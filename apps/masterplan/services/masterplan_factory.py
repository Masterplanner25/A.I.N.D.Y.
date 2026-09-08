import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID
from AINDY.core.execution_signal_helper import queue_memory_capture
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from apps.masterplan.models import GenesisSessionDB, MasterPlan
from apps.masterplan.services.posture import determine_posture  # adjust import if needed
from AINDY.core.observability_events import emit_observability_event


logger = logging.getLogger(__name__)


def create_masterplan_from_genesis(session_id: int, draft: dict, db: Session, user_id: str = None):

    session = (
        db.query(GenesisSessionDB)
        .filter(GenesisSessionDB.id == session_id)
        .with_for_update()
        .first()
    )

    if not session:
        raise Exception("Genesis session not found")

    if session.status == "locked":
        raise Exception("Session already locked")

    if not session.synthesis_ready:
        raise ValueError("Session is not synthesis-ready — run /genesis/synthesize first")

    # Load draft from session if available; fall back to caller-supplied draft
    draft_to_use = session.draft_json or draft

    # Version label scoped per-user to avoid global numbering pollution
    if user_id:
        user_uuid = UUID(str(user_id))
        user_plans = db.query(MasterPlan).filter(MasterPlan.user_id == user_uuid).order_by(MasterPlan.id).all()
    else:
        user_plans = db.query(MasterPlan).order_by(MasterPlan.id).all()

    if not user_plans:
        version_label = "V1"
        is_origin = True
        parent_id = None
    else:
        version_label = f"V{len(user_plans) + 1}"
        is_origin = False
        parent_id = user_plans[-1].id

    # Timeline
    horizon = draft_to_use.get("time_horizon_years", 5)
    # MasterPlan.start_date/target_date are legacy naive DateTime columns; SQLAlchemy may strip tzinfo here.
    start_date = datetime.now(timezone.utc)
    target_date = start_date + timedelta(days=int(horizon * 365))

    # Posture
    posture = determine_posture(draft_to_use)

    try:
        masterplan = MasterPlan(
            version_label=version_label,
            is_origin=is_origin,
            is_active=False,
            user_id=UUID(str(user_id)) if user_id else None,
            status="locked",
            structure_json=draft_to_use,
            posture=posture,
            locked_at=start_date,
            start_date=start_date,
            duration_years=horizon,
            target_date=target_date,
            parent_id=parent_id,
            linked_genesis_session_id=session.id
        )

        db.add(masterplan)

        # Freeze Genesis
        session.status = "locked"
        session.locked_at = start_date

        db.commit()
        db.refresh(masterplan)
    except IntegrityError:
        db.rollback()
        raise ValueError(
            f"A masterplan already exists for genesis session {session_id}"
        )
    except Exception:
        db.rollback()
        raise

    # ── Worth declarations: the plan's stated value becomes rows ──────────────────────────
    #
    # The same materialisation shape as phases → tasks, applied to the one thing Genesis was
    # already capturing and the schema was already dropping. Only declarations backed by the
    # user's own words survive; see `genesis_worth` for why that check is code and not a
    # prompt rule.
    #
    # Non-fatal on purpose. Locking a plan is the user's act, and a worth row that failed to
    # write must not undo it — the plan above is already committed by this point.
    # Each declaration is committed by the analytics syscall that writes it, so a failure
    # part-way leaves the earlier ones recorded. That is the honest outcome: they were stated
    # and they were stored.
    worth_result: dict = {"recorded": [], "dropped": []}
    if user_id:
        try:
            from apps.masterplan.services.genesis_worth import (
                WORTH_STATE_KEY,
                record_genesis_declarations,
            )

            worth_result = record_genesis_declarations(
                db,
                user_id=user_id,
                masterplan_id=masterplan.id,
                declared_worth=(session.summarized_state or {}).get(WORTH_STATE_KEY),
                transcript=session.transcript,
            )
        except Exception:
            db.rollback()
            emit_observability_event(
                logger,
                event="masterplan_worth_declaration_failed",
                session_id=session_id,
                user_id=user_id,
                masterplan_id=getattr(masterplan, "id", None),
            )

    # ── Strategy layer: the plan's two axes become rows ───────────────────────────────────
    #
    # Genesis has always emitted both — three `core_domains` and five `phases` — and they were
    # materialised as tasks and read-only text respectively (STRATEGY_LAYER_SPEC §3). Seeding
    # them here is the same materialisation as phases → tasks, applied to the layer that was
    # flattened into it.
    #
    # Nothing reads these yet (§8), so this is additive: a plan locked today gets its layer,
    # and step 3 is a code change rather than a code change plus a backfill.
    #
    # Non-fatal, like the worth declarations above. Locking is the user's act.
    try:
        from apps.masterplan.services.strategy_layer_seed import seed_strategy_layer

        seed_strategy_layer(db, masterplan_id=masterplan.id, user_id=user_id)
    except Exception:
        db.rollback()
        emit_observability_event(
            logger,
            event="masterplan_strategy_layer_seed_failed",
            session_id=session_id,
            user_id=user_id,
            masterplan_id=getattr(masterplan, "id", None),
        )

    # Capture lock event to memory (fire-and-forget)
    if user_id:
        try:
            vision = ""
            if isinstance(draft_to_use, dict):
                vision = str(draft_to_use.get("vision_statement") or draft_to_use.get("vision_summary") or "")
            queue_memory_capture(
                db=db,
                user_id=user_id,
                agent_namespace="genesis",
                event_type="masterplan_locked",
                content=(
                    f"Masterplan locked: {masterplan.version_label} "
                    f"(posture: {masterplan.posture}, session: {session_id}). "
                    f"Vision: {vision[:200]}"
                ),
                source="genesis_lock",
                tags=["genesis", "masterplan", "decision"],
                node_type="decision",
                force=True,
            )
        except Exception:
            emit_observability_event(
                logger,
                event="masterplan_lock_memory_capture_failed",
                session_id=session_id,
                user_id=user_id,
                masterplan_id=getattr(masterplan, "id", None),
            )
            raise

    # Observe for identity inference (non-blocking)
    if user_id:
        try:
            from apps.identity.public import observe_identity_event

            observe_identity_event(
                user_id=user_id,
                db=db,
                event_type="masterplan_locked",
                context={"posture": masterplan.posture},
            )
        except Exception:
            emit_observability_event(
                logger,
                event="masterplan_identity_observation_failed",
                session_id=session_id,
                user_id=user_id,
                masterplan_id=getattr(masterplan, "id", None),
            )
            raise

    # Carried on the instance rather than in the return type: every caller returns the
    # MasterPlan itself, and a tuple here would be a signature change across four call sites
    # for a diagnostic. Nothing depends on it; it exists so a lock can say what it recorded.
    masterplan.genesis_worth_result = worth_result
    return masterplan


