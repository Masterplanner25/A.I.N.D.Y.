"""Worth is scored per declaration kind, never as a cross-kind sum.

`SOAK_AUDIT_2026-08-15` §2b found `declared_worth_summary` summing three incommensurable
kinds into one total and feeding it through a single saturation scale of 100. The result:

    monetary_potential: 5000  (a modest contract)  -> 100.0   saturated, permanently
    strategic: 8              (a rating)           ->   7.7
    both together                                  -> 100.0   the strategic one is invisible

One ordinary money figure pinned the axis at its ceiling forever and drowned every
non-monetary declaration. The audit's verdict was that collecting declarations was unsafe
until this was fixed, because declaring against those maths produces a *confidently wrong*
Worth score — worse than an empty one, and undetectable downstream.

That is why these tests pin the audit's exact table: it is the specification.

Note that `strategic: 8 -> 7.7` is asserted UNCHANGED. The non-monetary maths was never the
defect; only the monetary scale and the combination rule were.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-required-length-1234567890")

pytestmark = pytest.mark.app_profile

three_axis = pytest.importorskip("apps.analytics.services.scoring.three_axis_service")


# Resolved lazily, NOT at module import. Binding these at the top made the whole file fail to
# COLLECT against the pre-fix implementation (AttributeError), which proves only that the
# helper is new — it hides whether the numbers changed. Lazy lookup lets the `compute_worth`
# tests at the bottom run against either implementation and fail on the actual value.
def _worth_kind_score(kind: str, total: float) -> float:
    return three_axis._worth_kind_score(kind, total)


def _scales() -> dict[str, float]:
    return three_axis.WORTH_KIND_SCALES


def _composite(**kind_totals: float) -> float:
    """Mirror compute_worth's combination rule over raw per-kind totals."""
    subs = [_worth_kind_score(k, v) for k, v in kind_totals.items()]
    present = [s for s in subs if s > 0]
    return (sum(present) / len(present)) if present else 0.0


# ── the audit's table, which is the spec ───────────────────────────────────────────────

def test_a_modest_contract_no_longer_saturates_the_axis():
    """$5,000 used to score 100.0 — the ceiling, permanently, from one modest declaration."""
    score = _worth_kind_score("monetary_potential", 5000.0)
    assert score == pytest.approx(9.52, abs=0.01)
    assert score < 20.0, "a modest contract must leave headroom on a 0-100 axis"


def test_the_non_monetary_scale_is_unchanged():
    """strategic 8 -> 7.7 before and after. This half was never broken; do not 'fix' it."""
    assert _worth_kind_score("strategic", 8.0) == pytest.approx(7.69, abs=0.01)
    assert _worth_kind_score("intrinsic", 8.0) == pytest.approx(7.69, abs=0.01)


def test_money_no_longer_drowns_a_non_monetary_declaration():
    """The original defect: declaring both produced 100.0 and the strategic one vanished."""
    both = _composite(monetary_potential=5000.0, strategic=8.0)
    assert both == pytest.approx(8.60, abs=0.01)

    # The decisive property — the combined figure must sit between the two parts, not at the
    # ceiling. A sum-then-saturate implementation cannot satisfy this.
    money_only = _worth_kind_score("monetary_potential", 5000.0)
    strategic_only = _worth_kind_score("strategic", 8.0)
    assert min(strategic_only, money_only) <= both <= max(strategic_only, money_only)
    assert both < 100.0


# ── the properties that keep it correct ────────────────────────────────────────────────

def test_kinds_are_scored_in_their_own_units():
    """Dollars need a dollar-sized denominator; ratings do not. Equal numbers must differ."""
    assert _worth_kind_score("monetary_potential", 100.0) != _worth_kind_score("strategic", 100.0)
    assert _scales()["monetary_potential"] > _scales()["strategic"]


def test_an_absent_kind_is_unknown_not_zero():
    """Averaging in undeclared kinds would penalise expressing worth in one dimension."""
    one_kind = _composite(strategic=8.0)
    assert one_kind == pytest.approx(_worth_kind_score("strategic", 8.0))
    # If absent kinds counted as 0, this would be a third of the value.
    assert one_kind > _worth_kind_score("strategic", 8.0) / 2


def test_no_declarations_scores_zero_not_an_error():
    assert _composite() == 0.0
    assert _worth_kind_score("strategic", 0.0) == 0.0


def test_an_unknown_kind_falls_back_to_relative_units():
    """A kind added to the model without a scale must not divide by zero or saturate."""
    assert _worth_kind_score("some_future_kind", 8.0) == pytest.approx(7.69, abs=0.01)


def test_every_declared_kind_has_a_scale():
    """The model's VALID_WORTH_KINDS and the scale table must not drift apart."""
    from apps.analytics.value_declaration import VALID_WORTH_KINDS

    missing = VALID_WORTH_KINDS - set(_scales())
    assert not missing, f"kinds with no declared scale: {sorted(missing)}"


def test_scores_stay_bounded_for_absurd_declarations():
    """The axis is 0..100. A declaration cannot push it past the ceiling or below zero."""
    for kind in ("monetary_potential", "strategic", "intrinsic"):
        assert 0.0 <= _worth_kind_score(kind, 10**9) <= 100.0
        assert _worth_kind_score(kind, -5.0) == 0.0


def test_the_score_is_monotonic_within_a_kind():
    """More declared worth in a kind must never lower that kind's sub-score."""
    prior = -1.0
    for total in (0.0, 1.0, 100.0, 5000.0, 50000.0, 250000.0):
        current = _worth_kind_score("monetary_potential", total)
        assert current >= prior
        prior = current


# ── through the public function, so the fix is proven end to end ───────────────────────
#
# The tests above exercise `_worth_kind_score`, which did not exist before the fix — so
# against the old implementation they fail at collection rather than on a value. That proves
# the helper is new, not that the behaviour changed. These go through `compute_worth`, which
# existed before and after, so they fail on the ACTUAL NUMBER (100.0 vs 8.6) either way.

class _FakeSummary:
    """Stand in for declared_worth_summary so no database is required."""

    def __init__(self, by_kind: dict[str, float]):
        self.by_kind = by_kind

    def __call__(self, db, user_id):
        return {
            "total": round(sum(self.by_kind.values()), 2),
            "by_kind": dict(self.by_kind),
            "count": len(self.by_kind),
        }


@pytest.fixture
def worth_of(monkeypatch):
    """Return compute_worth's output for a given set of per-kind totals."""
    from apps.analytics.services.scoring import value_declaration_service

    def _run(**by_kind: float):
        monkeypatch.setattr(
            value_declaration_service, "declared_worth_summary", _FakeSummary(by_kind)
        )
        monkeypatch.setattr(three_axis, "_realized_revenue", lambda db, user_id: 0.0)
        return three_axis.compute_worth(None, "11111111-1111-1111-1111-111111111111")

    return _run


def test_compute_worth_reproduces_the_audit_table(worth_of):
    """The three rows of SOAK_AUDIT §2b, through the real function. Was 100.0 / 7.7 / 100.0."""
    assert worth_of(monetary_potential=5000.0)["score"] == pytest.approx(9.52, abs=0.01)
    assert worth_of(strategic=8.0)["score"] == pytest.approx(7.69, abs=0.01)
    assert worth_of(monetary_potential=5000.0, strategic=8.0)["score"] == pytest.approx(8.60, abs=0.01)


def test_compute_worth_exposes_a_sub_score_per_kind(worth_of):
    """Without this the composite is a number nobody can interpret or check."""
    out = worth_of(monetary_potential=5000.0, strategic=8.0)
    assert set(out["score_by_kind"]) == {"monetary_potential", "strategic"}
    assert out["score_by_kind"]["strategic"] == pytest.approx(7.69, abs=0.01)


def test_declared_total_is_retained_but_does_not_drive_the_score(worth_of):
    """The shadow ledger has a column for it and the KPI panel renders it — so it stays.

    But it is a mixed-unit sum, and the score must no longer be derived from it. Two very
    different declarations with the SAME total must score differently.
    """
    money = worth_of(monetary_potential=1000.0)
    rating = worth_of(strategic=1000.0)

    assert money["declared_total"] == rating["declared_total"] == 1000.0
    assert money["score"] != rating["score"], (
        "identical mixed-unit totals scored the same — the score is still following the sum"
    )
