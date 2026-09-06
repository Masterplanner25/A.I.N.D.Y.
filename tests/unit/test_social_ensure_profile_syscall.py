"""`sys.v1.social.ensure_profile` — provisioning a social profile at signup.

Before this syscall, `signup_initialization_service` created a UserIdentity, a memory node,
a user score and an initial agent run — **but no social profile**. A freshly registered
account therefore 404'd on `GET /apps/social/profile/{username}`, and `/profile/:username`
opened in create-mode for every new user. Walk-log item 4.

The load-bearing property is **degradation**, not creation. The social layer is
Mongo-backed and `docker-compose.prod.yml` ships without Mongo, so this must never turn a
registration into a failure. `test_missing_mongo_degrades_instead_of_raising` is the test
that matters; the rest describe the happy path.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.app_profile

SYSCALL = "sys.v1.social.ensure_profile"


def _handler():
    from apps.social.syscalls.syscall_handlers import _handle_ensure_profile

    return _handle_ensure_profile


def _ctx(user_id="11111111-1111-4111-8111-111111111111", db=None):
    from AINDY.kernel.syscall_registry import SyscallContext

    return SyscallContext(
        execution_unit_id="eu-1",
        user_id=user_id,
        capabilities=["social.write"],
        trace_id="t-1",
        metadata={"_db": db} if db is not None else {},
    )


class _FakeProfiles:
    def __init__(self, existing=None):
        self.existing = existing
        self.inserted = []

    def find_one(self, _query):
        return self.existing

    def insert_one(self, doc):
        self.inserted.append(doc)


class _FakeClient(dict):
    """`client[MONGO_DB_NAME]["profiles"]` — mimics pymongo's mapping access."""

    def __init__(self, profiles):
        super().__init__()
        self._profiles = profiles

    def __getitem__(self, _db_name):
        return {"profiles": self._profiles}


def test_registered_with_write_capability():
    """A profile write must not be reachable with a read capability."""
    import apps.bootstrap as bootstrap
    from AINDY.kernel.syscall_registry import SYSCALL_REGISTRY

    bootstrap.bootstrap()
    entry = SYSCALL_REGISTRY.get(SYSCALL)
    assert entry is not None, f"{SYSCALL} is not registered"
    assert entry.capability == "social.write"


def test_missing_mongo_degrades_instead_of_raising(monkeypatch):
    """★ The one that matters. Prod ships without Mongo; signup must still succeed."""
    import apps.social.syscalls.syscall_handlers as mod

    monkeypatch.setattr(
        "AINDY.db.mongo_setup.get_mongo_client", lambda: None, raising=True
    )

    result = mod._handle_ensure_profile({"user_id": "u-1"}, _ctx())

    assert result["created"] is False
    assert result["degraded"] is True
    assert result["reason"] == "mongodb_unavailable"


def test_creates_profile_from_the_canonical_username(monkeypatch):
    import apps.social.syscalls.syscall_handlers as mod

    profiles = _FakeProfiles(existing=None)
    monkeypatch.setattr(
        "AINDY.db.mongo_setup.get_mongo_client", lambda: _FakeClient(profiles), raising=True
    )
    monkeypatch.setattr(
        "apps.social.services.identity_binding_service.resolve_canonical_username",
        lambda _db, _uid: ("shawn", True),
        raising=True,
    )

    result = mod._handle_ensure_profile({"user_id": "u-1"}, _ctx(db=object()))

    assert result["created"] is True
    assert result["username"] == "shawn"
    assert len(profiles.inserted) == 1
    doc = profiles.inserted[0]
    assert doc["username"] == "shawn"
    assert doc["user_id"] == "u-1"
    # Created at signup from the canonical users.username, so it is verified — not the
    # unverified social-only path the HTTP route falls back to (SOCIAL-IDENTITY-1).
    assert doc["username_verified"] is True


def test_is_idempotent(monkeypatch):
    """Signup can be retried; a second run must not create a duplicate profile."""
    import apps.social.syscalls.syscall_handlers as mod

    profiles = _FakeProfiles(existing={"user_id": "u-1", "username": "shawn"})
    monkeypatch.setattr(
        "AINDY.db.mongo_setup.get_mongo_client", lambda: _FakeClient(profiles), raising=True
    )
    monkeypatch.setattr(
        "apps.social.services.identity_binding_service.resolve_canonical_username",
        lambda _db, _uid: ("shawn", True),
        raising=True,
    )

    result = mod._handle_ensure_profile({"user_id": "u-1"}, _ctx(db=object()))

    assert result["created"] is False
    assert result["reason"] == "already_exists"
    assert profiles.inserted == []


def test_no_canonical_username_is_not_a_degradation(monkeypatch):
    """Distinct from the Mongo case: the store is fine, the user simply has no username.

    Reported separately so an operator can tell "Mongo is off" from "this account cannot
    have a profile yet" — they need different responses.
    """
    import apps.social.syscalls.syscall_handlers as mod

    profiles = _FakeProfiles(existing=None)
    monkeypatch.setattr(
        "AINDY.db.mongo_setup.get_mongo_client", lambda: _FakeClient(profiles), raising=True
    )
    monkeypatch.setattr(
        "apps.social.services.identity_binding_service.resolve_canonical_username",
        lambda _db, _uid: (None, False),
        raising=True,
    )

    result = mod._handle_ensure_profile({"user_id": "u-1"}, _ctx(db=object()))

    assert result["created"] is False
    assert result["degraded"] is False
    assert result["reason"] == "no_canonical_username"
    assert profiles.inserted == []


def test_requires_a_user_id():
    import apps.social.syscalls.syscall_handlers as mod

    with pytest.raises(ValueError, match="user_id"):
        mod._handle_ensure_profile({}, _ctx(user_id=""))


class TestSignupTolerance:
    """Signup must survive a social step that fails.

    The score step raises on failure and the agent-run step does not; social follows the
    agent-run pattern, because it is the degradable one. This is the property that decides
    whether an absent Mongo can stop people registering.
    """

    def test_signup_completes_when_the_social_syscall_errors(self, monkeypatch):
        import apps.identity.services.signup_initialization_service as svc

        calls = []

        def fake_dispatch(name, payload, **kwargs):
            calls.append(name)
            if name == "sys.v1.social.ensure_profile":
                return {"status": "error", "error": "mongo exploded", "data": {}}
            return {"status": "success", "data": {"run_id": "run-1"}}

        monkeypatch.setattr(svc, "_ensure_user_score_via_syscall",
                            lambda **kw: {"master_score": 42.0}, raising=True)
        monkeypatch.setattr("AINDY.kernel.syscall_dispatcher.dispatch_syscall",
                            fake_dispatch, raising=True)
        monkeypatch.setattr(svc, "queue_system_event", lambda **kw: None, raising=True)
        monkeypatch.setattr(svc.MemoryNodeDAO, "save",
                            lambda self, **kw: {"id": "mem-1"}, raising=True)

        db = _StubSession()
        result = svc.initialize_signup_state(db=db, user=_StubUser())

        # Registration still produced its state — the social failure is absorbed.
        assert result["metrics"]["score"] == 42.0
        assert result["agent_context"]["run_id"] == "run-1"
        assert result["social_profile"] == {
            "created": False,
            "degraded": False,
            "username": None,
        }
        assert "sys.v1.social.ensure_profile" in calls

    def test_signup_reports_a_created_profile(self, monkeypatch):
        import apps.identity.services.signup_initialization_service as svc

        def fake_dispatch(name, payload, **kwargs):
            if name == "sys.v1.social.ensure_profile":
                return {"status": "success",
                        "data": {"created": True, "degraded": False, "username": "shawn"}}
            return {"status": "success", "data": {"run_id": "run-1"}}

        monkeypatch.setattr(svc, "_ensure_user_score_via_syscall",
                            lambda **kw: {"master_score": 1.0}, raising=True)
        monkeypatch.setattr("AINDY.kernel.syscall_dispatcher.dispatch_syscall",
                            fake_dispatch, raising=True)
        monkeypatch.setattr(svc, "queue_system_event", lambda **kw: None, raising=True)
        monkeypatch.setattr(svc.MemoryNodeDAO, "save",
                            lambda self, **kw: {"id": "mem-1"}, raising=True)

        result = svc.initialize_signup_state(db=_StubSession(), user=_StubUser())

        assert result["social_profile"]["created"] is True
        assert result["social_profile"]["username"] == "shawn"


class _StubUser:
    id = "11111111-1111-4111-8111-111111111111"
    email = "someone@example.com"
    created_at = None


class _StubQuery:
    def filter(self, *_a, **_k):
        return self

    def first(self):
        # A UserIdentity already exists, so the service skips creating one — keeps this
        # test about the social step rather than about identity rows.
        return object()


class _StubSession:
    def query(self, *_a, **_k):
        return _StubQuery()

    def add(self, *_a, **_k):
        pass

    def commit(self):
        pass

    def refresh(self, *_a, **_k):
        pass
