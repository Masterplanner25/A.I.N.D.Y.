"""`sys.v1.automation.create_loop_adjustment` / `update_loop_adjustment` write the caller's rows only.

Create used to pass `**payload` to the model, so the payload's `user_id` chose the new row's
owner. Update fetched by `adjustment_id` alone and applied every key, so any caller could edit
another user's adjustment, or set its `user_id`. The follow-up to #506 and #507.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from AINDY.kernel.syscall_registry import SyscallContext
from apps.automation.infinity_loop import LoopAdjustment
from apps.automation.public import create_loop_adjustment
from apps.automation.syscalls import syscall_handlers as handlers

pytestmark = pytest.mark.app_profile


def _ctx(db, user_id) -> SyscallContext:
    return SyscallContext(
        execution_unit_id=str(uuid.uuid4()),
        user_id=str(user_id) if user_id else "",
        capabilities=["automation.write"],
        trace_id=str(uuid.uuid4()),
        metadata={"_db": db},
    )


def _fields() -> dict:
    return {
        "trigger_event": "manual",
        "decision_type": "review_plan",
        "applied_at": datetime.now(timezone.utc),
    }


def _id(record: dict) -> uuid.UUID:
    # `_row_to_dict` returns the id as a string; the UUID column on sqlite compares only a UUID.
    return uuid.UUID(str(record["id"]))


def _row(db, adjustment_id) -> LoopAdjustment:
    return db.query(LoopAdjustment).filter(LoopAdjustment.id == adjustment_id).one()


def test_create_owner_is_the_caller_not_the_payload(db_session):
    me, other = uuid.uuid4(), uuid.uuid4()
    out = handlers._handle_automation_create_loop_adjustment(
        {**_fields(), "user_id": str(other)}, _ctx(db_session, me)
    )
    assert _row(db_session, _id(out["adjustment"])).user_id == me


def test_create_without_a_caller_raises(db_session):
    with pytest.raises(ValueError):
        handlers._handle_automation_create_loop_adjustment(
            {**_fields(), "user_id": str(uuid.uuid4())}, _ctx(db_session, None)
        )


def test_update_cannot_touch_another_users_row(db_session):
    me, other = uuid.uuid4(), uuid.uuid4()
    theirs = create_loop_adjustment(db_session, user_id=other, **_fields())
    out = handlers._handle_automation_update_loop_adjustment(
        {"adjustment_id": _id(theirs), "decision_type": "create_new_task"}, _ctx(db_session, me)
    )
    assert out == {"adjustment": {}}
    assert _row(db_session, _id(theirs)).decision_type == "review_plan"


def test_update_cannot_reassign_the_owner(db_session):
    me, other = uuid.uuid4(), uuid.uuid4()
    mine = create_loop_adjustment(db_session, user_id=me, **_fields())
    handlers._handle_automation_update_loop_adjustment(
        {"adjustment_id": _id(mine), "user_id": str(other), "decision_type": "create_new_task"},
        _ctx(db_session, me),
    )
    row = _row(db_session, _id(mine))
    assert row.user_id == me
    assert row.decision_type == "create_new_task"
