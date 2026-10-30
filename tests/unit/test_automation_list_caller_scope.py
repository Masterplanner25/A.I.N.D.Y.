"""The `sys.v1.automation.list_*` reads act for the caller, never for a payload `user_id`.

They read `payload.get("user_id") or context.user_id`, so a payload could name another user and
read their feedback, loop adjustments or logs. Found with `watcher.query` (#506).
"""
from __future__ import annotations

import uuid

import pytest

import apps.automation.public as automation_public
from AINDY.kernel.syscall_registry import SyscallContext
from apps.automation.syscalls import syscall_handlers as handlers

pytestmark = pytest.mark.app_profile

ME = str(uuid.uuid4())
OTHER = str(uuid.uuid4())


@pytest.fixture
def seen(monkeypatch):
    """Record the user id each public reader is asked for."""
    calls: dict[str, str] = {}

    def feedback(user_id, db, limit=20):
        calls["feedback"] = user_id
        return []

    def adjustments(user_id, db, **_):
        calls["adjustments"] = user_id
        return []

    def logs(db, *, user_id, limit=250):
        calls["logs"] = user_id
        return []

    monkeypatch.setattr(automation_public, "get_user_feedback", feedback)
    monkeypatch.setattr(automation_public, "get_loop_adjustments", adjustments)
    monkeypatch.setattr(automation_public, "list_automation_logs", logs)
    return calls


def _ctx(user_id) -> SyscallContext:
    return SyscallContext(
        execution_unit_id=str(uuid.uuid4()),
        user_id=user_id or "",
        capabilities=["automation.read"],
        trace_id=str(uuid.uuid4()),
        metadata={"_db": object()},
    )


HANDLERS = [
    ("feedback", handlers._handle_automation_list_feedback),
    ("adjustments", handlers._handle_automation_list_loop_adjustments),
    ("logs", handlers._handle_automation_list_logs),
]


@pytest.mark.parametrize("key,handler", HANDLERS)
def test_payload_user_id_cannot_choose_another_user(seen, key, handler):
    handler({"user_id": OTHER}, _ctx(ME))
    assert seen[key] == ME


@pytest.mark.parametrize("key,handler", HANDLERS)
def test_without_a_payload_user_it_reads_the_caller(seen, key, handler):
    handler({}, _ctx(ME))
    assert seen[key] == ME


@pytest.mark.parametrize("key,handler", HANDLERS)
def test_without_a_caller_it_raises_instead_of_reading_user_none(seen, key, handler):
    with pytest.raises(ValueError):
        handler({"user_id": OTHER}, _ctx(None))
    assert key not in seen
