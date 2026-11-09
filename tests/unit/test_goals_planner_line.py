"""GOALS_LAYER_SPEC decision 5: the planner gets one line per active goal, beside the plan block."""
from __future__ import annotations

import uuid

import pytest

from apps.agent.agents.runtime_extensions import _goal_line
from apps.masterplan.services import goal_service
from apps.masterplan.services.planning_context import build_planning_context

pytestmark = pytest.mark.app_profile


def test_each_kind_of_goal_reads_as_one_honest_line():
    assert _goal_line({"name": "Financial Freedom", "measure": "anchor", "progress": None, "target_value": 1_000_000,
                       "unit": "USD", "target_date": "2030-12-31"}) == \
        "- Financial Freedom (target 1,000,000 USD by 2030-12-31; no measurement yet)"
    assert _goal_line({"name": "Partnerships", "measure": "objectives", "progress": 0.4,
                       "objectives": ["Partnership Development"]}) == \
        "- Partnerships (through objectives Partnership Development; 40% attained)"
    assert _goal_line({"name": "Funding", "measure": "declared", "progress": None}) == \
        "- Funding (declared: no number; the user marks it done)"


def test_active_goals_reach_the_planning_context_even_without_a_plan(db_session):
    owner = uuid.uuid4()
    assert build_planning_context(user_id=owner, db=db_session) is None
    goal_service.create_goal(db_session, user_id=str(owner), name="Read more", measure="declared", priority=0.6)
    goal_service.create_goal(db_session, user_id=str(owner), name="Dropped one", measure="declared", status="dropped")
    context = build_planning_context(user_id=owner, db=db_session)
    assert context["masterplan_id"] is None and [g["name"] for g in context["goals"]] == ["Read more"]


def test_the_planner_block_lists_goals(monkeypatch, db_session):
    import AINDY.platform_layer.registry as registry
    from apps.agent.agents import runtime_extensions

    plan = {"masterplan_id": None, "current_phase": None, "strategies": [],
            "goals": [{"name": "Read more", "measure": "declared", "progress": None}]}
    monkeypatch.setattr(registry, "get_job", lambda name: (lambda **kw: plan) if name == "masterplan.planning_context" else None)
    block = runtime_extensions._build_plan_context_block("u", db_session)
    assert "What the user is working toward" in block and "- Read more (declared" in block
    assert "masterplan_id" not in block  # no plan block without a plan
