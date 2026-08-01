"""Contract tests for the ``sys.v1.<domain>.get_goal_metric`` syscalls (Phase 1).

The resolver in ``apps/analytics/services/integration/goal_attainment.py`` treats
``supported: False`` as "fall back to the existing formula" and anything else as a real
measurement. These tests pin the producer side of that contract: a domain that cannot
answer must say so explicitly rather than returning a 0 that would be scored as genuine
lack of progress.

The distinction matters most for social, which reads Mongo and degrades gracefully — a
degraded read must not look like "you have zero impressions".

See docs/handoffs/MASTERPLAN_GOAL_ATTAINMENT_SPEC.md §3.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-required-length-1234567890")

pytestmark = pytest.mark.app_profile

freelance_syscalls = pytest.importorskip("apps.freelance.syscalls")
social_syscalls = pytest.importorskip("apps.social.syscalls.syscall_handlers")


class _Ctx:
    """Minimal stand-in for SyscallContext (only user_id/metadata are read here)."""

    def __init__(self, user_id: str | None = "11111111-1111-1111-1111-111111111111"):
        self.user_id = user_id
        self.metadata: dict = {}


def _assert_contract_shape(result: dict) -> None:
    """Every response, supported or not, must carry these keys with these types."""
    assert isinstance(result, dict)
    assert isinstance(result.get("supported"), bool)
    assert "unit" in result
    assert isinstance(result.get("value"), float)


# ── freelance ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("unit", ["books", "impressions", "", "tasks"])
def test_freelance_rejects_units_it_does_not_own(unit):
    result = freelance_syscalls._handle_freelance_goal_metric({"unit": unit}, _Ctx())
    assert result["supported"] is False
    _assert_contract_shape(result)


def test_freelance_requires_a_user():
    """Revenue is per-user; without an identity there is nothing meaningful to answer."""
    result = freelance_syscalls._handle_freelance_goal_metric(
        {"unit": "usd"}, _Ctx(user_id=None)
    )
    assert result["supported"] is False
    _assert_contract_shape(result)


@pytest.mark.parametrize("unit", ["usd", "USD", " revenue "])
def test_freelance_accepts_its_units_case_and_space_insensitively(monkeypatch, unit):
    """Normalization happens in the resolver, but the handler must not be brittle."""

    class _Q:
        def filter(self, *_a):
            return self

        def all(self):
            return [type("O", (), {"price": 1500.0})(), type("O", (), {"price": 500.0})()]

    class _DB:
        def query(self, *_a):
            return _Q()

        def close(self):
            pass

    monkeypatch.setattr(freelance_syscalls, "_session_from_context", lambda _ctx: (_DB(), False))
    result = freelance_syscalls._handle_freelance_goal_metric({"unit": unit}, _Ctx())

    assert result["supported"] is True
    assert result["unit"] == "usd"
    assert result["value"] == 2000.0
    assert result["scope"] == "user"
    _assert_contract_shape(result)


def test_freelance_null_prices_do_not_break_the_sum(monkeypatch):
    class _Q:
        def filter(self, *_a):
            return self

        def all(self):
            return [type("O", (), {"price": None})(), type("O", (), {"price": 250.0})()]

    class _DB:
        def query(self, *_a):
            return _Q()

        def close(self):
            pass

    monkeypatch.setattr(freelance_syscalls, "_session_from_context", lambda _ctx: (_DB(), False))
    result = freelance_syscalls._handle_freelance_goal_metric({"unit": "usd"}, _Ctx())
    assert result["value"] == 250.0


# ── social ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("unit", ["usd", "books", "", "tasks"])
def test_social_rejects_units_it_does_not_own(unit):
    result = social_syscalls._handle_social_goal_metric({"unit": unit}, _Ctx())
    assert result["supported"] is False
    _assert_contract_shape(result)


@pytest.mark.parametrize(
    "unit,key,expected",
    [
        ("impressions", "total_impressions", 1200.0),
        ("clicks", "total_clicks", 34.0),
        ("posts", "post_count", 9.0),
    ],
)
def test_social_maps_each_unit_to_its_overview_counter(monkeypatch, unit, key, expected):
    # The handler imports inside the function body, so patch the source module.
    import apps.social.services.social_performance_service as sps

    monkeypatch.setattr(
        sps, "summarize_social_performance", lambda **_k: {"overview": {key: expected}}
    )

    result = social_syscalls._handle_social_goal_metric({"unit": unit}, _Ctx())
    assert result["supported"] is True
    assert result["value"] == expected
    _assert_contract_shape(result)


def test_social_degraded_read_is_unsupported_not_zero(monkeypatch):
    """Mongo down must not be scored as 'you achieved nothing'."""
    import apps.social.services.social_performance_service as sps

    monkeypatch.setattr(
        sps,
        "summarize_social_performance",
        lambda **_k: {"status": "degraded", "data": [], "reason": "mongodb_unavailable"},
    )

    result = social_syscalls._handle_social_goal_metric({"unit": "impressions"}, _Ctx())
    assert result["supported"] is False
    assert result["reason"] == "degraded"
    _assert_contract_shape(result)


def test_social_missing_counter_reads_as_zero_not_a_crash(monkeypatch):
    import apps.social.services.social_performance_service as sps

    monkeypatch.setattr(sps, "summarize_social_performance", lambda **_k: {"overview": {}})
    result = social_syscalls._handle_social_goal_metric({"unit": "clicks"}, _Ctx())
    assert result["supported"] is True
    assert result["value"] == 0.0


# ── registration ──────────────────────────────────────────────────────────────


def test_both_goal_metric_syscalls_are_registered(monkeypatch):
    """The resolver dispatches by name; a rename here silently breaks attainment.

    Patched at each module's own binding — both do `from ... import register_syscall`,
    so they hold their own reference and patching the registry module has no effect.
    """
    registered: list[str] = []

    def _capture(name=None, *args, **kwargs):
        # freelance registers with name=, social positionally.
        registered.append(name if name is not None else (args[0] if args else ""))
        return None

    monkeypatch.setattr(freelance_syscalls, "register_syscall", _capture)
    monkeypatch.setattr(social_syscalls, "register_syscall", _capture)

    freelance_syscalls.register_freelance_syscall_handlers()
    social_syscalls.register_all()

    assert "sys.v1.freelance.get_goal_metric" in registered
    assert "sys.v1.social.get_goal_metric" in registered


def test_registered_capabilities_are_domain_scoped(monkeypatch):
    """Attainment reads must not require a broader capability than the domain's own."""
    seen: dict[str, str] = {}

    def _capture_freelance(name=None, handler=None, capability=None, **kwargs):
        seen[name] = capability
        return None

    def _capture_social(name, handler=None, capability=None, *args, **kwargs):
        seen[name] = capability
        return None

    monkeypatch.setattr(freelance_syscalls, "register_syscall", _capture_freelance)
    monkeypatch.setattr(social_syscalls, "register_syscall", _capture_social)

    freelance_syscalls.register_freelance_syscall_handlers()
    social_syscalls.register_all()

    assert seen["sys.v1.freelance.get_goal_metric"] == "freelance.read"
    assert seen["sys.v1.social.get_goal_metric"] == "social.read"
