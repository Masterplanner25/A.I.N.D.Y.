"""Outbound automation connectors — FR-1 capability-enforced dispatch.

The connectors (social / crm / email / webhook / stripe / subscription) are registered
with the runtime via `register_connector` and dispatched through
`connector_service.dispatch_connector` instead of a hardcoded app-side if/elif ladder.
Each handler performs outbound I/O through `ctx.call` (the enforcement-enabled successor
to `perform_external_call`), so the same authorization scope the runtime applies to agent
tools now applies to connector egress.

`authorized_external_call` (what `ctx.call` delegates to) and `urlopen` are faked here —
we assert the app's branch selection, payload/auth construction, that outbound calls are
routed through the capability boundary, and the envelope→exception contract, not the
runtime's enforcement internals or real network I/O. Backward-compatible fallbacks (CRM
record-only, social internal-only) are covered too.
"""

from __future__ import annotations

import json

import pytest

import AINDY.platform_layer.external_call_service as ecs
import apps.automation.services.automation_execution_service as aes

pytestmark = pytest.mark.app_profile


@pytest.fixture(autouse=True)
def _register_connectors():
    """Connectors are registered at app bootstrap; register them for direct-call tests."""
    aes.register_automation_connectors(overwrite=True)


class _FakeResp:
    status = 200

    def __init__(self, body: bytes = b'{"ok": true}'):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


@pytest.fixture
def capture_http(monkeypatch):
    """Fake the runtime authorized-call boundary (running the operation) + urlopen."""
    calls: dict[str, list] = {"external": [], "requests": []}

    def fake_authorized(*, service_name, capability=None, operation, endpoint=None,
                        method=None, extra=None, **_kw):
        calls["external"].append(
            {"service_name": service_name, "capability": capability,
             "endpoint": endpoint, "method": method, "extra": extra}
        )
        return operation()

    def fake_urlopen(req, timeout=None):
        calls["requests"].append(req)
        return _FakeResp()

    # ctx.call imports authorized_external_call from this module at call time.
    monkeypatch.setattr(ecs, "authorized_external_call", fake_authorized)
    monkeypatch.setattr(aes.urllib_request, "urlopen", fake_urlopen)
    return calls


class _FakeInsert:
    inserted_id = "post123"


class _FakeCollection:
    def __init__(self):
        self.docs: list[dict] = []

    def insert_one(self, doc):
        self.docs.append(doc)
        return _FakeInsert()


class _FakeMongo:
    def __init__(self, coll):
        self._coll = coll

    def __getitem__(self, _db_name):
        return {"posts": self._coll}


@pytest.fixture
def fake_mongo(monkeypatch):
    import AINDY.db.mongo_setup as mongo_setup

    coll = _FakeCollection()
    monkeypatch.setattr(mongo_setup, "require_mongo_client", lambda *a, **k: _FakeMongo(coll))
    monkeypatch.setattr(mongo_setup, "MONGO_DB_NAME", "test_db", raising=False)
    return coll


# --------------------------------------------------------------------------- #
# Registration (FR-1)
# --------------------------------------------------------------------------- #
def test_connectors_registered_with_capabilities():
    from AINDY.platform_layer.registry import get_connector

    for ct in ("social", "crm", "email", "webhook", "stripe", "subscription"):
        entry = get_connector(ct)
        assert entry is not None, f"{ct} connector not registered"
        assert entry["capability"] == f"outbound.{ct}"


# --------------------------------------------------------------------------- #
# CRM connector
# --------------------------------------------------------------------------- #
def test_crm_records_internally_without_endpoint(capture_http):
    result = aes.execute_automation_action(
        {
            "automation_type": "crm",
            "task_id": 7,
            "automation_config": {"action": "follow_up", "contact": "a@b.com"},
        },
        None,
    )
    assert result["status"] == "recorded"
    assert result["delivery"] == "internal"
    assert result["action"] == "follow_up"
    assert result["contact"] == "a@b.com"
    assert capture_http["external"] == []  # no outbound call was made


def test_crm_posts_to_external_endpoint(capture_http):
    result = aes.execute_automation_action(
        {
            "automation_type": "crm",
            "user_id": "u1",
            "task_name": "Sync lead",
            "automation_config": {
                "endpoint": "https://crm.example.com/contacts",
                "api_key": "secret",
                "action": "upsert",
                "contact": "lead@example.com",
                "details": "post-call note",
            },
        },
        None,
    )
    assert result["status"] == "completed"
    assert result["delivery"] == "external"
    assert result["response"]["status_code"] == 200

    ext = capture_http["external"][0]
    assert ext["service_name"] == "crm"
    assert ext["endpoint"] == "https://crm.example.com/contacts"
    assert ext["method"] == "http.post"

    req = capture_http["requests"][0]
    assert req.full_url == "https://crm.example.com/contacts"
    assert req.get_method() == "POST"
    assert req.get_header("Authorization") == "Bearer secret"
    sent = json.loads(req.data.decode("utf-8"))
    assert sent["action"] == "upsert"
    assert sent["contact"] == "lead@example.com"
    assert sent["details"] == "post-call note"


# --------------------------------------------------------------------------- #
# Social connector
# --------------------------------------------------------------------------- #
def test_social_internal_only_without_external_target(capture_http, fake_mongo):
    result = aes.execute_automation_action(
        {
            "automation_type": "social",
            "user_id": "u1",
            "automation_config": {"content": "hello world"},
        },
        None,
    )
    assert result["status"] == "completed"
    assert result["delivery"] == "internal"
    assert result["post_id"] == "post123"
    assert capture_http["external"] == []  # no external publish
    assert fake_mongo.docs[0]["content"] == "hello world"  # internal feed post written


def test_social_also_delivers_externally_when_configured(capture_http, fake_mongo):
    result = aes.execute_automation_action(
        {
            "automation_type": "social",
            "user_id": "u1",
            "automation_config": {
                "content": "launch post",
                "external_endpoint": "https://social.example.com/publish",
                "external_api_key": "tok",
            },
        },
        None,
    )
    assert result["delivery"] == "internal+external"
    assert result["post_id"] == "post123"  # internal feed post still written
    assert result["external_response"]["status_code"] == 200
    assert fake_mongo.docs[0]["content"] == "launch post"

    ext = capture_http["external"][0]
    assert ext["service_name"] == "social"
    assert ext["endpoint"] == "https://social.example.com/publish"

    req = capture_http["requests"][0]
    assert req.get_header("Authorization") == "Bearer tok"
    sent = json.loads(req.data.decode("utf-8"))
    assert sent["content"] == "launch post"


# --------------------------------------------------------------------------- #
# Guards / regression
# --------------------------------------------------------------------------- #
def test_unsupported_automation_type_raises(capture_http):
    with pytest.raises(ValueError, match="unsupported_automation_type"):
        aes.execute_automation_action({"automation_type": "bogus"}, None)


def test_social_requires_content(capture_http, fake_mongo):
    with pytest.raises(ValueError, match="social_content_required"):
        aes.execute_automation_action(
            {"automation_type": "social", "automation_config": {}}, None
        )


def test_content_generation_stays_internal(capture_http):
    # content_generation has no outbound I/O -> handled locally, not via a connector.
    result = aes.execute_automation_action(
        {"automation_type": "content_generation", "automation_config": {"prompt": "hi"}},
        None,
    )
    assert result["status"] == "completed"
    assert result["generated_content"]
    assert capture_http["external"] == []


def test_capability_denial_raises_permission_error(monkeypatch, capture_http):
    # A capability/policy/rate denial comes back as a denied envelope -> PermissionError.
    def _deny(*, operation, **_kw):
        raise ecs.OutboundCallDenied("outbound 'crm' denied: host not allowed")

    monkeypatch.setattr(ecs, "authorized_external_call", _deny)
    with pytest.raises(PermissionError, match="denied"):
        aes.execute_automation_action(
            {
                "automation_type": "crm",
                "user_id": "u1",
                "automation_config": {"endpoint": "https://blocked.example.com", "contact": "x@y.z"},
            },
            None,
        )


# ── Runtime transactional email (aindy-runtime >= 2.0.0) ──────────────────────────
# The runtime sends its OWN mail — email verification and password reset — through this
# same registered `email` connector, but with a different action shape:
#   {"type": "send", "to": ..., "subject": ..., "body": ...}
# with no "payload"/"config". The handler used to open with action["payload"], so every
# one of those raised KeyError. Because a registered connector that FAILS is deliberately
# never retried over SMTP, that was terminal: no verification mail could be sent, so no
# new account could complete signup, with only a log warning to explain it.


class _FakeSMTP:
    """Records what would have gone over the wire."""

    sent: list[dict] = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port
        self._started_tls = False
        self._login = None

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def starttls(self):
        self._started_tls = True

    def login(self, user, password):
        self._login = user

    def send_message(self, message):
        _FakeSMTP.sent.append(
            {
                "host": self.host,
                "port": self.port,
                "to": message["To"],
                "from": message["From"],
                "subject": message["Subject"],
                "starttls": self._started_tls,
                "login": self._login,
            }
        )


@pytest.fixture
def fake_smtp(monkeypatch):
    _FakeSMTP.sent = []
    monkeypatch.setattr(aes.smtplib, "SMTP", _FakeSMTP)
    return _FakeSMTP


@pytest.fixture
def smtp_settings(monkeypatch):
    from AINDY.config import settings

    for key, value in {
        "AINDY_SMTP_HOST": "mail.test",
        "AINDY_SMTP_PORT": 2525,
        "AINDY_SMTP_FROM": "noreply@test.local",
        "AINDY_SMTP_USER": "",
        "AINDY_SMTP_PASSWORD": "",
        "AINDY_SMTP_STARTTLS": False,
    }.items():
        monkeypatch.setattr(settings, key, value, raising=False)
    return settings


def test_email_connector_handles_runtime_transactional_shape(
    capture_http, fake_smtp, smtp_settings
):
    result = aes._email_connector(
        {"type": "send", "to": "user@example.com", "subject": "Verify", "body": "link"},
        _CtxShim(),
    )

    assert result["status"] == "completed"
    assert result["recipient"] == "user@example.com"
    assert fake_smtp.sent == [
        {
            "host": "mail.test",
            "port": 2525,
            "to": "user@example.com",
            "from": "noreply@test.local",
            "subject": "Verify",
            "starttls": False,
            "login": None,
        }
    ]
    # Still routed through the capability boundary, not a raw socket.
    assert capture_http["external"]
    assert capture_http["external"][-1]["service_name"] == "smtp"


def test_email_connector_reports_missing_smtp_rather_than_key_error(
    capture_http, fake_smtp, monkeypatch
):
    from AINDY.config import settings

    monkeypatch.setattr(settings, "AINDY_SMTP_HOST", "", raising=False)
    monkeypatch.setattr(settings, "AINDY_SMTP_FROM", "", raising=False)

    # A clear "not configured" error, never KeyError('payload').
    with pytest.raises(ValueError, match="email_smtp_not_configured"):
        aes._email_connector(
            {"type": "send", "to": "user@example.com", "subject": "s", "body": "b"},
            _CtxShim(),
        )
    assert fake_smtp.sent == []


def test_email_connector_still_handles_the_automation_shape(capture_http, fake_smtp):
    # The original app-authored automation path is unchanged: per-action SMTP config.
    result = aes.execute_automation_action(
        {
            "automation_type": "email",
            "user_id": "u1",
            "automation_config": {
                "recipient": "lead@example.com",
                "subject": "Hello",
                "body": "Body",
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "smtp_starttls": False,
            },
        },
        None,
    )

    assert result["status"] == "completed"
    assert result["recipient"] == "lead@example.com"
    assert fake_smtp.sent[-1]["host"] == "smtp.example.com"


class _CtxShim:
    """Minimal stand-in for the connector ctx: runs the operation through ctx.call."""

    def call(self, *, service_name, endpoint=None, method=None, extra=None, operation):
        return ecs.authorized_external_call(
            service_name=service_name,
            capability=f"outbound.{service_name}",
            operation=operation,
            endpoint=endpoint,
            method=method,
            extra=extra,
        )
