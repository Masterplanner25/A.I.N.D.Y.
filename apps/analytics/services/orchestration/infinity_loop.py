import logging
import uuid
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
from AINDY.core.observability_events import emit_observability_event
from AINDY.core.system_event_service import emit_error_event
from AINDY.platform_layer.trace_context import get_current_trace_id
from AINDY.platform_layer.user_ids import parse_user_id

from apps.analytics.services.reasoning import (
    decide,
    evaluate_state,
    reason,
    summarize_feedback,
)

THRASH_GUARD_MINUTES = 60
TASK_REPRIORITIZATION_LIMIT = 5

EXPECTED_SCORE_OFFSETS = {
    "continue_highest_priority_task": 3.0,
    "create_new_task": 2.0,
    "reprioritize_tasks": 1.5,
    "review_plan": 1.0,
}


def _normalize_trigger_event(trigger_event: str) -> str:
    mapping = {
        "task_completion": "task_completed",
        "arm_analysis": "arm_analyzed",
    }
    return mapping.get(trigger_event or "manual", trigger_event or "manual")


def _normalize_user_id(user_id: str | uuid.UUID | None):
    return parse_user_id(user_id) if user_id is not None else None


def get_latest_adjustment_record(*args, **kwargs):
    from ..integration import dependency_adapter

    return dependency_adapter.get_latest_loop_adjustment(*args, **kwargs)


def list_strategy_accuracy_adjustments(*args, **kwargs):
    from ..integration import dependency_adapter

    return dependency_adapter.list_strategy_accuracy_adjustments(*args, **kwargs)


def get_pending_adjustment_record(*args, **kwargs):
    from ..integration import dependency_adapter

    return dependency_adapter.get_pending_loop_adjustment(*args, **kwargs)


def list_recent_feedback_rows(*args, **kwargs):
    from ..integration import dependency_adapter

    return dependency_adapter.list_recent_feedback_rows(*args, **kwargs)


def fetch_next_ready_task(*args, **kwargs):
    from ..integration import dependency_adapter

    return dependency_adapter.fetch_next_ready_task(*args, **kwargs)


def list_incomplete_tasks(*args, **kwargs):
    from ..integration import dependency_adapter

    return dependency_adapter.list_incomplete_tasks(*args, **kwargs)


def create_loop_adjustment_record(**kwargs):
    from ..integration import dependency_adapter

    return dependency_adapter.create_loop_adjustment(**kwargs)


def get_latest_adjustment_for_update(*args, **kwargs):
    from ..integration import dependency_adapter

    return dependency_adapter.get_latest_loop_adjustment_for_update(*args, **kwargs)


def update_loop_adjustment_record(*args, **kwargs):
    from ..integration import dependency_adapter

    return dependency_adapter.update_loop_adjustment(*args, **kwargs)


def get_latest_adjustment(user_id: str, db):
    try:
        return get_latest_adjustment_record(user_id=user_id, db=db)
    except Exception as exc:
        logger.warning("[InfinityLoop] get_latest_adjustment failed for %s: %s", user_id, exc)
        return None


def _adjustment_get(adjustment, key: str, default=None):
    if adjustment is None:
        return default
    if isinstance(adjustment, dict):
        return adjustment.get(key, default)
    return getattr(adjustment, key, default)


def serialize_adjustment(adjustment) -> dict | None:
    if not adjustment:
        return None
    return {
        "id": str(_adjustment_get(adjustment, "id")),
        "trace_id": _adjustment_get(adjustment, "trace_id"),
        "decision_type": _adjustment_get(adjustment, "decision_type"),
        "expected_outcome": _adjustment_get(adjustment, "expected_outcome"),
        "expected_score": _adjustment_get(adjustment, "expected_score"),
        "actual_outcome": _adjustment_get(adjustment, "actual_outcome"),
        "actual_score": _adjustment_get(adjustment, "actual_score"),
        "prediction_accuracy": _adjustment_get(adjustment, "prediction_accuracy"),
        "deviation_score": _adjustment_get(adjustment, "deviation_score"),
        "applied_at": (
            _adjustment_get(adjustment, "applied_at").isoformat()
            if getattr(_adjustment_get(adjustment, "applied_at"), "isoformat", None)
            else _adjustment_get(adjustment, "applied_at")
        ),
        "adjustment_payload": _adjustment_get(adjustment, "adjustment_payload"),
    }


def _derive_expected_outcome(decision_type: str) -> str:
    if decision_type in {"continue_highest_priority_task", "create_new_task", "reprioritize_tasks"}:
        return "task_progress"
    if decision_type == "review_plan":
        return "plan_adjustment"
    return "stable_progress"


def _derive_actual_outcome(trigger_event: str) -> str:
    normalized = _normalize_trigger_event(trigger_event)
    if normalized in {"task_completed", "agent_completed"}:
        return "task_progress"
    if normalized in {"manual", "scheduled"}:
        return "stable_progress"
    return "plan_adjustment"


def _build_expectation(
    decision_type: str,
    score_snapshot: dict | None,
    offsets: dict | None = None,
) -> tuple[str, int]:
    baseline = float((score_snapshot or {}).get("master_score", 50.0) or 50.0)
    use_offsets = offsets if offsets else EXPECTED_SCORE_OFFSETS
    expected_score = int(round(min(100.0, baseline + use_offsets.get(decision_type, 1.0))))
    return _derive_expected_outcome(decision_type), expected_score


def _get_strategy_accuracy_context(user_id: str, db, limit: int = 20) -> dict[str, float]:
    try:
        rows = list_strategy_accuracy_adjustments(user_id=user_id, db=db, limit=limit)
        grouped: dict[str, list[float]] = {}
        for row in rows:
            decision_type = _adjustment_get(row, "decision_type")
            prediction_accuracy = _adjustment_get(row, "prediction_accuracy")
            if decision_type is None or prediction_accuracy is None:
                continue
            grouped.setdefault(decision_type, []).append(float(prediction_accuracy) / 100.0)
        return {
            decision_type: round(sum(values) / len(values), 4)
            for decision_type, values in grouped.items()
            if values
        }
    except Exception as exc:
        logger.warning("[InfinityLoop] strategy accuracy lookup failed for %s: %s", user_id, exc)
        return {}


def evaluate_pending_adjustment(
    *,
    user_id: str,
    trigger_event: str,
    actual_score: float | None,
    db,
) -> dict | None:
    from .concurrency import (
        supports_managed_transactions,
        transaction_scope,
    )

    try:
        adjustment = None
        if _normalize_user_id(user_id) is None:
            return None
        with transaction_scope(db):
            adjustment = get_pending_adjustment_record(
                user_id=user_id,
                db=db,
                managed_transactions=supports_managed_transactions(db),
            )
            if not adjustment:
                return None

            # Captured before the update for the shadow expectation log (Phase 0).
            score_snapshot_ctx = _adjustment_get(adjustment, "score_snapshot")

            actual_outcome = _derive_actual_outcome(trigger_event)
            expected_outcome = _adjustment_get(adjustment, "expected_outcome") or _derive_expected_outcome(
                _adjustment_get(adjustment, "decision_type")
            )
            expected_score = float(_adjustment_get(adjustment, "expected_score") or 50.0)
            actual_score_value = float(
                actual_score
                if actual_score is not None
                else (_adjustment_get(adjustment, "score_snapshot") or {}).get("master_score", 50.0)
            )
            # Phase 1 advisory (BUILD_PLAN learned recursion): blend the learned
            # expectation into the anchor — heuristic anchors, bounded, flag-gated
            # (AINDY_INFINITY_LEARNED_ADVISORY). Falls back to the heuristic when off
            # or no model exists, and never raises into REFLECT.
            try:
                from ..scoring.expectation_model_service import blended_expected_score

                effective_expected, advisory_meta = blended_expected_score(
                    db,
                    _adjustment_get(adjustment, "decision_type"),
                    score_snapshot_ctx,
                    expected_score,
                )
            except Exception as _adv_exc:
                logger.debug("[InfinityLoop] advisory blend skipped: %s", _adv_exc)
                effective_expected, advisory_meta = expected_score, {"applied": False, "reason": "error"}

            score_delta = round(actual_score_value - effective_expected, 2)
            deviation_score = int(round(abs(score_delta)))
            outcome_match = 1.0 if actual_outcome == expected_outcome else 0.5
            score_accuracy = max(0.0, 1.0 - min(1.0, abs(score_delta) / 25.0))
            prediction_accuracy = int(round(((outcome_match * 0.4) + (score_accuracy * 0.6)) * 100))

            payload = dict(_adjustment_get(adjustment, "adjustment_payload") or {})
            payload["expected_vs_actual"] = {
                "expected_outcome": expected_outcome,
                "actual_outcome": actual_outcome,
                "expected_score": expected_score,
                "effective_expected_score": effective_expected,
                "advisory": advisory_meta,
                "actual_score": actual_score_value,
                "score_delta": score_delta,
                "deviation_score": deviation_score,
                "prediction_accuracy": prediction_accuracy,
            }
            adjustment = update_loop_adjustment_record(
                adjustment_id=_adjustment_get(adjustment, "id"),
                db=db,
                user_id=user_id,  # the dispatch tenant — without it the job path is refused (SYSCALL-SILENT-ERRORS-1)
                actual_outcome=actual_outcome,
                actual_score=int(round(actual_score_value)),
                deviation_score=deviation_score,
                prediction_accuracy=prediction_accuracy,
                evaluated_at=datetime.now(timezone.utc),
                adjustment_payload=payload,
            ) or adjustment

        # Shadow-mode learned expectation (Phase 0 — BUILD_PLAN learned recursion):
        # logs a prediction next to the heuristic for the soak comparison. Default
        # off (AINDY_INFINITY_LEARNED_SHADOW); drives nothing, isolated transaction.
        try:
            from ..scoring.expectation_model_service import shadow_log_expectation

            shadow_log_expectation(
                db=db,
                loop_adjustment_id=_adjustment_get(adjustment, "id"),
                decision_type=_adjustment_get(adjustment, "decision_type"),
                score_snapshot=score_snapshot_ctx,
                heuristic_expected=expected_score,
                actual_score=actual_score_value,
            )
        except Exception as _shadow_exc:
            logger.debug("[InfinityLoop] shadow expectation logging skipped: %s", _shadow_exc)

        try:
            from ..scoring.kpi_weight_service import adapt_kpi_weights

            adapt_kpi_weights(db, user_id)
        except Exception as _adapt_exc:
            logger.debug("[InfinityLoop] weight adaptation skipped: %s", _adapt_exc)

        return {
            "adjustment_id": str(_adjustment_get(adjustment, "id")),
            "prediction_accuracy": prediction_accuracy,
            "deviation_score": deviation_score,
            "score_delta": score_delta,
        }
    except Exception as exc:
        logger.warning("[InfinityLoop] evaluate_pending_adjustment failed for %s: %s", user_id, exc)
        try:
            db.rollback()
        except Exception:
            logger.exception("[InfinityLoop] rollback failed while evaluating pending adjustment")
        return None


def _get_recent_feedback_context(user_id: str, db, limit: int = 5) -> dict:
    try:
        rows = list_recent_feedback_rows(user_id=user_id, db=db, limit=limit)
        # Pure summarization is owned by the reasoning feedback analyzer (Phase 2).
        return summarize_feedback(rows)
    except Exception as exc:
        logger.warning("[InfinityLoop] feedback context lookup failed for %s: %s", user_id, exc)
        return {"count": 0, "positive": 0, "negative": 0, "latest_feedback_text": None}


def _get_top_incomplete_task(user_id: str, db) -> dict | None:
    try:
        next_ready = fetch_next_ready_task(db=db, user_id=user_id)
        if next_ready:
            return next_ready
    except Exception as exc:
        logger.warning("[InfinityLoop] next ready task lookup failed for %s: %s", user_id, exc)
    tasks = list_incomplete_tasks(user_id=user_id, db=db, limit=1)
    if not tasks:
        return None
    task = tasks[0]
    return {
        "task_id": task.id,
        "name": task.name,
        "priority": task.priority,
        "status": task.status,
    }


def _decide(
    score_snapshot: dict | None,
    feedback_context: dict | None = None,
    memory_signals: list[dict] | None = None,
    system_state: dict | None = None,
    goals: list[dict] | None = None,
    social_signals: list[dict] | None = None,
    kpi_low: dict | None = None,
) -> tuple[str, dict]:
    """Thin wrapper over the extracted reasoning engine.

    The decision logic (threshold branches + memory/system/goal/social weighting)
    now lives in ``apps/analytics/services/reasoning/`` (ARM/Reasoning Phase 1).
    This wrapper preserves the legacy ``(decision_type, payload)`` shape for the
    loop and existing callers/tests. Strategy-accuracy weighting remains in the
    loop (it needs a DB lookup) and is applied after this returns.
    """
    snapshot = evaluate_state(
        score_snapshot,
        feedback_context=feedback_context,
        memory_signals=memory_signals,
        system_state=system_state,
        goals=goals,
        social_signals=social_signals,
        kpi_low=kpi_low,
    )
    return decide(snapshot).to_tuple()


def _reprioritize_tasks(user_id: str, db) -> dict:
    from .concurrency import transaction_scope

    if _normalize_user_id(user_id) is None:
        return {"reason": "invalid_user_id", "task_ids": []}
    tasks = list_incomplete_tasks(user_id=user_id, db=db, limit=TASK_REPRIORITIZATION_LIMIT)

    if not tasks:
        return {"reason": "no_incomplete_tasks", "task_ids": []}

    with transaction_scope(db):
        affected = []
        for task in tasks:
            previous_priority = task.priority
            task.priority = "high"
            affected.append(
                {
                    "task_id": task.id,
                    "name": task.name,
                    "previous_priority": previous_priority,
                    "new_priority": task.priority,
                }
            )
            db.add(task)
        db.flush()
        return {"task_ids": [item["task_id"] for item in affected], "tasks": affected}


def run_loop(
    user_id: str,
    trigger_event: str,
    db,
    score_snapshot: dict | None = None,
    feedback_context: dict | None = None,
    loop_context: dict | None = None,
):
    from .concurrency import (
        supports_managed_transactions,
        transaction_scope,
    )

    try:
        with transaction_scope(db):
            normalized_trigger = _normalize_trigger_event(trigger_event)
            persisted_user_id = _normalize_user_id(user_id)
            owner_user_id = persisted_user_id or user_id
            if score_snapshot is None:
                from ..scoring.infinity_service import get_user_kpi_snapshot

                score_snapshot = get_user_kpi_snapshot(user_id=owner_user_id, db=db)
            feedback_context = feedback_context or _get_recent_feedback_context(user_id=owner_user_id, db=db)
            memory_signals = list((loop_context or {}).get("memory_signals") or [])
            system_state = dict((loop_context or {}).get("system_state") or {})
            goals = list((loop_context or {}).get("goals") or [])
            social_signals = list((loop_context or {}).get("social_signals") or [])
            try:
                from ..scoring.policy_adaptation_service import get_effective_thresholds

                policy = get_effective_thresholds(db, owner_user_id)
            except Exception as exc:
                logger.debug("[InfinityLoop] policy lookup failed for %s: %s", owner_user_id, exc)
                policy = {"kpi_low": {}, "offsets": dict(EXPECTED_SCORE_OFFSETS)}

            kpi_low = dict(policy.get("kpi_low") or {})
            adapted_offsets = dict(policy.get("offsets") or EXPECTED_SCORE_OFFSETS)

            # The loop is a consumer of the reusable reasoning service (Phase 2):
            # it gathers context + the DB-backed strategy-accuracy history, and the
            # service composes state evaluation, the decision engine, and strategy
            # selection into one normalized result.
            strategy_accuracy = _get_strategy_accuracy_context(owner_user_id, db)
            decision_type, payload = reason(
                score_snapshot,
                feedback_context=feedback_context,
                memory_signals=memory_signals,
                system_state=system_state,
                goals=goals,
                social_signals=social_signals,
                kpi_low=kpi_low,
                strategy_accuracy=strategy_accuracy,
            ).to_tuple()
            now = datetime.now(timezone.utc)

            if supports_managed_transactions(db):
                last_adjustment = get_latest_adjustment_for_update(
                    persisted_user_id=persisted_user_id,
                    db=db,
                )
            else:
                last_adjustment = get_latest_adjustment(user_id=owner_user_id, db=db)
            if (
                last_adjustment
                and _adjustment_get(last_adjustment, "decision_type") == decision_type
                and _adjustment_get(last_adjustment, "applied_at")
            ):
                applied_at_raw = _adjustment_get(last_adjustment, "applied_at")
                applied_at = (
                    datetime.fromisoformat(applied_at_raw)
                    if isinstance(applied_at_raw, str)
                    else applied_at_raw
                )
                if applied_at.tzinfo is None:
                    applied_at = applied_at.replace(tzinfo=timezone.utc)
                if now - applied_at < timedelta(minutes=THRASH_GUARD_MINUTES):
                    return last_adjustment

            if decision_type == "reprioritize_tasks":
                reprioritized = _reprioritize_tasks(user_id=owner_user_id, db=db)
                if reprioritized.get("task_ids"):
                    payload.update(reprioritized)
                    payload["next_action"] = {
                        "type": "reprioritize_tasks",
                        "title": "Continue after reprioritizing the current task queue",
                        "task_ids": reprioritized["task_ids"],
                    }
                else:
                    decision_type = "create_new_task"
                    payload = {
                        "reason": reprioritized.get("reason", "no_incomplete_tasks"),
                        "suggested_goal": "Create one concrete next task to rebuild momentum",
                        "next_action": {
                            "type": "create_new_task",
                            "title": "Create one concrete next task",
                            "suggested_goal": "Create one concrete next task to rebuild momentum",
                        },
                    }
            elif decision_type == "continue_highest_priority_task":
                top_task = _get_top_incomplete_task(user_id=owner_user_id, db=db)
                if top_task:
                    payload["task"] = top_task
                    payload["next_action"] = {
                        "type": "continue_highest_priority_task",
                        "title": f"Continue task: {top_task['name']}",
                        "task_id": top_task["task_id"],
                        "task_name": top_task["name"],
                    }
                else:
                    decision_type = "create_new_task"
                    payload = {
                        "reason": "no_incomplete_tasks",
                        "suggested_goal": "Create the next highest-value task for today",
                        "next_action": {
                            "type": "create_new_task",
                            "title": "Create the next highest-value task",
                            "suggested_goal": "Create the next highest-value task for today",
                        },
                    }

            if not payload.get("next_action"):
                raise RuntimeError("Infinity loop invariant violated: next_action is required")

            expected_outcome, expected_score = _build_expectation(
                decision_type,
                score_snapshot,
                offsets=adapted_offsets,
            )

            adjustment = create_loop_adjustment_record(
                db=db,
                user_id=persisted_user_id,
                trace_id=get_current_trace_id(),
                trigger_event=normalized_trigger,
                score_snapshot=score_snapshot,
                decision_type=decision_type,
                expected_outcome=expected_outcome,
                expected_score=expected_score,
                adjustment_payload={
                    **payload,
                    "feedback_context": feedback_context,
                    "loop_context": loop_context or {},
                    "expected_vs_actual": {
                        "expected_outcome": expected_outcome,
                        "expected_score": expected_score,
                    },
                },
                applied_at=now,
            )
            return adjustment
    except Exception as exc:
        logger.warning("[InfinityLoop] run_loop failed for %s: %s", user_id, exc)
        try:
            emit_error_event(
                db=db,
                error_type="loop",
                message=str(exc),
                user_id=user_id,
                trace_id=get_current_trace_id(),
                payload={"trigger_event": trigger_event},
                required=True,
            )
        except Exception:
            logger.exception("[InfinityLoop] failed to emit required error event for %s", user_id)
        try:
            db.rollback()
        except Exception as rollback_exc:
            emit_observability_event(
                logger,
                event="infinity_loop_rollback_failed",
                user_id=user_id,
                error=str(rollback_exc),
            )
        return None

