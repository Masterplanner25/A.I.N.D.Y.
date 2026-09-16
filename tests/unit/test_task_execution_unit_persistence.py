"""TASK-EU-NOT-PERSISTED-1 — a task's own execution unit must survive the handler that created it.

`sys.v1.task.create` (and start / pause / complete) run through `_session_from_context`, which
opens a session the handler OWNS whenever the caller passed none — the flow-node path, because
`make_syscall_ctx_from_flow` carries no `_db`. `create_task` commits the task row itself, then the
EU hook `add`s + `flush`es a unit, and the handler's `finally: db.close()` rolled that flush back.
Same shape as runtime FR-30, on our side of the seam: every task unit since 2026-09-06 was lost.

★ These tests read the unit back through a SEPARATE session on a FILE-backed engine. The shared
`db_session` fixture (one StaticPool connection, one transaction) cannot see this defect — a flush
reads exactly like a commit there, which is how the runtime's own FR-30 tests passed on broken
code. Do not "simplify" these onto `db_session`.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.app_profile


@pytest.fixture
def own_session_db(tmp_path, monkeypatch):
    """A file-backed sqlite engine whose sessions do NOT share a connection.

    Patches `AINDY.db.database.SessionLocal` so `_session_from_context` opens the handler-owned
    session against it — the exact production path — and hands back a factory for the
    independent read-back session.
    """
    import tests.fixtures.db  # noqa: F401 — registers the sqlite compile hooks for JSONB/UUID/ARRAY
    from tests.fixtures.db import _import_model_registry

    _import_model_registry()
    from AINDY.db import database as db_module
    from AINDY.db.database import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'own.db'}", future=True)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    monkeypatch.setattr(db_module, "SessionLocal", factory)
    # task_service binds SessionLocal at import for its isolated event-emit session; point that
    # at the same engine so the emit lands (it is non-fatal either way, but keep the log clean).
    from apps.tasks.services import task_service

    monkeypatch.setattr(task_service, "SessionLocal", factory)
    yield factory
    engine.dispose()


def _flow_ctx(user_id: str, capability: str):
    """A SyscallContext the way a flow node builds one: no `_db`, so the handler owns its session."""
    from AINDY.kernel.syscall_dispatcher import make_syscall_ctx_from_flow

    return make_syscall_ctx_from_flow(
        {"run_id": str(uuid.uuid4()), "user_id": user_id, "trace_id": str(uuid.uuid4())},
        capabilities=[capability],
    )


def _unit_for(factory, task_id) -> tuple[str | None, str | None]:
    """Read the task's unit through a fresh session — the only read that cannot see a flush."""
    from AINDY.db.models.execution_unit import ExecutionUnit

    with factory() as reader:
        eu = (
            reader.query(ExecutionUnit)
            .filter(ExecutionUnit.source_type == "task", ExecutionUnit.source_id == str(task_id))
            .first()
        )
        return (str(eu.id), eu.status) if eu else (None, None)


def test_create_via_owned_session_persists_the_task_unit(own_session_db):
    from apps.tasks.syscalls.syscall_handlers import _handle_task_create

    user_id = str(uuid.uuid4())
    result = _handle_task_create({"task_name": "eu-persist"}, _flow_ctx(user_id, "task.create"))
    assert result["task_id"]

    eu_id, status = _unit_for(own_session_db, result["task_id"])
    assert eu_id is not None, "the create hook's unit was flushed and never committed"
    assert status == "pending"


def test_start_pause_complete_move_the_persisted_unit(own_session_db, monkeypatch):
    from apps.tasks.syscalls.syscall_handlers import (
        _handle_task_complete,
        _handle_task_create,
        _handle_task_pause,
        _handle_task_start,
    )

    user_id = str(uuid.uuid4())
    created = _handle_task_create({"task_name": "eu-lifecycle"}, _flow_ctx(user_id, "task.create"))
    task_id = created["task_id"]

    _handle_task_start({"task_name": "eu-lifecycle"}, _flow_ctx(user_id, "task.start"))
    assert _unit_for(own_session_db, task_id)[1] == "executing"

    _handle_task_pause({"task_name": "eu-lifecycle"}, _flow_ctx(user_id, "task.pause"))
    assert _unit_for(own_session_db, task_id)[1] == "waiting"

    # Completing a PAUSED task: the runtime's transition table forbids waiting -> completed, by
    # design (DEC-021). The hook must resume the unit first — the runtime's own wake path,
    # waiting -> resumed -> executing — or the unit is stuck `waiting` forever. Record every
    # transition the hook asks for, so the shape is pinned and not just the end state: the
    # previous shape stepped waiting -> executing directly and skipped `resumed`.
    from AINDY.core.execution_unit_service import ExecutionUnitService

    transitions: list[str] = []
    real_update_status = ExecutionUnitService.update_status

    def _recording_update_status(self, eu_id, new_status):
        transitions.append(new_status)
        return real_update_status(self, eu_id, new_status)

    monkeypatch.setattr(ExecutionUnitService, "update_status", _recording_update_status)

    _handle_task_complete({"task_name": "eu-lifecycle"}, _flow_ctx(user_id, "task.complete"))
    assert _unit_for(own_session_db, task_id)[1] == "completed"
    assert transitions == ["resumed", "executing", "completed"], transitions
