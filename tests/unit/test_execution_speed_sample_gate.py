"""`execution_speed` weighs in proportion to the completions it rests on (§9.4 option C).

Owner's decision 2026-09-23 (`INFINITY_SCORE_MODEL.md` §9.4): at four lifetime completions the
KPI swung 44.66 → 11.92 in a day because two tasks aged out of the 14-day window, and it carried
the full 0.25 in the master while doing it. Below `EXECUTION_SPEED_FULL_WEIGHT_AT` completions its
weight ramps linearly and the freed share goes to the other four KPIs pro rata.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from apps.analytics.services.scoring import infinity_service
from apps.analytics.services.scoring.kpi_weight_service import (
    EXECUTION_SPEED_FULL_WEIGHT_AT,
    sample_gated_weights,
)
from apps.analytics.user_score import KPI_WEIGHTS

pytestmark = pytest.mark.app_profile


def _gate(samples, weights=None):
    return sample_gated_weights(
        dict(weights or KPI_WEIGHTS),
        kpi="execution_speed",
        samples=samples,
        full_at=EXECUTION_SPEED_FULL_WEIGHT_AT,
    )


def test_the_threshold_is_the_decided_ten():
    assert EXECUTION_SPEED_FULL_WEIGHT_AT == 10


@pytest.mark.parametrize("samples", [0, 1, 4, 9, 10, 40])
def test_the_weights_still_sum_to_one(samples):
    assert sum(_gate(samples).values()) == pytest.approx(1.0)


def test_four_completions_carry_four_tenths_of_the_weight():
    gated = _gate(4)
    assert gated["execution_speed"] == pytest.approx(0.25 * 0.4)  # 0.10


def test_the_freed_weight_goes_to_the_others_in_proportion():
    gated = _gate(4)
    freed = 0.25 * 0.6
    others = {k: v for k, v in KPI_WEIGHTS.items() if k != "execution_speed"}
    total = sum(others.values())
    for key, base in others.items():
        assert gated[key] == pytest.approx(base + freed * base / total)
    # proportions among the other four are unchanged
    assert gated["decision_efficiency"] / gated["focus_quality"] == pytest.approx(0.25 / 0.15)


def test_zero_completions_take_execution_speed_out_entirely():
    assert _gate(0)["execution_speed"] == 0.0


@pytest.mark.parametrize("samples", [10, 11, 400])
def test_at_or_past_the_threshold_nothing_changes(samples):
    assert _gate(samples) == KPI_WEIGHTS


def test_learned_weights_are_gated_the_same_way_and_not_mutated():
    learned = {
        "execution_speed": 0.30,
        "decision_efficiency": 0.20,
        "ai_productivity_boost": 0.20,
        "focus_quality": 0.15,
        "masterplan_progress": 0.15,
    }
    before = dict(learned)
    gated = sample_gated_weights(learned, kpi="execution_speed", samples=5, full_at=10)
    assert learned == before
    assert gated["execution_speed"] == pytest.approx(0.15)
    assert sum(gated.values()) == pytest.approx(1.0)


def _stub_tasks(monkeypatch, end_times):
    tasks = [{"status": "completed", "end_time": t.isoformat()} for t in end_times]
    tasks.append({"status": "pending", "end_time": None})
    monkeypatch.setattr(infinity_service, "_get_user_tasks_for_scoring", lambda user_id, db: tasks)


def test_the_sample_is_lifetime_completions_from_the_same_fetch(monkeypatch):
    now = datetime.now(timezone.utc)
    _stub_tasks(monkeypatch, [now - timedelta(days=17), now - timedelta(days=16), now - timedelta(hours=3)])
    score, recent, completed = infinity_service._execution_speed_with_sample("u-1", None)
    assert completed == 3  # lifetime, pending excluded
    assert recent == 1  # the 14-day window, as before


def test_the_public_function_keeps_its_two_value_contract(monkeypatch):
    now = datetime.now(timezone.utc)
    _stub_tasks(monkeypatch, [now - timedelta(days=2)])
    result = infinity_service.calculate_execution_speed("u-1", None)
    assert isinstance(result, tuple) and len(result) == 2
    assert result == infinity_service._execution_speed_with_sample("u-1", None)[:2]
