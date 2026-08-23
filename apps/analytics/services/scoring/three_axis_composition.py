"""
Three-axis composition — the *advisory* blend (three-axis model, Phase C).

Phase A measured the axes; Phase B shadow-logged them; Phase C is the first phase where the
Worth and Trajectory axes are allowed to *move* the canonical ``master_score`` — but only
when ``AINDY_INFINITY_THREE_AXIS_ADVISORY`` is on (default off), and only within bounded,
reversible weight clamps. The behavioral KPIs remain the anchor (≥ ``BEHAVIORAL_MIN_WEIGHT``
of the composite). See §8 of ``docs/infinity/INFINITY_SCORE_MODEL.md``.

Design decisions this module implements (all locked in §8):
  * **Worth source = declared prior only** — the advisory blend reads Worth from the
    declared-prior score (`compute_worth`); realized revenue stays observability-only.
  * **Volume consolidation** — `consolidate_volume` / `consolidated_weight_view` express how
    the three completion KPIs collapse into a single Volume axis. In Phase C this is the
    *tested migration path* surfaced for interpretability; it does not yet re-shape the
    persisted schema (that is Phase D). The advisory blend adds only Worth + Trajectory on
    top of the behavioral anchor, which already embodies volume via its completion KPIs — so
    completion is never double-counted.
  * **Conservative initial worth weight** — ~12% worth / ~8% trajectory by default,
    soak-tunable via env, so behavioral stays ≥ 80%.

**Graceful degradation is the crux.** Early deployments have no worth declarations and few
estimated tasks, so an axis often has *no data*. A naive blend would drag such a user's score
toward zero. Instead, a missing axis returns its reserved weight to the behavioral anchor —
a user with neither Worth nor Trajectory data scores exactly as they do today. The axes can
only *add* signal, never silently penalize its absence.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ── Flag ──────────────────────────────────────────────────────────────────────
ADVISORY_FLAG = "AINDY_INFINITY_THREE_AXIS_ADVISORY"
_TRUTHY = {"1", "true", "yes", "on"}

# ── Conservative initial weights (decision §8.4) ──────────────────────────────
# Reserved for the two new axes; the behavioral anchor keeps the remainder (≥ 0.80).
# Soak-tunable via env so the flip can be calibrated from real shadow divergence data
# without a code change — but the anchor floor is enforced regardless (see _reserved_weights).
DEFAULT_WORTH_WEIGHT = 0.12
DEFAULT_TRAJECTORY_WEIGHT = 0.08
BEHAVIORAL_MIN_WEIGHT = 0.80   # behavioral KPIs remain the anchor — hard floor
WORTH_WEIGHT_ENV = "AINDY_INFINITY_WORTH_WEIGHT"
TRAJECTORY_WEIGHT_ENV = "AINDY_INFINITY_TRAJECTORY_WEIGHT"

# The three completion-flavored KPIs that consolidate into Volume (decision §8.2).
_VOLUME_SOURCE_KPIS = ("execution_speed", "decision_efficiency", "masterplan_progress")
# The behavioral KPIs that survive consolidation unchanged.
_SURVIVING_KPIS = ("focus_quality", "ai_productivity_boost")


def advisory_enabled() -> bool:
    """Whether the advisory blend moves master_score on each score event (default off)."""
    return os.environ.get(ADVISORY_FLAG, "").strip().lower() in _TRUTHY


def _env_weight(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        val = float(raw)
    except (TypeError, ValueError):
        logger.debug("[three_axis] bad %s=%r; using default %s", name, raw, default)
        return default
    return max(0.0, val)


def _reserved_weights() -> tuple[float, float]:
    """(worth_weight, trajectory_weight), env-tunable but clamped so behavioral stays anchor.

    If the two configured weights would leave the behavioral anchor below
    ``BEHAVIORAL_MIN_WEIGHT``, they are scaled down proportionally — the anchor floor wins.
    """
    w = _env_weight(WORTH_WEIGHT_ENV, DEFAULT_WORTH_WEIGHT)
    t = _env_weight(TRAJECTORY_WEIGHT_ENV, DEFAULT_TRAJECTORY_WEIGHT)
    reserved = w + t
    max_reserved = 1.0 - BEHAVIORAL_MIN_WEIGHT
    if reserved > max_reserved and reserved > 0:
        scale = max_reserved / reserved
        w, t = w * scale, t * scale
    return round(w, 6), round(t, 6)


def compose_advisory_master(
    behavioral_master: float,
    *,
    worth_score: float | None,
    trajectory_score: float | None,
    worth_available: bool,
    trajectory_available: bool,
) -> dict[str, Any]:
    """Blend Worth + Trajectory onto the behavioral anchor, renormalizing over *available*
    axes so a missing axis never drags the score.

    Returns the advisory master plus a full breakdown (weights actually applied, which axes
    contributed, the behavioral anchor weight). When neither axis has data, ``advisory_master``
    equals ``behavioral_master`` exactly.
    """
    base = float(behavioral_master or 0.0)
    w_worth, w_traj = _reserved_weights()

    applied_worth = w_worth if (worth_available and worth_score is not None) else 0.0
    applied_traj = w_traj if (trajectory_available and trajectory_score is not None) else 0.0
    reserved = applied_worth + applied_traj
    anchor_weight = 1.0 - reserved  # missing axes return their weight to the anchor

    advisory = anchor_weight * base
    if applied_worth:
        advisory += applied_worth * float(worth_score)
    if applied_traj:
        advisory += applied_traj * float(trajectory_score)
    advisory = max(0.0, min(100.0, round(advisory, 2)))

    return {
        "advisory_master": advisory,
        "behavioral_master": round(base, 2),
        "delta": round(advisory - base, 2),
        "anchor_weight": round(anchor_weight, 6),
        "applied_worth_weight": round(applied_worth, 6),
        "applied_trajectory_weight": round(applied_traj, 6),
        "worth_contributed": bool(applied_worth),
        "trajectory_contributed": bool(applied_traj),
    }


def consolidate_volume(behavioral_kpis: dict[str, float]) -> float:
    """Collapse the three completion KPIs into a single Volume value (decision §8.2).

    Phase C migration-path math: Volume is the mean of the completion-flavored behavioral
    KPIs the persisted score already tracks. (masterplan_progress carries a small trajectory
    component; that is acknowledged and resolved when Trajectory becomes first-class in
    Phase D — here it is an interpretability approximation, not the driving value.)
    """
    vals = [float(behavioral_kpis.get(k) or 0.0) for k in _VOLUME_SOURCE_KPIS]
    return round(sum(vals) / len(vals), 2) if vals else 0.0


def consolidated_weight_view(effective_weights: dict[str, float]) -> dict[str, float]:
    """Map the 5 behavioral KPI weights → the consolidated axis weights (the Phase-D
    migration path), summing to 1.0.

    The three completion-KPI weights fold into a single ``volume`` weight; ``focus_quality``
    and ``ai_productivity_boost`` survive; ``worth`` and ``trajectory`` take the reserved
    weights. The behavioral portion is renormalized to fill the anchor share so the whole
    view still sums to 1.0 — this is exactly the reweighting Phase D would persist.
    """
    w_worth, w_traj = _reserved_weights()
    anchor_share = 1.0 - (w_worth + w_traj)

    volume_w = sum(float(effective_weights.get(k) or 0.0) for k in _VOLUME_SOURCE_KPIS)
    survivors = {k: float(effective_weights.get(k) or 0.0) for k in _SURVIVING_KPIS}
    behavioral_total = volume_w + sum(survivors.values())

    if behavioral_total <= 0:
        # Degenerate input — split the anchor share evenly across the surviving axes.
        n = 1 + len(_SURVIVING_KPIS)
        even = anchor_share / n
        view = {"volume": even, **{k: even for k in _SURVIVING_KPIS}}
    else:
        scale = anchor_share / behavioral_total
        view = {"volume": volume_w * scale, **{k: v * scale for k, v in survivors.items()}}

    view["worth"] = w_worth
    view["trajectory"] = w_traj
    view = {k: round(v, 6) for k, v in view.items()}

    # Absorb any rounding residual into volume so the view sums to exactly 1.0.
    residual = round(1.0 - sum(view.values()), 6)
    if residual:
        view["volume"] = round(view["volume"] + residual, 6)
    return view


def compute_advisory_breakdown(
    db: Session,
    user_id,
    *,
    behavioral_master: float,
    behavioral_kpis: dict[str, float],
    effective_weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """The full advisory object: the blended master + every input that produced it.

    Reads Worth (declared prior) and Trajectory (padding-guarded) via the three-axis service,
    composes the advisory master, and attaches the consolidated Volume view for
    interpretability. Pure computation — never writes the score.
    """
    from apps.analytics.services.scoring.three_axis_service import (
        compute_trajectory,
        compute_worth,
    )

    worth = compute_worth(db, user_id)
    trajectory = compute_trajectory(db, user_id)

    worth_available = bool(worth.get("declaration_count"))  # declared prior exists
    trajectory_available = trajectory.get("score") is not None

    composition = compose_advisory_master(
        behavioral_master,
        worth_score=worth.get("score"),
        trajectory_score=trajectory.get("score"),
        worth_available=worth_available,
        trajectory_available=trajectory_available,
    )
    breakdown: dict[str, Any] = {
        **composition,
        "worth": worth,
        "trajectory": trajectory,
        "consolidated_volume": consolidate_volume(behavioral_kpis),
        "flag": ADVISORY_FLAG,
    }
    if effective_weights is not None:
        breakdown["consolidated_weight_view"] = consolidated_weight_view(effective_weights)
    return breakdown


def preview_advisory(db: Session, user_id) -> dict[str, Any]:
    """Read-only preview of what the advisory blend *would* produce for a user, from their
    current behavioral KPIs — regardless of whether the flag is on. Never writes the score.

    The behavioral anchor is reconstructed from the persisted behavioral KPI columns ×
    effective weights (those columns are always behavioral, even once the flag flips), so the
    preview is a true "advisory vs. behavioral" comparison operators can read before flipping.
    """
    from apps.analytics.services.scoring.infinity_service import get_user_kpi_snapshot
    from apps.analytics.services.scoring.kpi_weight_service import get_effective_weights

    snapshot = get_user_kpi_snapshot(str(user_id), db)
    if not snapshot:
        return {"available": False, "reason": "no_score_yet", "flag_enabled": advisory_enabled()}

    kpis = {
        "execution_speed": float(snapshot.get("execution_speed") or 0.0),
        "decision_efficiency": float(snapshot.get("decision_efficiency") or 0.0),
        "ai_productivity_boost": float(snapshot.get("ai_productivity_boost") or 0.0),
        "focus_quality": float(snapshot.get("focus_quality") or 0.0),
        "masterplan_progress": float(snapshot.get("masterplan_progress") or 0.0),
    }
    weights = get_effective_weights(db, user_id)
    behavioral_master = round(sum(kpis[k] * float(weights.get(k) or 0.0) for k in kpis), 2)

    breakdown = compute_advisory_breakdown(
        db, user_id,
        behavioral_master=behavioral_master,
        behavioral_kpis=kpis,
        effective_weights=weights,
    )
    return {
        "available": True,
        "flag_enabled": advisory_enabled(),
        "persisted_master_score": snapshot.get("master_score"),
        **breakdown,
    }
