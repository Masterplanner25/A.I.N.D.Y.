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


def _apply_declared_worth(
    current_state: dict, state_update: dict, transcript: list[dict]
) -> dict:
    """Merge this turn's worth declarations into the session state, verified.

    ★ Handled apart from the generic `for key, value in state_update.items()` loop above for
    two reasons, both of which would otherwise lose data silently:

    1. That loop only copies keys **already present** in `current_state`. Sessions created
       before this field existed have no `declared_worth` key, so every declaration made in one
       of them would be dropped on the way in and nothing would ever say so. This is the third
       instance of one shape in this repo — Genesis captures it and the schema drops it.
    2. That loop **replaces**. Each turn's extraction reports only what that turn established,
       so a turn about anything else returns `[]` — which would wipe every prior declaration.
       Worth accumulates instead (`merge_declared_worth`).
    """
    from apps.masterplan.services.genesis_worth import WORTH_STATE_KEY, merge_declared_worth

    current_state[WORTH_STATE_KEY] = merge_declared_worth(
        current_state.get(WORTH_STATE_KEY),
        state_update.get(WORTH_STATE_KEY),
        transcript,
    )
    return current_state


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
                    "inferred_domains": [], "inferred_phases": [],
                    "declared_worth": [], "confidence": 0.0,
                },
            )
            db.add(session)
            db.flush()

        llm_output = call_genesis_import_llm(content, user_id=str(user_id), db=db)

        state_update = llm_output.get("state_update") or {}
        current_state = dict(session.summarized_state or {})
        for key, value in state_update.items():
            if key in current_state and value is not None:
                current_state[key] = value
        if "confidence" in current_state:
            current_state["confidence"] = max(0.0, min(current_state["confidence"], 1.0))

        reply = llm_output.get("reply", "")
        transcript = list(session.transcript or [])
        transcript.append(_transcript_entry("user", content))
        # After the imported text joins the transcript, so a worth stated in the plan the user
        # wrote is verifiable against their own words — an import is the user speaking.
        current_state = _apply_declared_worth(current_state, state_update, transcript)
        session.summarized_state = current_state
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
        current_state = dict(current_state)
        for key, value in state_update.items():
            if key in current_state and value is not None:
                current_state[key] = value

        if "confidence" in current_state:
            current_state["confidence"] = max(0.0, min(current_state["confidence"], 1.0))

        reply = llm_output.get("reply", "")
        # Appended after the call, so the model saw the conversation *before* this turn
        # and the new message exactly once rather than duplicated as history.
        transcript.append(_transcript_entry("user", message))
        # Worth is verified only after THIS turn is in the transcript. A declaration is almost
        # always made in the message that just arrived, so verifying before the append would
        # reject every real declaration on the turn it was made.
        current_state = _apply_declared_worth(current_state, state_update, transcript)
        session.summarized_state = current_state
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


def _handle_resolve_phase(payload: dict, ctx: SyscallContext) -> dict:
    """sys.v1.masterplan.resolve_phase — which phase a new task on this plan belongs to.

    ★ Tasks owns the write of `tasks.phase_id`; masterplan owns the decision. A task created
    for a plan without naming a phase lands on the plan's *current* phase — the frontier
    `phase_advance` proposes against — because that is where new work on a plan is by
    default, and because a task with no phase is invisible to the layer: it neither counts
    toward the phase's completion nor brings a dismissed proposal back. Measured 2026-09-10:
    every task created from the task screen landed with `phase_id = NULL`.

    Payload keys:
        masterplan_id  (str | int) — required
        strategy_id    (str)       — optional; when given it must be on this plan, and the
                                     task lands on the strategy's phase (a task under a
                                     strategy is scheduled where the strategy is)
        phase_id       (str)       — optional; when given it must be on this plan

    Returns:
        {"phase_id": str | None, "name": str | None, "ordinal": int | None,
         "strategy_id": str | None,
         "source": "strategy" | "requested" | "current" | "none"}
        `None`s for a plan that predates the layer — not an error, there is simply no phase.

    Raises:
        ValueError "NOT_FOUND:" when a requested phase or strategy is not on the plan.
    """
    from AINDY.db.database import SessionLocal
    from apps.masterplan.services.phase_advance import frontier_phase
    from apps.masterplan.strategy_layer import PlanPhase, PlanStrategy

    masterplan_id = int(payload["masterplan_id"])
    requested = payload.get("phase_id")
    strategy_id = payload.get("strategy_id")

    external_db = ctx.metadata.get("_db")
    owns_session = external_db is None
    db = external_db if external_db is not None else SessionLocal()
    try:
        phases = (
            db.query(PlanPhase)
            .filter(PlanPhase.masterplan_id == masterplan_id)
            .order_by(PlanPhase.ordinal.asc(), PlanPhase.created_at.asc())
            .all()
        )
        if strategy_id:
            strategy = (
                db.query(PlanStrategy)
                .filter(
                    PlanStrategy.id == str(strategy_id),
                    PlanStrategy.masterplan_id == masterplan_id,
                )
                .first()
            )
            if strategy is None:
                raise ValueError(
                    f"NOT_FOUND:strategy {strategy_id} is not on plan {masterplan_id}"
                )
            phase = next((row for row in phases if row.id == strategy.phase_id), None)
            return {
                "phase_id": phase.id if phase is not None else None,
                "name": phase.name if phase is not None else None,
                "ordinal": phase.ordinal if phase is not None else None,
                "strategy_id": strategy.id,
                "source": "strategy",
            }
        if requested:
            phase = next((row for row in phases if row.id == str(requested)), None)
            if phase is None:
                raise ValueError(f"NOT_FOUND:phase {requested} is not on plan {masterplan_id}")
            source = "requested"
        else:
            phase = frontier_phase(phases) if phases else None
            # Every phase complete: new work still needs a home, and the last phase is the
            # only one that is not "before" where the plan is.
            if phase is None and phases:
                phase = phases[-1]
            source = "current" if phase is not None else "none"
        return {
            "phase_id": phase.id if phase is not None else None,
            "name": phase.name if phase is not None else None,
            "ordinal": phase.ordinal if phase is not None else None,
            "strategy_id": None,
            "source": source,
        }
    finally:
        if owns_session:
            db.close()


def _handle_get_objective_attainment(payload: dict, ctx: SyscallContext) -> dict:
    """sys.v1.masterplan.get_objective_attainment — work done against each objective.

    The attainment spec's §4b gap, closed from the masterplan side: hours roll up
    task → strategy → objective, so each objective reports its own fraction. Analytics reads
    this by syscall for the attainment shadow (never by import).

    Payload keys:
        user_id        (str)       — required
        masterplan_id  (str | int) — optional; the user's active plan when omitted

    Returns:
        {"supported": bool, "masterplan_id": int | None, "objectives": [...],
         "plan": {hours_total, hours_completed, attainment_pct, objectives_measured},
         "unhoused": {strategies, hours_total, hours_completed}}
        `supported: False` with no objectives is a normal answer, not an error.
    """
    from AINDY.db.database import SessionLocal
    from apps.masterplan.masterplan import MasterPlan
    from apps.masterplan.services.phase_advance import objective_attainment

    user_id = payload["user_id"]
    masterplan_id = payload.get("masterplan_id")

    external_db = ctx.metadata.get("_db")
    owns_session = external_db is None
    db = external_db if external_db is not None else SessionLocal()
    try:
        query = db.query(MasterPlan).filter(MasterPlan.user_id == _as_uuid(user_id))
        if masterplan_id is not None:
            plan = query.filter(MasterPlan.id == int(masterplan_id)).first()
        else:
            plan = query.filter(MasterPlan.is_active.is_(True)).first()
        if plan is None:
            return {"supported": False, "masterplan_id": None, "objectives": [], "plan": {}, "unhoused": {}}
        return objective_attainment(db, masterplan_id=plan.id, user_id=user_id)
    finally:
        if owns_session:
            db.close()


def _as_uuid(value):
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


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
        name="sys.v1.masterplan.resolve_phase",
        handler=_handle_resolve_phase,
        capability="masterplan.read",
        description=(
            "Which phase a new task on this plan belongs to: the requested one if it is on "
            "the plan, else the plan's current phase."
        ),
        input_schema={
            "required": ["masterplan_id"],
            "properties": {
                "masterplan_id": {"type": "string"},
                "phase_id": {"type": "string"},
                "strategy_id": {"type": "string"},
            },
        },
        output_schema={
            "required": ["phase_id", "source"],
            "properties": {
                "phase_id": {"type": "string"},
                "name": {"type": "string"},
                "ordinal": {"type": "integer"},
                "source": {"type": "string"},
            },
        },
        stable=False,
    )
    register_syscall(
        name="sys.v1.masterplan.get_objective_attainment",
        handler=_handle_get_objective_attainment,
        capability="masterplan.read",
        description=(
            "Work done against each of a plan's objectives: hours completed / hours planned "
            "through task -> strategy -> objective. The attainment shadow's input."
        ),
        input_schema={
            "required": ["user_id"],
            "properties": {
                "user_id": {"type": "string"},
                "masterplan_id": {"type": "string"},
            },
        },
        output_schema={
            "required": ["supported", "objectives", "plan"],
            "properties": {
                "supported": {"type": "bool"},
                "masterplan_id": {"type": "integer"},
                "objectives": {"type": "array"},
                "plan": {"type": "object"},
                "unhoused": {"type": "object"},
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
