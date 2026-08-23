"""
Three-axis Infinity score — observability snapshot (Phase A).

Computes Volume / Worth / Trajectory *alongside* the canonical `master_score`, for
observation only. It **never** writes `master_score` or feeds `calculate_infinity_score`
— the whole point of Phase A is to make the three axes visible before any decision to let
them drive scoring (see `docs/infinity/INFINITY_SCORE_MODEL.md`).

Reads through the same boundaries the existing KPI scorers use — the
``sys.v1.task.get_user_tasks`` snapshot and the analytics ``dependency_adapter`` pillar
syscalls — so there are no cross-app imports.

Axes (all data-sourced):
  * **Volume**     — effort-weighted work completed (consolidates the 3 completion KPIs).
  * **Trajectory** — estimate-vs-actual pace (task ``duration`` est-hours vs ``time_spent``
                     actual-seconds); on-time is neutral.
  * **Worth**      — declared prior (`IntentValueDeclaration`) + realized revenue (the
                     freelance pillar). Presented as components; realized $ and declared
                     units are *not* fake-combined.

Normalization constants are deliberately explicit and tunable — Phase A is measurement, so
raw components are surfaced next to each score.
"""
from __future__ import annotations

import logging
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from AINDY.platform_layer.user_ids import parse_user_id

logger = logging.getLogger(__name__)

# --- tunable normalization (Phase A: measurement; expose raw alongside) ---
VOLUME_WINDOW_DAYS = 14
VOLUME_EFFORT_SCALE = 40.0     # effort-hours in window → ~63 (saturating); 80h → ~86
TRAJECTORY_RATIO_CAP = 2.0     # 2× faster than estimate = max; 2× slower ≈ 25
WORTH_DECLARED_SCALE = 100.0   # declared-units → provisional 0..100 (saturating)

# --- Trajectory anti-gaming guard (Phase C, decision §8.3) ---
# The gaming vector is estimate *padding*: since trajectory ∝ estimated/actual, inflating
# every estimate makes every task finish "ahead" and pins the axis at 100. The per-task
# ratio is already capped (TRAJECTORY_RATIO_CAP), so the realistic exploit is chronic,
# across-the-board over-estimation. The guard dampens the ahead-of-plan *excess* (the part
# above the neutral 50) when the ahead-signature is both pervasive (most tasks ahead) and
# strong (mean ratio well above 1). A genuinely fast-but-variable worker — some tasks
# behind, some on-time — trips neither condition and is not penalized.
PAD_GUARD_MIN_TASKS = 5        # need a real sample before judging "chronic"
PAD_GUARD_AHEAD_FRACTION = 0.80  # >80% of tasks ahead starts to look systematic
PAD_GUARD_RATIO_REF = 1.6      # mean ratio at/above which the padding penalty is full-strength
PAD_GUARD_MAX_PENALTY = 0.5    # at most halve the ahead-of-plan excess


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_end_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _get_tasks(db: Session, user_id) -> list[dict]:
    """Task snapshot via the runtime task read-syscall (status/end_time/duration/time_spent)."""
    from apps.analytics.services.scoring.infinity_service import _get_user_tasks_for_scoring

    try:
        return _get_user_tasks_for_scoring(str(user_id), db) or []
    except Exception as exc:  # pragma: no cover - degradable
        logger.debug("[three_axis] task snapshot unavailable: %s", exc)
        return []


def compute_volume(db: Session, user_id) -> dict[str, Any]:
    """Effort-weighted work completed in the recent window — the consolidated throughput axis."""
    uid = parse_user_id(user_id)
    if uid is None:
        return {"score": None, "reason": "no_user"}
    since = _now() - timedelta(days=VOLUME_WINDOW_DAYS)
    completed = [t for t in _get_tasks(db, user_id) if t.get("status") == "completed"]
    recent = [
        t for t in completed
        if (_parse_end_time(t.get("end_time")) is None) or (_parse_end_time(t.get("end_time")) >= since)
    ]
    effort = round(sum(float(t.get("duration") or 0.0) for t in recent), 2)  # duration = est hours
    score = _clamp(100.0 * (1.0 - math.exp(-effort / VOLUME_EFFORT_SCALE))) if effort > 0 else 0.0
    return {
        "score": round(score, 2),
        "completed_count": len(recent),
        "effort_hours": effort,
        "window_days": VOLUME_WINDOW_DAYS,
    }


def compute_trajectory(db: Session, user_id) -> dict[str, Any]:
    """Estimate-vs-actual pace over completed tasks with both an estimate and actual time."""
    uid = parse_user_id(user_id)
    if uid is None:
        return {"score": None, "reason": "no_user"}
    ratios: list[float] = []
    ahead = behind = on_time = 0
    for t in _get_tasks(db, user_id):
        if t.get("status") != "completed":
            continue
        est_hours = float(t.get("duration") or 0.0)             # estimated hours
        actual_hours = float(t.get("time_spent") or 0.0) / 3600.0  # time_spent is SECONDS
        if est_hours <= 0 or actual_hours <= 0:
            continue
        ratio = min(TRAJECTORY_RATIO_CAP, est_hours / actual_hours)  # >1 faster than estimate
        ratios.append(ratio)
        if actual_hours < est_hours * 0.95:
            ahead += 1
        elif actual_hours > est_hours * 1.05:
            behind += 1
        else:
            on_time += 1
    measured = len(ratios)
    if measured == 0:
        return {"score": None, "reason": "no_estimated_completed_tasks", "tasks_measured": 0}
    mean_ratio = sum(ratios) / measured
    # ratio 1.0 (on estimate) → 50 (neutral); 2.0 → 100 (twice as fast); 0.5 → 25.
    raw_score = _clamp(50.0 * mean_ratio)
    ahead_fraction = ahead / measured
    guarded_score, penalty = _apply_padding_guard(raw_score, measured, ahead_fraction, mean_ratio)
    return {
        "score": round(guarded_score, 2),
        "raw_score": round(raw_score, 2),          # pre-guard, for interpretability
        "padding_penalty": round(penalty, 3),      # 0 = untouched; up to PAD_GUARD_MAX_PENALTY
        "tasks_measured": measured,
        "mean_pace_ratio": round(mean_ratio, 3),
        "ahead": ahead,
        "on_time": on_time,
        "behind": behind,
    }


def _apply_padding_guard(
    raw_score: float, measured: int, ahead_fraction: float, mean_ratio: float
) -> tuple[float, float]:
    """Dampen the ahead-of-plan excess when the ahead-signature looks like chronic estimate
    padding (see the PAD_GUARD_* constants). Returns (guarded_score, penalty_fraction).

    Penalty is smooth (no cliff) in *both* how pervasive the ahead-fraction is and how strong
    the mean ratio is, so a user just over the thresholds is nudged, not slammed. Only the
    excess above the neutral 50 is dampened — being behind or on-time is never touched.
    """
    excess = raw_score - 50.0
    if measured < PAD_GUARD_MIN_TASKS or excess <= 0 or mean_ratio <= 1.0:
        return raw_score, 0.0
    pervasiveness = max(0.0, ahead_fraction - PAD_GUARD_AHEAD_FRACTION) / (1.0 - PAD_GUARD_AHEAD_FRACTION)
    strength = _clamp((mean_ratio - 1.0) / (PAD_GUARD_RATIO_REF - 1.0), 0.0, 1.0)
    penalty = PAD_GUARD_MAX_PENALTY * pervasiveness * strength
    if penalty <= 0:
        return raw_score, 0.0
    return 50.0 + excess * (1.0 - penalty), penalty


def compute_worth(db: Session, user_id) -> dict[str, Any]:
    """Declared prior + realized revenue. Components are kept separate (units differ)."""
    from apps.analytics.services.scoring.value_declaration_service import declared_worth_summary

    declared = declared_worth_summary(db, user_id)
    realized_revenue = _realized_revenue(db, user_id)
    declared_total = float(declared.get("total") or 0.0)
    provisional = _clamp(100.0 * (1.0 - math.exp(-declared_total / WORTH_DECLARED_SCALE))) if declared_total > 0 else 0.0
    return {
        "score": round(provisional, 2),           # provisional — from declared prior only
        "declared_total": declared.get("total", 0.0),
        "declared_by_kind": declared.get("by_kind", {}),
        "declaration_count": declared.get("count", 0),
        "realized_revenue": realized_revenue,     # raw $, NOT folded into score in Phase A
        "note": "provisional score reflects declared worth only; realized_revenue is shown raw",
    }


def _realized_revenue(db: Session, user_id) -> float:
    """Realized revenue via the analytics pillar adapter (freelance get_performance_signals syscall)."""
    try:
        from apps.analytics.services.integration.dependency_adapter import (
            fetch_freelance_performance_signals,
        )

        signals = fetch_freelance_performance_signals(user_id=str(user_id)) or []
        return round(sum(float(s.get("realized_revenue") or 0.0) for s in signals), 2)
    except Exception as exc:  # pragma: no cover - degradable
        logger.debug("[three_axis] realized revenue unavailable: %s", exc)
        return 0.0


def compute_three_axes(db: Session, user_id) -> dict[str, Any]:
    """The observability snapshot: Volume / Worth / Trajectory + the (unchanged) master_score.

    Reads `master_score` for reference only — this function never writes it.
    """
    from apps.analytics.services.scoring.infinity_service import get_user_kpi_snapshot

    snapshot = get_user_kpi_snapshot(str(user_id), db) or {}
    return {
        "user_id": str(user_id),
        "volume": compute_volume(db, user_id),
        "worth": compute_worth(db, user_id),
        "trajectory": compute_trajectory(db, user_id),
        "master_score": snapshot.get("master_score"),   # reference, unchanged
        "observability_only": True,
        "note": "Phase A: axes are computed for observation and do NOT drive master_score.",
    }


# ── Phase B: shadow logging (flag-gated, drives nothing) ──────────────────────

THREE_AXIS_SHADOW_FLAG = "AINDY_INFINITY_THREE_AXIS_SHADOW"
_TRUTHY = {"1", "true", "yes", "on"}


def three_axis_shadow_enabled() -> bool:
    """Whether the three-axis shadow ledger records on each score event (default off)."""
    return os.environ.get(THREE_AXIS_SHADOW_FLAG, "").strip().lower() in _TRUTHY


def shadow_log_three_axes(db: Session, *, user_id, master_score=None, trigger_event=None) -> bool:
    """Record the three axes next to ``master_score`` in the shadow ledger.

    No-op when the flag is off; non-fatal on any error (must never break scoring). Takes
    ``master_score`` directly (not a re-read) so it is safe to call mid score-persist.
    """
    if not three_axis_shadow_enabled():
        return False
    try:
        from apps.analytics.three_axis_shadow import ThreeAxisShadowRecord

        uid = parse_user_id(user_id)
        if uid is None:
            return False
        volume = compute_volume(db, user_id)
        worth = compute_worth(db, user_id)
        trajectory = compute_trajectory(db, user_id)
        row = ThreeAxisShadowRecord(
            user_id=uid,
            master_score=(float(master_score) if master_score is not None else None),
            volume_score=volume.get("score"),
            worth_score=worth.get("score"),
            trajectory_score=trajectory.get("score"),
            effort_hours=volume.get("effort_hours"),
            completed_count=volume.get("completed_count"),
            declared_total=worth.get("declared_total"),
            realized_revenue=worth.get("realized_revenue"),
            mean_pace_ratio=trajectory.get("mean_pace_ratio"),
            trigger_event=trigger_event,
        )
        db.add(row)
        db.flush()
        return True
    except Exception as exc:  # pragma: no cover - defensive; scoring must not break
        logger.warning("[three_axis] shadow log failed (non-fatal): %s", exc)
        return False


def three_axis_shadow_report(db: Session, *, user_id=None, limit: int = 50) -> dict[str, Any]:
    """Soak report: recent shadow records + mean axis scores next to master (the divergence signal)."""
    from apps.analytics.three_axis_shadow import ThreeAxisShadowRecord

    q = db.query(ThreeAxisShadowRecord)
    if user_id is not None:
        uid = parse_user_id(user_id)
        if uid is None:
            return {"records": [], "summary": {}, "count": 0, "shadow_enabled": three_axis_shadow_enabled()}
        q = q.filter(ThreeAxisShadowRecord.user_id == uid)
    rows = q.order_by(ThreeAxisShadowRecord.created_at.desc()).limit(max(1, min(int(limit or 50), 500))).all()

    def _mean(vals):
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    summary = {
        "master_score": _mean([r.master_score for r in rows]),
        "volume": _mean([r.volume_score for r in rows]),
        "worth": _mean([r.worth_score for r in rows]),
        "trajectory": _mean([r.trajectory_score for r in rows]),
    }
    records = [
        {
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "master_score": r.master_score,
            "volume_score": r.volume_score,
            "worth_score": r.worth_score,
            "trajectory_score": r.trajectory_score,
            "effort_hours": r.effort_hours,
            "declared_total": r.declared_total,
            "realized_revenue": r.realized_revenue,
            "mean_pace_ratio": r.mean_pace_ratio,
            "trigger_event": r.trigger_event,
        }
        for r in rows
    ]
    return {
        "records": records,
        "summary": summary,
        "count": len(rows),
        "shadow_enabled": three_axis_shadow_enabled(),
    }
