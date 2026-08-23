"""Phase 0 tests for the goal-attainment resolver.

The resolver's central contract is that it **never raises**. Every failure mode —
undeclared goal, unusable target, unknown unit, degraded domain — must return
``supported: False`` so the caller can fall back to the existing
``masterplan_progress`` formula without a try/except. These tests lock that down,
because the whole design depends on scoring being unable to regress when a domain is
down.

See docs/specs/MASTERPLAN_GOAL_ATTAINMENT_SPEC.md.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-required-length-1234567890")

pytestmark = pytest.mark.app_profile

ga = pytest.importorskip("apps.analytics.services.integration.goal_attainment")


# ── unit normalization ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("tasks", "tasks"),
        ("Tasks", "tasks"),
        ("  TASK  ", "tasks"),
        ("completed_tasks", "tasks"),
        ("USD", "usd"),
        ("$", "usd"),
        ("revenue", "usd"),
        ("Dollars", "usd"),
        ("books", "books"),
    ],
)
def test_aliases_fold_to_canonical_units(raw, expected):
    assert ga.normalize_unit(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", 42, [], {}])
def test_unusable_units_normalize_to_none(raw):
    assert ga.normalize_unit(raw) is None


def test_unknown_unit_passes_through_rather_than_crashing():
    # An unrecognised unit is preserved so the caller can report it; it simply has no
    # resolver and therefore comes back unsupported.
    assert ga.normalize_unit("bananas") == "bananas"


# ── unresolved paths — none of these may raise ────────────────────────────────


def _resolve(**kwargs):
    base = {"user_id": "u-1", "goal_unit": "tasks", "goal_value": 10, "masterplan_id": 1}
    base.update(kwargs)
    return ga.resolve_goal_attainment(None, **base)


def test_no_goal_unit_is_unresolved():
    result = _resolve(goal_unit=None)
    assert result["supported"] is False
    assert result["reason"] == "no_goal_unit"


def test_non_numeric_goal_value_is_unresolved():
    result = _resolve(goal_value="not-a-number")
    assert result["supported"] is False
    assert result["reason"] == "no_goal_value"


@pytest.mark.parametrize("target", [0, 0.0, -5])
def test_non_positive_goal_value_is_unresolved(target):
    """Guards the divide-by-zero and the meaningless-ratio case."""
    result = _resolve(goal_value=target)
    assert result["supported"] is False
    assert result["reason"] == "non_positive_goal_value"


def test_unsupported_unit_is_a_normal_answer():
    result = _resolve(goal_unit="books")
    assert result["supported"] is False
    assert result["reason"] == "unsupported_unit"
    assert result["unit"] == "books"


def test_resolver_exception_is_swallowed(monkeypatch):
    """A degraded domain must never break scoring."""
    def boom(*_args, **_kwargs):
        raise RuntimeError("domain is down")

    monkeypatch.setitem(ga._RESOLVERS, "tasks", boom)
    result = _resolve()
    assert result["supported"] is False
    assert result["reason"] == "resolver_failed"


def test_resolver_returning_none_is_unresolved(monkeypatch):
    monkeypatch.setitem(ga._RESOLVERS, "tasks", lambda *_a, **_k: None)
    result = _resolve()
    assert result["supported"] is False
    assert result["reason"] == "no_value"


# ── resolved paths ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,target,expected_pct,expected_raw",
    [
        (0, 10, 0.0, 0.0),
        (5, 10, 0.5, 0.5),
        (10, 10, 1.0, 1.0),
        (15, 10, 1.0, 1.5),   # clamped
    ],
)
def test_attainment_is_clamped_but_raw_ratio_is_preserved(
    monkeypatch, value, target, expected_pct, expected_raw
):
    """Overachievement must not inflate a score past its ceiling, but must stay visible."""
    monkeypatch.setitem(ga._RESOLVERS, "tasks", lambda *_a, **_k: float(value))
    result = _resolve(goal_value=target)

    assert result["supported"] is True
    assert result["value"] == float(value)
    assert result["attainment_pct"] == pytest.approx(expected_pct)
    assert result["raw_ratio"] == pytest.approx(expected_raw)


def test_supported_units_reports_what_resolves_today():
    # Phase 1 added usd (freelance) and the social counters. `playbooks` joined once
    # rippletrace gained a data supply and a get_goal_metric syscall — before that the
    # unit was aliased but had nothing behind it. `books` is still unresolvable:
    # authorship has only AuthorDB, with no publication concept to count.
    assert ga.supported_units() == [
        "clicks",
        "impressions",
        "playbooks",
        "posts",
        "tasks",
        "usd",
    ]


@pytest.mark.parametrize("unit", ["books"])
def test_units_without_a_domain_stay_unsupported(unit):
    """A unit nothing can answer reports *why*, so the caller can fall back cleanly."""
    result = _resolve(goal_unit=unit)
    assert result["supported"] is False
    assert result["reason"] == "unsupported_unit"


def test_playbooks_resolves_through_rippletrace(monkeypatch):
    monkeypatch.setitem(ga._RESOLVERS, "playbooks", lambda *_a, **_k: 3.0)
    result = _resolve(goal_unit="playbooks", goal_value=4)

    assert result["supported"] is True
    assert result["unit"] == "playbooks"
    assert result["value"] == 3.0
    assert result["attainment_pct"] == pytest.approx(0.75)


def test_playbooks_degrades_to_no_value_rather_than_zero():
    """A registered unit whose domain cannot answer is *unresolved*, not zero attainment.

    This is the live path in a bare unit-test database, where the `playbooks` table does
    not exist: rippletrace catches the error, reports `supported: False`, and the
    resolver turns that into `no_value`. Scoring against a phantom 0 would be worse than
    not scoring — it would read as "you have built no playbooks" when the truth is "we
    could not find out".
    """
    result = _resolve(goal_unit="playbooks", goal_value=4)

    assert result["supported"] is False
    assert result["reason"] == "no_value"
    assert result["value"] is None
    assert result["attainment_pct"] is None


# ── the tasks resolver ────────────────────────────────────────────────────────


def test_tasks_resolver_counts_only_completed(monkeypatch):
    monkeypatch.setattr(
        ga,
        "_dispatch",
        lambda *_a, **_k: {
            "tasks": [
                {"status": "completed"},
                {"status": "completed"},
                {"status": "pending"},
                {"status": "blocked"},
            ]
        },
    )
    assert ga._resolve_tasks(None, user_id="u-1", masterplan_id=1) == 2.0


def test_tasks_resolver_needs_a_plan_id():
    """Plan-scoped by design — a plan's goal is about that plan's work."""
    assert ga._resolve_tasks(None, user_id="u-1", masterplan_id=None) is None


def test_tasks_resolver_handles_a_failed_syscall(monkeypatch):
    # _dispatch returns {} on any non-success status.
    monkeypatch.setattr(ga, "_dispatch", lambda *_a, **_k: {})
    assert ga._resolve_tasks(None, user_id="u-1", masterplan_id=1) is None


def test_tasks_resolver_tolerates_a_malformed_payload(monkeypatch):
    monkeypatch.setattr(ga, "_dispatch", lambda *_a, **_k: {"tasks": "not-a-list"})
    assert ga._resolve_tasks(None, user_id="u-1", masterplan_id=1) is None


def test_tasks_resolver_survives_null_entries(monkeypatch):
    monkeypatch.setattr(
        ga, "_dispatch", lambda *_a, **_k: {"tasks": [None, {"status": "completed"}]}
    )
    assert ga._resolve_tasks(None, user_id="u-1", masterplan_id=1) == 1.0


# ── get_goal_metric resolvers (Phase 1: freelance, social) ────────────────────


@pytest.mark.parametrize(
    "unit,expected_domain",
    [
        ("usd", "sys.v1.freelance.get_goal_metric"),
        ("impressions", "sys.v1.social.get_goal_metric"),
        ("clicks", "sys.v1.social.get_goal_metric"),
        ("posts", "sys.v1.social.get_goal_metric"),
    ],
)
def test_each_unit_dispatches_to_its_own_domain(monkeypatch, unit, expected_domain):
    seen = {}

    def fake_dispatch(name, payload, **kwargs):
        seen["name"] = name
        seen["unit"] = payload.get("unit")
        return {"supported": True, "value": 7.0}

    monkeypatch.setattr(ga, "_dispatch", fake_dispatch)
    result = _resolve(goal_unit=unit, goal_value=10)

    assert seen["name"] == expected_domain
    # The canonical unit must reach the domain, not the caller's raw spelling.
    assert seen["unit"] == unit
    assert result["value"] == 7.0


def test_alias_is_normalized_before_dispatch(monkeypatch):
    seen = {}

    def fake_dispatch(name, payload, **kwargs):
        seen["unit"] = payload.get("unit")
        return {"supported": True, "value": 1.0}

    monkeypatch.setattr(ga, "_dispatch", fake_dispatch)
    _resolve(goal_unit="$", goal_value=10)
    assert seen["unit"] == "usd"


def test_domain_reporting_unsupported_yields_unresolved(monkeypatch):
    """A domain that cannot answer must not be read as an achievement of 0."""
    monkeypatch.setattr(ga, "_dispatch", lambda *_a, **_k: {"supported": False, "value": 0.0})
    result = _resolve(goal_unit="usd", goal_value=1000)
    assert result["supported"] is False
    assert result["reason"] == "no_value"


def test_degraded_domain_yields_unresolved_not_zero(monkeypatch):
    """Social degrades when Mongo is down — that must not score as 0 progress."""
    monkeypatch.setattr(
        ga, "_dispatch", lambda *_a, **_k: {"supported": False, "value": 0.0, "reason": "degraded"}
    )
    result = _resolve(goal_unit="impressions", goal_value=500)
    assert result["supported"] is False
    assert result["attainment_pct"] is None


def test_failed_syscall_yields_unresolved(monkeypatch):
    # _dispatch returns {} on non-success; .get("supported") is then falsy.
    monkeypatch.setattr(ga, "_dispatch", lambda *_a, **_k: {})
    result = _resolve(goal_unit="usd", goal_value=1000)
    assert result["supported"] is False


@pytest.mark.parametrize("bad", [None, "not-a-number", [], {}])
def test_non_numeric_domain_value_yields_unresolved(monkeypatch, bad):
    monkeypatch.setattr(ga, "_dispatch", lambda *_a, **_k: {"supported": True, "value": bad})
    result = _resolve(goal_unit="usd", goal_value=1000)
    assert result["supported"] is False
    assert result["reason"] == "no_value"


def test_revenue_attainment_resolves_end_to_end(monkeypatch):
    monkeypatch.setattr(ga, "_dispatch", lambda *_a, **_k: {"supported": True, "value": 25000.0})
    result = _resolve(goal_unit="revenue", goal_value=100000)

    assert result["supported"] is True
    assert result["unit"] == "usd"
    assert result["value"] == 25000.0
    assert result["attainment_pct"] == pytest.approx(0.25)


# ── active-plan wrapper ───────────────────────────────────────────────────────


def test_no_active_plan_is_unresolved(monkeypatch):
    monkeypatch.setattr(ga, "get_symbol", lambda _name: None)
    result = ga.resolve_for_active_plan(None, "u-1")
    assert result["supported"] is False
    assert result["reason"] == "masterplan_model_unavailable"
