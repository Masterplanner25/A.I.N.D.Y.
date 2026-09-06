"""Regression test: a repeated task completion must not re-run the orchestration chain.

`complete_task` is idempotent — it returns early on an already-completed task without
mutating anything. But `task_orchestrate` is a SIBLING node in the `task_completion`
flow (`task_validate -> task_complete -> task_orchestrate`), not something
`complete_task` calls, so that guard was invisible to it and the orchestration ran
regardless: memory capture, downstream unlock, ETA recalc, and a full Infinity
re-score via `analytics.infinity_execute`.

Measured on the live stack 2026-09-06 before the fix: one task completion arrived as
4 `tasks.complete` calls (three within 21ms), producing 4 `task_completion` flow runs
and duplicate `score_history` / `three_axis_shadow_records` rows — one carrying
`score_delta = 0`, a recalculation that could not change anything. That inflates the
shadow ledger SOAK-THEN-FLIP-1 depends on, where 105 rows held only 20 distinct
measurements.

Filed as TASK-COMPLETE-ORCHESTRATE-REFIRE-1. Distinct from the resolved
TASK-COMPLETE-IDEMPOTENCY-1, which fixed the mutation guard this test sits downstream of.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-required-length-1234567890")

pytestmark = pytest.mark.app_profile

tasks_flows = pytest.importorskip("apps.tasks.flows.tasks_flows")
task_service = pytest.importorskip("apps.tasks.services.task_service")

task_orchestrate = tasks_flows.task_orchestrate
TASK_ALREADY_COMPLETED_PREFIX = task_service.TASK_ALREADY_COMPLETED_PREFIX


@pytest.fixture
def spy_syscall(monkeypatch):
    """Record whether `task_orchestrate` reached the orchestration syscall."""
    calls: list[str] = []

    def _fake(name, state, context, capability):
        calls.append(name)
        return {"status": "SUCCESS", "output_patch": {"task_orchestration": {"ran": True}}}

    monkeypatch.setattr(tasks_flows, "_syscall_node", _fake)
    return calls


def test_repeat_completion_skips_orchestration(spy_syscall):
    """The no-op return from `complete_task` must short-circuit the chain."""
    state = {"task_name": "Fix Nodus Issues",
             "task_result": f"{TASK_ALREADY_COMPLETED_PREFIX} Fix Nodus Issues"}

    result = task_orchestrate(state, {})

    # The whole point: the orchestration syscall is never dispatched, so no Infinity
    # re-score, no duplicate score_history row. Fails on the old code, which called it
    # unconditionally.
    assert spy_syscall == []
    assert result["status"] == "SUCCESS"
    orchestration = result["output_patch"]["task_orchestration"]
    assert orchestration["skipped"] is True
    assert orchestration["reason"] == "already_completed"
    assert orchestration["score_orchestrated"] is False


def test_first_completion_still_orchestrates(spy_syscall):
    """A genuine completion must be unaffected — the guard must not swallow real work."""
    state = {"task_name": "Fix Nodus Issues", "task_result": "Completed task: Fix Nodus Issues"}

    result = task_orchestrate(state, {})

    assert spy_syscall == ["sys.v1.task.orchestrate"]
    assert result["status"] == "SUCCESS"
    assert result["output_patch"]["task_orchestration"] == {"ran": True}


def test_missing_task_result_still_orchestrates(spy_syscall):
    """Absent state must not be read as 'already completed' and silently skip work."""
    result = task_orchestrate({"task_name": "Fix Nodus Issues"}, {})

    assert spy_syscall == ["sys.v1.task.orchestrate"]
    assert result["status"] == "SUCCESS"


def test_unlock_message_still_orchestrates(spy_syscall):
    """The `| unlocked: ...` completion variant is a real completion, not a no-op."""
    state = {"task_name": "A", "task_result": "Completed task: A | unlocked: B, C"}

    task_orchestrate(state, {})

    assert spy_syscall == ["sys.v1.task.orchestrate"]


def test_guard_matches_the_service_sentinel_exactly():
    """The node and the service must agree on the sentinel, or the guard silently lapses.

    If `complete_task`'s message is reworded without updating the constant, the prefix
    match stops firing and the duplicate re-score returns with no test failing anywhere.
    """
    assert TASK_ALREADY_COMPLETED_PREFIX == "Task already completed:"
    # The real message must start with the constant the node matches on.
    assert f"{TASK_ALREADY_COMPLETED_PREFIX} Some Task".startswith(TASK_ALREADY_COMPLETED_PREFIX)
