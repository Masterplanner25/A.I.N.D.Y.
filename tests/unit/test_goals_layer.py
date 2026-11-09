"""GOALS_LAYER_SPEC phase A: a goal's progress follows from its measure (decided 2026-11-09).

anchor → the anchor resolver; objectives → the linked objectives' attainment; declared → no number. Keyword-overlap
progress is retired (decision 3), and only a measured goal may override the loop's next action (decision 4). Nothing
is manufactured: an unmeasured goal reads None, never 0.
"""
from __future__ import annotations

import uuid

import pytest

from apps.masterplan.services import goal_service as gs

pytestmark = pytest.mark.app_profile


@pytest.fixture
def owner():
    return str(uuid.uuid4())


@pytest.fixture
def anchor_job(monkeypatch):
    """The analytics anchor resolver, swapped for a controllable one."""
    import AINDY.platform_layer.registry as registry

    answers = {"value": {"supported": True, "attainment_pct": 0.25, "reason": None}}
    real_get_job = registry.get_job

    def get_job(name):
        if name == "analytics.resolve_goal_attainment":
            return lambda db, **kw: answers["value"]
        return real_get_job(name)

    monkeypatch.setattr(registry, "get_job", get_job)
    return answers


def test_a_declared_goal_has_no_number_and_is_not_measured(db_session, owner):
    goal = gs.create_goal(db_session, user_id=owner, name="Positive feedback from users and stakeholders",
                          source="success_criterion", measure="declared")
    assert goal["progress"] is None and goal["measured"] is False and goal["measure"] == "declared"


def test_an_anchor_goal_reads_the_resolver_and_says_when_nothing_measures_it(db_session, owner, anchor_job):
    goal = gs.create_goal(db_session, user_id=owner, name="Financial Freedom", source="anchor", measure="anchor",
                          target_value=1_000_000, unit="USD")
    assert goal["progress"] == 0.25 and goal["measured"] is True

    anchor_job["value"] = {"supported": False, "attainment_pct": None, "reason": "no_value"}
    refreshed = gs.refresh_goal_states(db_session, owner)
    assert refreshed[0]["progress"] is None and refreshed[0]["measured"] is False  # unmeasured, never 0


def test_an_objectives_goal_averages_its_linked_objectives(db_session, owner, monkeypatch):
    from apps.masterplan.services import phase_advance
    from apps.masterplan.strategy_layer import PlanObjective

    a, b, c = (PlanObjective(masterplan_id=9101, user_id=uuid.UUID(owner), name=n, ordinal=i)
               for i, n in enumerate(("Ethical AI Framework", "Platform Enablement", "Partnerships")))
    db_session.add_all([a, b, c])
    db_session.commit()
    monkeypatch.setattr(phase_advance, "objective_attainment", lambda db, masterplan_id, user_id: {"objectives": [
        {"id": a.id, "attainment_pct": 0.4}, {"id": b.id, "attainment_pct": 0.8}, {"id": c.id, "attainment_pct": 0.1},
    ]})
    goal = gs.create_goal(db_session, user_id=owner, name="Widely adopted ethical AI framework",
                          source="success_criterion", measure="objectives", objective_ids=[a.id, b.id])
    assert goal["progress"] == 0.6  # the two linked, not the third

    monkeypatch.setattr(phase_advance, "objective_attainment", lambda db, masterplan_id, user_id: {"objectives": [
        {"id": a.id, "attainment_pct": None}, {"id": b.id, "attainment_pct": None}]})
    assert gs.refresh_goal_states(db_session, owner)[0]["progress"] is None  # no work planned: unmeasured


def test_a_measured_goal_completes_and_a_declared_one_never_does_by_itself(db_session, owner, anchor_job, monkeypatch):
    events = []
    monkeypatch.setattr(gs, "emit_event", lambda event_type, payload: events.append(payload))
    gs.create_goal(db_session, user_id=owner, name="Declared one", measure="declared")
    anchor_job["value"] = {"supported": True, "attainment_pct": 0.5, "reason": None}
    gs.create_goal(db_session, user_id=owner, name="Anchor", source="anchor", measure="anchor",
                   target_value=100, unit="USD")
    anchor_job["value"] = {"supported": True, "attainment_pct": 1.0, "reason": None}
    remaining = gs.refresh_goal_states(db_session, owner)
    assert [g["name"] for g in remaining] == ["Declared one"]  # the anchor completed and left the active list
    assert events and events[0]["status"] == "completed"


def test_an_execution_no_longer_nudges_progress_by_keywords(db_session, owner):
    gs.create_goal(db_session, user_id=owner, name="Deploy enabling platforms", measure="declared", priority=0.9)
    after = gs.update_goals_from_execution(
        db_session, user_id=owner, workflow_type="deploy",
        execution_result={"task_result": "Deploy enabling platforms: done"}, success=True)
    assert after[0]["progress"] is None and after[0]["recent_actions"] == []


def test_ranking_reads_an_unmeasured_gap_as_neither_done_nor_untouched(db_session, owner):
    gs.create_goal(db_session, user_id=owner, name="Declared", measure="declared", priority=0.5)
    ranked = gs.rank_goals(db_session, owner)
    assert ranked[0]["progress_gap"] == gs.UNMEASURED_GAP


def test_bad_measure_or_source_is_refused(db_session, owner):
    with pytest.raises(ValueError):
        gs.create_goal(db_session, user_id=owner, name="x", measure="keywords")
    with pytest.raises(ValueError):
        gs.create_goal(db_session, user_id=owner, name="x", source="guessed")


@pytest.mark.parametrize("measured, expected", [(False, "continue_highest_priority_task"), (True, "review_plan")])
def test_only_a_measured_goal_overrides_the_loops_next_action(measured, expected, monkeypatch):
    import apps.analytics.services.reasoning.decision_engine as engine

    monkeypatch.setattr(engine, "get_job", lambda name: (lambda goals, text: 0.0))  # no alignment at all
    top = {"id": "g1", "name": "Financial Freedom", "ranked_priority": 0.9, "measured": measured}
    decision, payload = engine._apply_goal_weighting(
        "continue_highest_priority_task", {"next_action": {"title": "Write the next piece"}}, goals=[top])
    assert decision == expected
