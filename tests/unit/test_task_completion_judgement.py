"""Complexity and difficulty are collected at completion, validated, and optional.

WCU is `effort_hours x task_complexity x task_difficulty` and is the only universal measure
of work done in this repo. Two of its three terms were inert: every task carried
`task_complexity = 1` and `task_difficulty = 1` — the column defaults — because nothing ever
set them. So WCU silently reduced to estimated hours, which `Task.duration` already reports
(MASTERPLAN_GOAL_ATTAINMENT_SPEC §4b).

Collected at COMPLETION rather than creation, on the owner's call: difficulty guessed up
front is a guess, difficulty recorded afterwards is an observation — and WCU only accrues
from completed tasks, so nothing is lost by waiting.

Two properties matter and pull in opposite directions, which is why both are pinned here:

* **Optional.** An agent or script that cannot judge must leave the columns alone rather than
  invent a middle value. A defaulted 3 is fabricated data indistinguishable from a real
  judgement — the failure the worth-declaration spec is built around.
* **Validated.** A supplied value outside 1-5 is an error, not something to clamp. Clamping
  would silently record a different judgement than the one made.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-required-length-1234567890")

pytestmark = pytest.mark.app_profile

task_service = pytest.importorskip("apps.tasks.services.task_service")
_validated_judgement = task_service._validated_judgement


# ── validation ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [(1, 1), (3, 3), (5, 5), ("4", 4)])
def test_valid_judgements_are_accepted(value, expected):
    """1-5, matching the scale analytics_inputs.py already documents for these concepts."""
    assert _validated_judgement(value, "task_complexity") == expected


def test_absent_judgement_stays_none():
    """None means 'not judged' and must survive as None — not become a default."""
    assert _validated_judgement(None, "task_complexity") is None


@pytest.mark.parametrize("value", [0, 6, -1, 100])
def test_out_of_range_is_rejected_not_clamped(value):
    """Clamping would record a judgement the user did not make."""
    with pytest.raises(ValueError, match="between 1 and 5"):
        _validated_judgement(value, "task_difficulty")


@pytest.mark.parametrize("value", ["high", "", [], {}])
def test_non_numeric_is_rejected(value):
    with pytest.raises(ValueError, match="must be an integer"):
        _validated_judgement(value, "task_complexity")


def test_the_scale_matches_the_documented_analytics_scale():
    """Two scales for one concept is how the seconds/hours confusion happened."""
    assert (task_service.WCU_JUDGEMENT_MIN, task_service.WCU_JUDGEMENT_MAX) == (1, 5)


# ── the contract at the edges ──────────────────────────────────────────────────────────

def test_complete_task_accepts_the_judgements_as_keyword_only():
    """Positional would silently swallow a mis-ordered call from an existing caller."""
    import inspect

    sig = inspect.signature(task_service.complete_task)
    for field in ("task_complexity", "task_difficulty"):
        assert sig.parameters[field].kind is inspect.Parameter.KEYWORD_ONLY
        assert sig.parameters[field].default is None


def test_the_action_schema_leaves_them_optional():
    """`/start` and `/pause` share TaskAction; requiring these would break both."""
    from apps.tasks.schemas.task_schemas import TaskAction

    action = TaskAction(name="Fix Nodus Issues")
    assert action.task_complexity is None
    assert action.task_difficulty is None

    judged = TaskAction(name="x", task_complexity=4, task_difficulty=2)
    assert (judged.task_complexity, judged.task_difficulty) == (4, 2)


def test_the_completion_syscall_forwards_them():
    """The chain is route -> flow -> syscall -> service; a gap anywhere drops the judgement."""
    import inspect

    from apps.tasks.syscalls import syscall_handlers

    source = inspect.getsource(syscall_handlers._handle_task_complete)
    assert 'payload.get("task_complexity")' in source
    assert 'payload.get("task_difficulty")' in source


def test_the_route_puts_them_into_the_flow_state():
    """The flow node reads state; values left out of the payload never reach the service."""
    import inspect

    from apps.tasks.routes import task_router

    source = inspect.getsource(task_router)
    assert '"task_complexity": task.task_complexity' in source
    assert '"task_difficulty": task.task_difficulty' in source
