"""
Masterplan domain syscall handlers.

Registers sys.v1.masterplan.* syscalls. Called once at startup via
register_masterplan_syscall_handlers() which is invoked from apps/bootstrap.py.
"""
from __future__ import annotations

import logging
from uuid import UUID

from AINDY.kernel.syscall_registry import SyscallContext, register_syscall

logger = logging.getLogger(__name__)


def _session_from_context(ctx: SyscallContext):
    from AINDY.db.database import SessionLocal

    external_db = ctx.metadata.get("_db")
    if external_db is not None:
        return external_db, False
    return SessionLocal(), True


def _handle_assert_masterplan_owned(payload: dict, ctx: SyscallContext) -> dict:
    """sys.v1.masterplan.assert_owned — verify user owns the given MasterPlan.

    Payload keys:
        masterplan_id  (str | int) — required
        user_id        (str)       — required

    Context metadata keys (optional):
        _db — caller-provided SQLAlchemy Session (transaction preserved).

    Returns:
        {"owned": True, "masterplan_id": str} on success.

    Raises:
        ValueError with prefix "NOT_FOUND:" when plan is missing or not owned.
    """
    from fastapi import HTTPException

    from AINDY.db.database import SessionLocal
    from apps.masterplan.services.masterplan_service import assert_masterplan_owned

    masterplan_id = payload["masterplan_id"]
    user_id = payload["user_id"]

    external_db = ctx.metadata.get("_db")
    owns_session = external_db is None
    db = external_db if external_db is not None else SessionLocal()
    try:
        assert_masterplan_owned(db, masterplan_id, user_id)
        return {"owned": True, "masterplan_id": str(masterplan_id)}
    except HTTPException as exc:
        detail = exc.detail
        if isinstance(detail, dict):
            message = detail.get("message", str(detail))
        else:
            message = str(detail)
        if exc.status_code == 404:
            raise ValueError(f"NOT_FOUND:{message}") from exc
        raise ValueError(f"FORBIDDEN:{message}") from exc
    finally:
        if owns_session:
            db.close()


def _handle_get_masterplan_eta(payload: dict, ctx: SyscallContext) -> dict:
    from AINDY.db.database import SessionLocal
    from apps.masterplan.services.eta_service import calculate_eta

    masterplan_id = payload["masterplan_id"]
    user_id = payload["user_id"]

    external_db = ctx.metadata.get("_db")
    owns_session = external_db is None
    db = external_db if external_db is not None else SessionLocal()
    try:
        return {"eta": calculate_eta(db=db, masterplan_id=masterplan_id, user_id=user_id)}
    finally:
        if owns_session:
            db.close()


def _handle_recalculate_wcu(payload: dict, ctx: SyscallContext) -> dict:
    from AINDY.db.database import SessionLocal
    from apps.masterplan.services.wcu_service import calculate_wcu

    masterplan_id = payload["masterplan_id"]
    user_id = payload["user_id"]

    external_db = ctx.metadata.get("_db")
    owns_session = external_db is None
    db = external_db if external_db is not None else SessionLocal()
    try:
        return {"wcu": calculate_wcu(db=db, masterplan_id=masterplan_id, user_id=user_id)}
    finally:
        if owns_session:
            db.close()


def _handle_get_active_masterplan(payload: dict, ctx: SyscallContext) -> dict:
    from apps.masterplan.models import MasterPlan

    user_id = payload["user_id"]
    db, owns_session = _session_from_context(ctx)
    try:
        plan = (
            db.query(MasterPlan)
            .filter(MasterPlan.user_id == user_id, MasterPlan.is_active.is_(True))
            .first()
        )
        if plan is None:
            return {"masterplan": None}
        return {
            "masterplan": {
                "id": plan.id,
                "anchor_date": plan.anchor_date.isoformat() if plan.anchor_date else None,
            }
        }
    finally:
        if owns_session:
            db.close()


# Full history is kept for the user to read back; only a recent window is sent to the
# model (see genesis_ai.build_transcript_window). The cap bounds unbounded growth of a
# JSON column on a session that never ends.
MAX_TRANSCRIPT_ENTRIES_STORED = 200


def _transcript_entry(role: str, content: str) -> dict:
    from datetime import datetime, timezone

    return {
        "role": role,
        "content": content,
        "at": datetime.now(timezone.utc).isoformat(),
    }


def _trim_transcript(entries: list[dict]) -> list[dict]:
    """Keep the most recent entries. Oldest go first — the near past is what matters."""
    if len(entries) <= MAX_TRANSCRIPT_ENTRIES_STORED:
        return entries
    return entries[-MAX_TRANSCRIPT_ENTRIES_STORED:]


# Upper bound on an imported plan, sized against the model that reads it rather than
# guessed. `call_genesis_import_llm` uses gpt-4o-mini (128k-token context); 80,000
# characters is roughly 20k tokens, comfortably inside it while still refusing a
# pathological paste.
#
# Was 20,000, which was below the size of a real plan and therefore not a safety limit
# but a wall. Measured 2026-08-16 against the owner's own corpus:
#
#   V1   8,184 chars   V2  65,671   V3  50,900   V4  22,749
#
# V4 — the version anyone would actually import — missed the old cap by 2,749
# characters and was rejected outright. The limit was never protecting the model: V4 is
# ~6k tokens and even V2 is only ~17k. It was protecting nothing and blocking the
# feature's primary use case.
#
# Keep a cap: input to an LLM call should always be bounded, and an unbounded paste is
# a cost and latency hazard on a path that already has one (FR-15). Just bound it where
# the real constraint is.
MAX_IMPORT_CHARS = 80000


def _handle_genesis_import_plan(payload: dict, ctx: SyscallContext) -> dict:
    """Seed a Genesis session from a plan the user already wrote.

    Imports into the *conversation*, not straight into a locked MasterPlan: the whole
    reason for accepting free text is so an existing plan can be discussed and refined
    with Genesis before it is locked. The imported text becomes the first user turn and
    the extraction summary the first assistant turn, so the session opens mid-dialogue
    with real context rather than from a blank prompt.

    Reuses the active session when one exists — matching `genesis_session_create`'s
    idempotency — so importing does not silently orphan work already in progress.
    """
    from apps.masterplan.models import GenesisSessionDB
    from apps.masterplan.services.genesis_ai import call_genesis_import_llm

    content = (payload.get("content") or "").strip()
    if not content:
        raise ValueError("sys.v1.genesis.import_plan requires 'content'")
    if len(content) > MAX_IMPORT_CHARS:
        raise ValueError(
            f"Plan is too long to import ({len(content)} chars; limit {MAX_IMPORT_CHARS})."
        )

    db, owns_session = _session_from_context(ctx)
    try:
        user_id = UUID(str(ctx.user_id))
        session = (
            db.query(GenesisSessionDB)
            .filter(
                GenesisSessionDB.user_id == user_id,
                GenesisSessionDB.status == "active",
            )
            .order_by(GenesisSessionDB.id.desc())
            .first()
        )
        resumed = session is not None
        if session is None:
            session = GenesisSessionDB(
                user_id=user_id,
                synthesis_ready=False,
                summarized_state={
                    "vision_summary": None, "time_horizon": None,
                    "mechanism_summary": None, "assets_summary": None,
                    "inferred_domains": [], "inferred_phases": [], "confidence": 0.0,
                },
            )
            db.add(session)
            db.flush()

        llm_output = call_genesis_import_llm(content, user_id=str(user_id), db=db)

        current_state = dict(session.summarized_state or {})
        for key, value in (llm_output.get("state_update") or {}).items():
            if key in current_state and value is not None:
                current_state[key] = value
        if "confidence" in current_state:
            current_state["confidence"] = max(0.0, min(current_state["confidence"], 1.0))
        session.summarized_state = current_state

        reply = llm_output.get("reply", "")
        transcript = list(session.transcript or [])
        transcript.append(_transcript_entry("user", content))
        if reply:
            transcript.append(_transcript_entry("assistant", reply))
        session.transcript = _trim_transcript(transcript)

        if llm_output.get("synthesis_ready", False) and not session.synthesis_ready:
            session.synthesis_ready = True
        db.commit()
        db.refresh(session)

        return {
            "session_id": session.id,
            "resumed": resumed,
            "reply": reply,
            "summarized_state": session.summarized_state,
            "transcript": session.transcript or [],
            "synthesis_ready": bool(session.synthesis_ready),
        }
    except Exception:
        db.rollback()
        raise
    finally:
        if owns_session:
            db.close()


def _handle_genesis_execute_llm(payload: dict, ctx: SyscallContext) -> dict:
    from apps.masterplan.models import GenesisSessionDB
    from apps.masterplan.services.genesis_ai import call_genesis_llm

    session_id = payload.get("session_id")
    message = payload.get("message")
    if not session_id:
        raise ValueError("sys.v1.genesis.execute_llm requires 'session_id'")
    if not message:
        raise ValueError("sys.v1.genesis.execute_llm requires 'message'")

    db, owns_session = _session_from_context(ctx)
    try:
        user_id = UUID(str(ctx.user_id))
        session = (
            db.query(GenesisSessionDB)
            .filter(
                GenesisSessionDB.id == session_id,
                GenesisSessionDB.user_id == user_id,
            )
            .first()
        )
        if not session:
            raise ValueError("GenesisSession not found")

        current_state = session.summarized_state or {}
        transcript = list(session.transcript or [])

        llm_output = call_genesis_llm(
            message=message,
            current_state=current_state,
            user_id=str(user_id),
            db=db,
            transcript=transcript,
        )

        state_update = llm_output.get("state_update", {})
        for key, value in state_update.items():
            if key in current_state and value is not None:
                current_state[key] = value

        if "confidence" in current_state:
            current_state["confidence"] = max(0.0, min(current_state["confidence"], 1.0))

        session.summarized_state = current_state

        reply = llm_output.get("reply", "")
        # Appended after the call, so the model saw the conversation *before* this turn
        # and the new message exactly once rather than duplicated as history.
        transcript.append(_transcript_entry("user", message))
        if reply:
            transcript.append(_transcript_entry("assistant", reply))
        # JSON column reassignment (not in-place mutation) so SQLAlchemy marks it dirty.
        session.transcript = _trim_transcript(transcript)

        if llm_output.get("synthesis_ready", False) and not session.synthesis_ready:
            session.synthesis_ready = True
        db.commit()

        return {
            "genesis_response": {
                "reply": llm_output.get("reply", ""),
                "synthesis_ready": session.synthesis_ready,
            }
        }
    except Exception:
        db.rollback()
        raise
    finally:
        if owns_session:
            db.close()


def _handle_genesis_call_llm(payload: dict, ctx: SyscallContext) -> dict:
    from apps.masterplan.services.genesis_ai import call_genesis_llm

    message = payload.get("message") or payload.get("query") or payload.get("input")
    current_state = payload.get("current_state") or payload.get("state") or {}
    if not message:
        raise ValueError("sys.v1.genesis.call_llm requires 'message'")

    db, owns_session = _session_from_context(ctx)
    try:
        return call_genesis_llm(
            message=str(message),
            current_state=current_state,
            user_id=ctx.user_id,
            db=db,
        )
    finally:
        if owns_session:
            db.close()


def _handle_genesis_message(payload: dict, ctx: SyscallContext) -> dict:
    from AINDY.runtime.flow_engine import execute_intent

    session_id = payload.get("session_id")
    message = payload.get("message")
    if not message:
        raise ValueError("sys.v1.genesis.message requires 'message'")
    if not session_id:
        raise ValueError("sys.v1.genesis.message requires 'session_id'")

    db, owns_session = _session_from_context(ctx)
    try:
        result = execute_intent(
            intent_data={
                "workflow_type": "genesis_message",
                "session_id": session_id,
                "message": message,
            },
            db=db,
            user_id=ctx.user_id,
        )
        return result if isinstance(result, dict) else {"result": result}
    finally:
        if owns_session:
            db.close()


def _handle_goal_create(payload: dict, ctx: SyscallContext) -> dict:
    from apps.masterplan.services.goal_service import create_goal

    name = payload.get("name")
    if not name:
        raise ValueError("sys.v1.goal.create requires 'name'")

    db, owns_session = _session_from_context(ctx)
    try:
        goal = create_goal(
            db,
            user_id=ctx.user_id,
            name=name,
            description=payload.get("description"),
            goal_type=payload.get("goal_type", "strategic"),
            priority=payload.get("priority", 0.5),
            status=payload.get("status", "active"),
            success_metric=payload.get("success_metric", {}),
        )
        return {"goal_create_result": goal}
    finally:
        if owns_session:
            db.close()


def register_masterplan_syscall_handlers() -> None:
    """Register all masterplan domain syscall handlers.

    Called once at application startup from apps/bootstrap.py.
    Safe to call multiple times — idempotent.
    """
    register_syscall(
        name="sys.v1.masterplan.assert_owned",
        handler=_handle_assert_masterplan_owned,
        capability="masterplan.read",
        description="Assert that the given user owns the given MasterPlan.",
        input_schema={
            "required": ["masterplan_id", "user_id"],
            "properties": {
                "masterplan_id": {"type": "string"},
                "user_id": {"type": "string"},
            },
        },
        output_schema={
            "required": ["owned"],
            "properties": {
                "owned": {"type": "bool"},
                "masterplan_id": {"type": "string"},
            },
        },
        stable=False,
    )
    register_syscall(
        name="sys.v1.masterplan.get_eta",
        handler=_handle_get_masterplan_eta,
        capability="masterplan.read",
        description="Calculate and return the ETA projection for a masterplan.",
        input_schema={
            "required": ["masterplan_id", "user_id"],
            "properties": {
                "masterplan_id": {"type": "string"},
                "user_id": {"type": "string"},
            },
        },
        output_schema={
            "required": ["eta"],
            "properties": {
                "eta": {"type": "dict"},
            },
        },
        stable=False,
    )
    register_syscall(
        name="sys.v1.masterplan.recalculate_wcu",
        handler=_handle_recalculate_wcu,
        capability="masterplan.read",
        description="Recompute + persist total_wcu (Work Complexity Units) for a plan's completed tasks and re-evaluate its phase.",
        input_schema={
            "required": ["masterplan_id", "user_id"],
            "properties": {
                "masterplan_id": {"type": "string"},
                "user_id": {"type": "string"},
            },
        },
        output_schema={
            "required": ["wcu"],
            "properties": {
                "wcu": {"type": "dict"},
            },
        },
        stable=False,
    )
    register_syscall(
        name="sys.v1.masterplan.get_active",
        handler=_handle_get_active_masterplan,
        capability="masterplan.read",
        description="Return the active masterplan summary for the given user.",
        input_schema={
            "required": ["user_id"],
            "properties": {
                "user_id": {"type": "string"},
            },
        },
        stable=False,
    )
    register_syscall(
        name="sys.v1.genesis.execute_llm",
        handler=_handle_genesis_execute_llm,
        capability="genesis.execute_llm",
        description="Call Genesis LLM and update session state.",
        stable=False,
    )
    register_syscall(
        name="sys.v1.genesis.import_plan",
        handler=_handle_genesis_import_plan,
        capability="genesis.execute_llm",
        description="Seed a Genesis session from a plan the user already wrote, so it can be discussed before locking.",
        stable=False,
    )
    register_syscall(
        name="sys.v1.genesis.message",
        handler=_handle_genesis_message,
        capability="genesis.message",
        description="Run the full genesis_message flow.",
        stable=False,
    )
    register_syscall(
        name="sys.v1.genesis.call_llm",
        handler=_handle_genesis_call_llm,
        capability="genesis.execute_llm",
        description="Call Genesis LLM without session persistence.",
        stable=False,
    )
    register_syscall(
        name="sys.v1.goal.create",
        handler=_handle_goal_create,
        capability="goal.create",
        description="Create a goal.",
        stable=False,
    )
    logger.info(
        "[masterplan_syscalls] registered sys.v1.masterplan.assert_owned and sys.v1.masterplan.get_eta"
    )
