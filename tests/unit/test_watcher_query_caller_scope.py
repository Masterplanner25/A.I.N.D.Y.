"""`sys.v1.watcher.query` and the `watcher_signals_list` nodes read the caller's signals only.

Found 2026-10-29 while listing, for the runtime, the dispatch sites a payload-identity refusal
(DEC-103) could break. The handler filtered by user only when the payload named one, so a call
without `user_id` returned every user's watcher signals, and a payload `user_id` chose whose.
Both `watcher_signals_list_node` copies did the same with `state["user_id_filter"]`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from AINDY.kernel.syscall_registry import SyscallContext
from apps.automation.flows.watcher_flows import watcher_signals_list_node
from apps.automation.models import WatcherSignal
from apps.automation.syscalls.syscall_handlers import handle_watcher_query

pytestmark = pytest.mark.app_profile


def _signal(db, user_id: uuid.UUID, session_id: str) -> None:
    db.add(
        WatcherSignal(
            user_id=user_id,
            signal_type="focus_achieved",
            session_id=session_id,
            app_name="editor",
            activity_type="work",
            signal_timestamp=datetime.now(timezone.utc),
        )
    )
    db.flush()


def _ctx(db, user_id) -> SyscallContext:
    return SyscallContext(
        execution_unit_id=str(uuid.uuid4()),
        user_id=str(user_id) if user_id else "",
        capabilities=["watcher.query"],
        trace_id=str(uuid.uuid4()),
        metadata={"_db": db},
    )


@pytest.fixture
def two_users(db_session):
    me, other = uuid.uuid4(), uuid.uuid4()
    _signal(db_session, me, "s-me")
    _signal(db_session, other, "s-other")
    return me, other


def _sessions(signals) -> set[str]:
    return {s["session_id"] for s in signals}


def test_query_without_user_returns_only_the_callers_signals(db_session, two_users):
    me, _ = two_users
    out = handle_watcher_query({}, _ctx(db_session, me))
    assert _sessions(out["signals"]) == {"s-me"}
    assert out["total"] == 1


def test_payload_user_id_cannot_choose_another_user(db_session, two_users):
    me, other = two_users
    out = handle_watcher_query({"user_id": str(other)}, _ctx(db_session, me))
    assert _sessions(out["signals"]) == {"s-me"}


def test_query_without_a_caller_is_an_error_not_the_whole_table(db_session, two_users):
    with pytest.raises(ValueError):
        handle_watcher_query({}, _ctx(db_session, None))


def test_list_node_ignores_user_id_filter(db_session, two_users):
    me, other = two_users
    result = watcher_signals_list_node(
        {"user_id_filter": str(other)}, {"db": db_session, "user_id": str(me)}
    )
    assert result["status"] == "SUCCESS"
    assert _sessions(result["output_patch"]["watcher_signals_list_result"]) == {"s-me"}


def test_list_node_without_a_caller_fails(db_session, two_users):
    result = watcher_signals_list_node({}, {"db": db_session})
    assert result["status"] == "FAILURE"
