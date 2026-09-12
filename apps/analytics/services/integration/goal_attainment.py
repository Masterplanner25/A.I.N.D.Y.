"""Goal attainment — resolve a plan's declared goal against real domain signals.

A MasterPlan can declare a destination (``goal_value`` + ``goal_unit``) but has no
counterpart column for distance travelled — ``goal_value`` is write-only, set by the
anchor route and echoed back on read, never compared to anything. So the only things
that move ``masterplan_progress`` today are task completion and elapsed time: activity,
not achievement.

This module resolves the declared goal against signals the domains already compute,
**on read** — no new column, no write path to keep in sync, no migration. Resolution
goes over syscalls (mirroring ``dependency_adapter``) rather than cross-app imports, so
no ``APP_DEPENDS_ON`` edge is added.

Phase 0 (this module): resolver + unit registry + the ``tasks`` unit, which is the only
one answerable with an existing syscall. Not wired into scoring — exposed read-only at
``GET /apps/analytics/goal-attainment`` so it can be inspected before it influences
anything. See ``docs/specs/MASTERPLAN_GOAL_ATTAINMENT_SPEC.md``.

Contract note: every failure mode returns an *unresolved* result rather than raising.
An unsupported unit is a normal answer, not an error — the caller must be able to fall
back to the existing formula without a try/except.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from AINDY.kernel.syscall_dispatcher import get_dispatcher, make_syscall_ctx_from_tool
from AINDY.platform_layer.registry import get_symbol

logger = logging.getLogger(__name__)


# Canonical unit -> the aliases a user might type into the anchor form. Normalization is
# case-insensitive and whitespace-stripped; anything unrecognised stays as-is and simply
# resolves to unsupported.
UNIT_ALIASES: dict[str, str] = {
    "task": "tasks",
    "tasks": "tasks",
    "completed_tasks": "tasks",
    # Registered but not yet resolvable — Phase 1 adds the syscalls behind these.
    "usd": "usd",
    "$": "usd",
    "dollar": "usd",
    "dollars": "usd",
    "revenue": "usd",
    "impression": "impressions",
    "impressions": "impressions",
    "click": "clicks",
    "clicks": "clicks",
    "post": "posts",
    "posts": "posts",
    "playbook": "playbooks",
    "playbooks": "playbooks",
    "book": "books",
    "books": "books",
}


def normalize_unit(goal_unit: Any) -> str | None:
    """Fold a user-entered unit onto its canonical form. ``None`` when unusable."""
    if not isinstance(goal_unit, str):
        return None
    cleaned = goal_unit.strip().lower()
    if not cleaned:
        return None
    return UNIT_ALIASES.get(cleaned, cleaned)


def _dispatch(name: str, payload: dict[str, Any], *, user_id: str, capability: str, db=None) -> dict[str, Any]:
    """Dispatch a syscall, returning ``{}`` on any non-success. Never raises."""
    ctx = make_syscall_ctx_from_tool(str(user_id or ""), capabilities=[capability])
    if db is not None:
        ctx.metadata["_db"] = db
    result = get_dispatcher().dispatch(name, payload, ctx)
    if result.get("status") != "success":
        return {}
    return result.get("data") or {}


# ── Per-unit resolvers ────────────────────────────────────────────────────────
# Each returns a float (the cumulative-to-date value) or None when it cannot answer.
# Phase 0 registers only `tasks`; the others land in Phase 1 behind
# sys.v1.<domain>.get_goal_metric, which does not exist yet.


def _resolve_tasks(db, *, user_id: str, masterplan_id: Any, _unit: str = "tasks") -> float | None:
    """Completed tasks for this plan, via the existing task syscall.

    Scoped to the plan rather than the user: a plan's goal is about that plan's work.
    Unlike the freelance/social resolvers this predates the uniform ``get_goal_metric``
    contract and reuses ``sys.v1.task.list_for_masterplan``; ``_unit`` is accepted only
    to keep every resolver's signature identical.
    """
    if masterplan_id is None:
        return None
    data = _dispatch(
        "sys.v1.task.list_for_masterplan",
        {"masterplan_id": int(masterplan_id), "user_id": str(user_id)},
        user_id=str(user_id),
        capability="task.read",
        db=db,
    )
    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        return None
    return float(sum(1 for task in tasks if (task or {}).get("status") == "completed"))


def _resolve_via_goal_metric(domain: str, capability: str) -> Callable[..., float | None]:
    """Build a resolver over the uniform ``sys.v1.<domain>.get_goal_metric`` contract.

    A domain answering ``supported: False`` (unknown unit, or degraded — Mongo down for
    social, say) yields ``None``, which surfaces as an unresolved attainment rather than
    a misleading 0. Scoring against a phantom zero would be worse than not scoring.
    """

    def _resolver(db, *, user_id: str, masterplan_id: Any, _unit: str) -> float | None:
        data = _dispatch(
            f"sys.v1.{domain}.get_goal_metric",
            {"unit": _unit, "user_id": str(user_id), "masterplan_id": masterplan_id},
            user_id=str(user_id),
            capability=capability,
            db=db,
        )
        if not data.get("supported"):
            return None
        value = data.get("value")
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    return _resolver


_freelance_metric = _resolve_via_goal_metric("freelance", "freelance.read")
_social_metric = _resolve_via_goal_metric("social", "social.read")
_rippletrace_metric = _resolve_via_goal_metric("rippletrace", "rippletrace.read")


_RESOLVERS: dict[str, Callable[..., float | None]] = {
    "tasks": _resolve_tasks,
    "usd": _freelance_metric,
    "impressions": _social_metric,
    "clicks": _social_metric,
    "posts": _social_metric,
    # Answerable only since rippletrace gained a data supply — the table was empty
    # before, so this unit resolved to `unsupported_unit`. Note rippletrace reports
    # `scope: "global"` for it: playbooks carry no owner, because the strategies they
    # derive from are built across all drop points without a user filter.
    "playbooks": _rippletrace_metric,
}


def supported_units() -> list[str]:
    """Canonical units resolvable today. Grows as Phase 1 syscalls land."""
    return sorted(_RESOLVERS)


# ── Public entry point ────────────────────────────────────────────────────────


def unresolved(reason: str, *, unit: str | None = None, goal_value: float | None = None) -> dict[str, Any]:
    """The shape every failure path returns. `supported=False` means: use the fallback."""
    return {
        "supported": False,
        "reason": reason,
        "unit": unit,
        "goal_value": goal_value,
        "value": None,
        "attainment_pct": None,
        "raw_ratio": None,
    }


def resolve_goal_attainment(
    db,
    *,
    user_id: str,
    goal_unit: Any,
    goal_value: Any,
    masterplan_id: Any = None,
) -> dict[str, Any]:
    """Resolve declared goal -> achieved value -> attainment fraction.

    Returns ``supported: False`` (never raises) when the goal is undeclared, the target
    is non-positive, the unit has no resolver, or the underlying domain cannot answer.

    ``attainment_pct`` is clamped to 1.0 so overachievement cannot inflate a score past
    its ceiling; ``raw_ratio`` carries the unclamped value for observability.
    """
    unit = normalize_unit(goal_unit)
    if unit is None:
        return unresolved("no_goal_unit")

    try:
        target = float(goal_value)
    except (TypeError, ValueError):
        return unresolved("no_goal_value", unit=unit)
    if target <= 0:
        # A zero or negative target makes the ratio meaningless (and is a divide-by-zero).
        return unresolved("non_positive_goal_value", unit=unit, goal_value=target)

    resolver = _RESOLVERS.get(unit)
    if resolver is None:
        return unresolved("unsupported_unit", unit=unit, goal_value=target)

    try:
        value = resolver(db, user_id=str(user_id), masterplan_id=masterplan_id, _unit=unit)
    except Exception as exc:
        # A degraded domain must never break scoring — fall back, don't propagate.
        logger.warning("[GoalAttainment] resolver for unit %r failed: %s", unit, exc)
        return unresolved("resolver_failed", unit=unit, goal_value=target)

    if value is None:
        return unresolved("no_value", unit=unit, goal_value=target)

    raw_ratio = value / target
    return {
        "supported": True,
        "reason": None,
        "unit": unit,
        "goal_value": target,
        "value": float(value),
        "attainment_pct": min(1.0, raw_ratio),
        "raw_ratio": raw_ratio,
    }


def resolve_for_active_plan(db, user_id: str) -> dict[str, Any]:
    """Resolve attainment for the user's active plan.

    Reads MasterPlan through the registry (``get_symbol``) exactly as
    ``calculate_masterplan_progress`` does, so this stays inside the analytics domain
    and adds no cross-app import.
    """
    MasterPlan = get_symbol("MasterPlan")
    if MasterPlan is None:
        return unresolved("masterplan_model_unavailable")

    try:
        plan = (
            db.query(MasterPlan)
            .filter(MasterPlan.user_id == user_id, MasterPlan.is_active.is_(True))
            .first()
        )
    except Exception as exc:
        logger.warning("[GoalAttainment] active plan lookup failed: %s", exc)
        return unresolved("plan_lookup_failed")

    if plan is None:
        return unresolved("no_active_plan")

    result = resolve_goal_attainment(
        db,
        user_id=user_id,
        goal_unit=plan.goal_unit,
        goal_value=plan.goal_value,
        masterplan_id=plan.id,
    )
    result["masterplan_id"] = plan.id
    result["goal_description"] = plan.goal_description
    return result


# ── ★ Attribution-based attainment, and the shadow (§6 Phase 2) ─────────────────────────────────────
#
# §4b said WCU could measure THAT you worked, never that you worked ON THIS, because a task
# carried a plan and nothing else. `STRATEGY_LAYER_SPEC` §5b built the chain (#333, #335), and
# masterplan now answers `sys.v1.masterplan.get_objective_attainment`: hours completed against
# each objective, and a plan figure weighted over housed work. This is that answer, read by
# syscall, blended by the §5 formula, and RECORDED — never applied. Owner, 2026-09-11: "yes, as
# a shadow first."

SHADOW_FLAG = "AINDY_MASTERPLAN_GOAL_ATTAINMENT_SHADOW"
LIVE_FLAG = "AINDY_MASTERPLAN_GOAL_ATTAINMENT"
_TRUTHY = {"1", "true", "yes", "on"}

# §5 weights. A starting value, not a derived one (§7 is the open calibration question).
ATTAINMENT_WEIGHT = 0.40
COMPLETION_WEIGHT = 0.35
SCHEDULE_WEIGHT = 0.25


def shadow_enabled() -> bool:
    """Record the blend next to the live score. Default ON: recording changes no score, and a
    shadow nobody records cannot end a soak. Set the flag to 0 to stop recording."""
    import os

    raw = os.environ.get(SHADOW_FLAG)
    if raw is None or not raw.strip():
        return True
    return raw.strip().lower() in _TRUTHY


def live_enabled() -> bool:
    """Let the blend BE the score. Default OFF, and stays off until the shadow ledger says
    something. This is the flip; it is not this PR's to make."""
    import os

    return (os.environ.get(LIVE_FLAG) or "").strip().lower() in _TRUTHY


def resolve_objective_attainment(db, *, user_id: str, masterplan_id: Any = None) -> dict[str, Any]:
    """Work done against each objective, from masterplan by syscall. Never raises.

    `supported: False` when the plan has no objectives (or the syscall failed — logged by the
    dispatcher's own path or by `_dispatch`, and reported here as unsupported rather than as
    zero attainment).
    """
    payload: dict[str, Any] = {"user_id": str(user_id)}
    if masterplan_id is not None:
        payload["masterplan_id"] = str(masterplan_id)
    try:
        data = _dispatch(
            "sys.v1.masterplan.get_objective_attainment", payload,
            user_id=str(user_id), capability="masterplan.read", db=db,
        )
    except Exception as exc:  # pragma: no cover - defensive; scoring must not break
        logger.warning("[GoalAttainment] objective attainment failed: %s", exc)
        return {"supported": False, "reason": "syscall_failed"}
    if not data or not data.get("supported"):
        return {"supported": False, "reason": "no_objectives", **({k: v for k, v in data.items() if k != "supported"})}
    return data


def blend_with_attainment(
    *, completion_pct: float, schedule_score: float, attainment_pct: float | None
) -> float:
    """The §5 formula. With no measurable attainment it collapses to the live formula — the
    fallback is total, by construction rather than by branch."""
    if attainment_pct is None:
        return round(min(100.0, completion_pct * 100 * 0.6 + schedule_score * 0.4), 2)
    score = (
        min(1.0, float(attainment_pct)) * 100 * ATTAINMENT_WEIGHT
        + completion_pct * 100 * COMPLETION_WEIGHT
        + schedule_score * SCHEDULE_WEIGHT
    )
    return round(min(100.0, score), 2)


def shadow_log_attainment(
    db, *, user_id, live_score: float, completion_pct: float, schedule_score: float,
    masterplan_id: Any = None, trigger_event: str | None = None,
) -> dict[str, Any] | None:
    """Record the blend next to the live score. No-op when the flag is off; non-fatal always.

    Returns the row's inputs (for the caller's own reporting) or None.
    """
    if not shadow_enabled():
        return None
    try:
        from AINDY.platform_layer.user_ids import parse_user_id
        from apps.analytics.goal_attainment_shadow import GoalAttainmentShadowRecord

        uid = parse_user_id(user_id)
        if uid is None:
            return None
        att = resolve_objective_attainment(db, user_id=str(user_id), masterplan_id=masterplan_id)
        plan = att.get("plan") or {}
        attainment_pct = plan.get("attainment_pct") if att.get("supported") else None
        shadow = blend_with_attainment(
            completion_pct=completion_pct, schedule_score=schedule_score, attainment_pct=attainment_pct,
        )
        row = GoalAttainmentShadowRecord(
            user_id=uid,
            masterplan_id=att.get("masterplan_id") or (int(masterplan_id) if masterplan_id is not None else None),
            live_score=float(live_score),
            shadow_score=shadow,
            attainment_pct=attainment_pct,
            completion_pct=completion_pct,
            schedule_score=schedule_score,
            hours_completed=plan.get("hours_completed"),
            hours_total=plan.get("hours_total"),
            objectives_measured=plan.get("objectives_measured"),
            objectives=att.get("objectives") or None,
            trigger_event=trigger_event,
        )
        db.add(row)
        db.flush()
        return {"live_score": float(live_score), "shadow_score": shadow, "attainment_pct": attainment_pct}
    except Exception as exc:  # pragma: no cover - defensive; scoring must not break
        logger.warning("[GoalAttainment] shadow log failed (non-fatal): %s", exc)
        return None


def attainment_shadow_report(db, *, user_id=None, limit: int = 50) -> dict[str, Any]:
    """Soak report: recent rows and the divergence signal — mean(shadow - live) over rows where
    attainment was measurable. A mean near zero says attainment would not have changed the
    score; a consistent sign says which way it pulls."""
    from AINDY.platform_layer.user_ids import parse_user_id
    from apps.analytics.goal_attainment_shadow import GoalAttainmentShadowRecord

    q = db.query(GoalAttainmentShadowRecord)
    if user_id is not None:
        uid = parse_user_id(user_id)
        if uid is not None:
            q = q.filter(GoalAttainmentShadowRecord.user_id == uid)
    rows = q.order_by(GoalAttainmentShadowRecord.created_at.desc()).limit(int(limit)).all()
    measured = [r for r in rows if r.attainment_pct is not None and r.live_score is not None]
    divergence = (
        round(sum(r.shadow_score - r.live_score for r in measured) / len(measured), 2)
        if measured else None
    )
    return {
        "shadow_enabled": shadow_enabled(),
        "live_enabled": live_enabled(),
        "count": len(rows),
        "measured": len(measured),
        "mean_divergence": divergence,
        "records": [
            {
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "masterplan_id": r.masterplan_id,
                "live_score": r.live_score,
                "shadow_score": r.shadow_score,
                "attainment_pct": r.attainment_pct,
                "hours_completed": r.hours_completed,
                "hours_total": r.hours_total,
                "objectives_measured": r.objectives_measured,
                "objectives": r.objectives,
                "trigger_event": r.trigger_event,
            }
            for r in rows
        ],
    }

