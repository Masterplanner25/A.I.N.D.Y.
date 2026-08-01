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
anything. See ``docs/handoffs/MASTERPLAN_GOAL_ATTAINMENT_SPEC.md``.

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


_RESOLVERS: dict[str, Callable[..., float | None]] = {
    "tasks": _resolve_tasks,
    "usd": _freelance_metric,
    "impressions": _social_metric,
    "clicks": _social_metric,
    "posts": _social_metric,
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
