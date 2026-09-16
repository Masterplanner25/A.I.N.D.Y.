"""App-owned Agentics decision levers (AGENTICS.md hardening).

AGENTICS is overwhelmingly runtime-owned (it is the doc that defined the
`aindy-runtime` split). The app's genuine contribution is the *decision* logic it
registers into the runtime via `register_*` hooks — and it was untested. This
covers the three app-owned levers:

- Phase C: the autonomy trigger evaluator (`apps/agent/agents/triggers.py`) — the
  execute/defer/ignore policy used for every trigger type via the "default" hook.
- Phase D: the agent ranking strategy (`apps/masterplan/agents/ranking.py`).
- Phase A/C: the agent completion hook (`apps/agent/agents/runtime_extensions.py`)
  that enforces the Infinity loop after a run.

All pure/injectable — no runtime edits, no live execution stack.
"""

from __future__ import annotations

import pytest

from apps.agent.agents.runtime_extensions import handle_agent_run_completed
from apps.agent.agents.triggers import evaluate_autonomy_trigger
from apps.masterplan.agents.ranking import rank_agents

pytestmark = pytest.mark.app_profile


# --------------------------------------------------------------------------- #
# Phase C — autonomy trigger evaluator (execute / defer / ignore policy)
# --------------------------------------------------------------------------- #
# No "db" in context -> _enrich_context is a no-op, so the decision is computed
# purely from the provided trigger + context.
def test_trigger_executes_high_value_user_trigger():
    out = evaluate_autonomy_trigger({"trigger_type": "user", "trigger": {"importance": 0.95}, "context": {}})
    assert out["decision"] == "execute"
    assert out["priority"] == pytest.approx(0.7625)
    assert out["defer_seconds"] == 0


def test_trigger_defers_when_system_health_critical():
    out = evaluate_autonomy_trigger(
        {"trigger_type": "watcher", "trigger": {}, "context": {"system_state": {"health_status": "critical"}}}
    )
    assert out["decision"] == "defer"
    assert out["defer_seconds"] == 300
    assert "critical" in out["reason"]


def test_trigger_defers_under_high_load():
    out = evaluate_autonomy_trigger(
        {"trigger_type": "watcher", "trigger": {}, "context": {"system_state": {"system_load": 0.9}}}
    )
    assert out["decision"] == "defer"
    assert "load" in out["reason"]


def test_trigger_defers_on_repeated_failure_pattern():
    out = evaluate_autonomy_trigger(
        {"trigger_type": "schedule", "trigger": {}, "context": {"ripple_patterns": [{"failure_events": 3}]}}
    )
    assert out["decision"] == "defer"
    assert "repeated failures" in out["reason"]


def test_trigger_ignores_low_value_watcher():
    out = evaluate_autonomy_trigger(
        {
            "trigger_type": "watcher",
            "trigger": {},
            "context": {
                "memory_signals": [
                    {"type": "failure", "impact_score": 1.0},
                    {"type": "failure", "impact_score": 1.0},
                    {"type": "failure"},
                ]
            },
        }
    )
    assert out["decision"] == "ignore"
    assert out["priority"] < 0.35


def test_autonomy_trigger_evaluator_registered():
    from AINDY.platform_layer.registry import get_trigger_evaluator

    # All trigger types fall back to "default" -> the app-owned evaluator. The
    # runtime may wrap trigger evaluators (subprocess-capable surface), so assert
    # registration by presence rather than object identity.
    evaluator = get_trigger_evaluator("default")
    assert evaluator is not None and callable(evaluator)


# --------------------------------------------------------------------------- #
# Phase D — agent ranking strategy
# --------------------------------------------------------------------------- #
def test_rank_agents_sorts_by_coordination_score():
    candidates = [
        {"agent_id": "a", "coordination_score": 0.3},
        {"agent_id": "b", "coordination_score": 0.7},
    ]
    ranked = rank_agents(candidates, {})  # no db -> no goal bonus, just sort
    assert [c["agent_id"] for c in ranked] == ["b", "a"]
    # input is not mutated
    assert candidates[0]["agent_id"] == "a"


def test_rank_agents_applies_goal_alignment_bonus(monkeypatch):
    import AINDY.platform_layer.registry as registry
    import AINDY.platform_layer.system_state_service as system_state_service

    monkeypatch.setattr(
        registry,
        "get_job",
        lambda name: (lambda db, user_id, system_state=None: [{"name": "ship widget", "ranked_priority": 0.8}])
        if name == "goals.rank"
        else None,
    )
    monkeypatch.setattr(system_state_service, "compute_current_state", lambda db: {})

    ranked = rank_agents(
        [{"agent_id": "a", "coordination_score": 0.5}],
        {"db": object(), "user_id": "u1", "task": {"name": "ship widget"}},
    )
    # bonus = ranked_priority(0.8) * 0.15 = 0.12
    assert ranked[0]["coordination_score"] == pytest.approx(0.62)


def test_agent_ranking_strategy_registered():
    from AINDY.platform_layer.registry import get_agent_ranking_strategy

    assert get_agent_ranking_strategy() is rank_agents


# --------------------------------------------------------------------------- #
# Phase A/C — agent completion hook (enforces the Infinity loop post-run)
# --------------------------------------------------------------------------- #
class _FakeRun:
    def __init__(self, result=None, run_id="run-1", user_id="u1"):
        self.result = {} if result is None else result
        self.id = run_id
        self.user_id = user_id


class _FakeQuery:
    def __init__(self, run):
        self._run = run

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._run


class _FakeSession:
    """Stands in for the SessionLocal() the hook opens to re-fetch the run by id."""

    def __init__(self, run):
        self._run = run
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def query(self, model):
        return _FakeQuery(self._run)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def _patch_session(monkeypatch, run):
    """Make the hook's `SessionLocal()` return a fake session that yields `run`."""
    import AINDY.db.database as database

    session = _FakeSession(run)
    monkeypatch.setattr(database, "SessionLocal", lambda: session)
    return session


def test_completion_hook_enforces_infinity_loop(monkeypatch):
    import AINDY.platform_layer.registry as registry

    monkeypatch.setattr(
        registry,
        "get_job",
        lambda name: (
            lambda **kw: {
                "next_action": {
                    "type": "continue_highest_priority_task",
                    "title": "Continue task: Ship onboarding",
                    "task_id": "t1",
                }
            }
        )
        if name == "analytics.infinity_execute"
        else None,
    )
    run = _FakeRun()
    session = _patch_session(monkeypatch, run)
    out = handle_agent_run_completed({"run_id": "run-1", "user_id": "u1"})

    # The hook re-fetched the run by id and stamped its rich decision dict (consumer contract).
    assert run.result["loop_enforced"] is True
    assert run.result["next_action"]["type"] == "continue_highest_priority_task"
    assert session.committed is True
    assert session.closed is True

    # The hook RETURNS a runtime-coercible NextAction (Gap 4 ledger), not run.result.
    assert out["action"] == "trigger_execution"
    assert out["source"] == "infinity_orchestrator"
    assert out["reason"] == "infinity:continue_highest_priority_task"
    assert out["args"]["title"] == "Continue task: Ship onboarding"


def test_completion_hook_takes_the_tenant_from_the_run_not_the_redacted_context(monkeypatch):
    """AGENT-COMPLETION-HOOK-USERID-1 — the runtime passes `user_id` as a `uuid.UUID`, and the
    extension boundary redacts every non-primitive to `{"_redacted_type": "UUID"}`. Every
    completed agent run to 2026-09-16 (8/8) failed here with "user_id is required" and none
    carries `loop_enforced`. The hook must take the tenant from the run it re-fetches."""
    import AINDY.platform_layer.registry as registry

    seen: dict = {}

    def _job(name):
        if name != "analytics.infinity_execute":
            return None

        def _execute(**kw):
            seen.update(kw)
            return {"next_action": {"type": "review_plan", "title": "Review"}}

        return _execute

    monkeypatch.setattr(registry, "get_job", _job)
    run = _FakeRun(user_id="283ae082-19f1-47f8-af2e-1c2c5efada40")
    _patch_session(monkeypatch, run)

    # Exactly what the boundary hands us in production (see extension_boundary._sanitize).
    out = handle_agent_run_completed({"run_id": "run-1", "user_id": {"_redacted_type": "UUID"}})

    assert seen["user_id"] == "283ae082-19f1-47f8-af2e-1c2c5efada40"
    assert run.result["loop_enforced"] is True
    assert out is not None and out["action"] == "ask_user"


def test_completion_hook_return_is_runtime_coercible(monkeypatch):
    # The runtime coerces the hook's return via coerce_next_action; a round-trip
    # must yield the same canonical verb (proves the ledger records the app verb).
    import AINDY.platform_layer.registry as registry
    from AINDY.core.next_action import VALID_ACTIONS, coerce_next_action

    _patch_session(monkeypatch, _FakeRun())
    monkeypatch.setattr(
        registry,
        "get_job",
        lambda name: (lambda **kw: {"next_action": {"type": "review_plan", "title": "Review the plan"}})
        if name == "analytics.infinity_execute"
        else None,
    )
    out = handle_agent_run_completed({"run_id": "run-1", "user_id": "u1"})
    assert out["action"] == "ask_user"  # review_plan is manual/human-gated
    assert out["action"] in VALID_ACTIONS
    assert coerce_next_action(out)["action"] == "ask_user"


@pytest.mark.parametrize(
    "decision_type, expected_verb",
    [
        ("continue_highest_priority_task", "trigger_execution"),
        ("reprioritize_tasks", "trigger_execution"),
        ("create_new_task", "trigger_execution"),
        ("review_plan", "ask_user"),
    ],
)
def test_next_action_mapping_covers_every_loop_verb(decision_type, expected_verb):
    from AINDY.core.next_action import VALID_ACTIONS
    from apps.agent.agents.runtime_extensions import (
        _INFINITY_DECISION_TO_NEXT_ACTION,
        _next_action_for_runtime,
    )

    # Every verb the loop can emit is mapped, and every target is a canonical verb.
    assert set(_INFINITY_DECISION_TO_NEXT_ACTION.values()) <= VALID_ACTIONS
    out = _next_action_for_runtime({"next_action": {"type": decision_type}})
    assert out["action"] == expected_verb


def test_next_action_unmapped_or_missing_falls_back_to_runtime_default():
    from apps.agent.agents.runtime_extensions import _next_action_for_runtime

    # Unknown verb, non-dict, and missing decision all -> None (runtime keeps default).
    assert _next_action_for_runtime({"next_action": {"type": "totally_unknown"}}) is None
    assert _next_action_for_runtime({"next_action": "not-a-dict"}) is None
    assert _next_action_for_runtime({}) is None
    assert _next_action_for_runtime(None) is None


def test_completion_hook_noop_when_already_enforced(monkeypatch):
    import AINDY.platform_layer.registry as registry

    session = _patch_session(monkeypatch, _FakeRun(result={"loop_enforced": True}))
    called = []
    monkeypatch.setattr(registry, "get_job", lambda name: called.append(name) or None)
    out = handle_agent_run_completed({"run_id": "run-1", "user_id": "u1"})
    assert out is None
    assert called == []  # short-circuits before touching the job registry
    assert session.closed is True  # session still closed on the no-op path


def test_completion_hook_noop_when_run_not_found(monkeypatch):
    # run_id given but the run is gone (re-fetch returns None) -> no-op, session closed.
    session = _patch_session(monkeypatch, None)
    out = handle_agent_run_completed({"run_id": "gone", "user_id": "u1"})
    assert out is None
    assert session.closed is True


def test_completion_hook_graceful_without_orchestrator(monkeypatch):
    import AINDY.platform_layer.registry as registry

    session = _patch_session(monkeypatch, _FakeRun())
    monkeypatch.setattr(registry, "get_job", lambda name: None)
    out = handle_agent_run_completed({"run_id": "run-1", "user_id": "u1"})
    assert out is None  # missing job -> swallowed
    assert session.rolled_back is True
    assert session.closed is True


def test_completion_hook_requires_run_id_and_user():
    # Missing run_id or user_id -> no-op before a session is ever opened.
    assert handle_agent_run_completed({"run_id": None, "user_id": None}) is None
    assert handle_agent_run_completed({"user_id": "u1"}) is None
    assert handle_agent_run_completed({"run_id": "r1"}) is None
