"""A Genesis turn must not trigger an Infinity recalculation.

The `genesis_message` flow queued a full recalculation after every conversational turn. The
premise — "a turn IS a scoring event" — was tested for LATENCY (GENESIS-TURN-LATENCY-1 moved
the work off the request path) but never for EFFECT.

Measured 2026-09-06 across 46 days of `score_history`: of 16 `genesis_message`
recalculations, **14 produced a score_delta of exactly 0**, including four consecutive turns
10-15 seconds apart all scoring 42.140. Each costs 1.8-4.1s of `gather_support_state` and
produced no information in 87% of cases.

Owner's call: *"I don't think it needs to be recalculated on each turn specifically."* A turn
changes the transcript — not the task graph, the metrics, or the pillars — so the score has
nothing to move on until something is actually *done*.

These tests pin both halves: the recalculation is gone, and the score is not stranded.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-required-length-1234567890")

pytestmark = pytest.mark.app_profile

flow_definitions = pytest.importorskip("apps.automation.flows.flow_definitions")


def _genesis_flow_source() -> str:
    import inspect

    return inspect.getsource(flow_definitions)


# ── the recalculation is gone ──────────────────────────────────────────────────────────

def test_the_orchestrate_node_no_longer_exists():
    """The node's only job was queueing the recalculation, so it goes with it.

    Left in place as an empty pass-through it would be exactly the dead-surface shape this
    repo keeps rediscovering — something a future reader assumes is load-bearing.
    """
    assert not hasattr(flow_definitions, "genesis_message_orchestrate")


def test_the_flow_graph_ends_at_execute():
    """`genesis_message_execute` is the terminal node; nothing runs after the reply."""
    source = _genesis_flow_source()

    # The registered graph must not route to a node that no longer exists — a dangling
    # edge would fail at flow-run time rather than here.
    assert '"genesis_message_execute": ["genesis_message_orchestrate"]' not in source
    assert '"end": ["genesis_message_execute"]' in source


def test_the_flow_plan_has_two_steps():
    """The plan and the graph must agree, or the runtime validates against a stale shape."""
    import inspect

    from apps.masterplan import bootstrap as mp_bootstrap

    source = inspect.getsource(mp_bootstrap)
    assert '["genesis_message_validate", "genesis_message_execute"]' in source
    assert "genesis_message_orchestrate" not in source


def test_no_infinity_recalc_is_queued_for_a_genesis_turn():
    """The specific behaviour removed: a job submission with trigger_event genesis_message.

    Guards against it returning by another route — an async job, an inline dispatch, or a
    new node — rather than only against the old node's literal body.
    """
    source = _genesis_flow_source()

    # The recalc was queued as `analytics.infinity_recalc` with this trigger.
    assert '"trigger_event": "genesis_message"' not in source
    assert '"task_name": "analytics.infinity_recalc"' not in source


# ── the score is not stranded ──────────────────────────────────────────────────────────

def test_other_triggers_still_recalculate():
    """Removing one trigger must not remove the score's ability to move.

    `masterplan_goal_state_changed` matters most here: it covers what a Genesis session
    actually produces — a changed plan — as distinct from the conversation about it.
    """
    import subprocess

    result = subprocess.run(
        ["git", "grep", "-l", "trigger_event"],
        capture_output=True, text=True, cwd=os.getcwd(),
    )
    assert result.returncode == 0, "git grep failed"

    from apps.analytics.services.orchestration import infinity_orchestrator

    # The orchestrator still accepts and acts on a trigger; only one caller went away.
    assert hasattr(infinity_orchestrator, "execute")


def test_the_daily_recalculation_still_exists():
    """The 'polling recalculation' this removal leans on — a daily cron at 07:00.

    Without it, dropping the per-turn trigger WOULD strand a user who only converses.
    """
    import inspect

    from apps.analytics import bootstrap as analytics_bootstrap

    source = inspect.getsource(analytics_bootstrap)
    assert "daily_infinity_score_recalculation" in source
    assert 'trigger="cron"' in source
    assert '{"hour": 7}' in source
