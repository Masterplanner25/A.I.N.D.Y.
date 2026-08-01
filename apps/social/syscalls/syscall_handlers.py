"""Social domain syscall handlers."""

from __future__ import annotations

from AINDY.kernel.syscall_registry import SyscallContext, register_syscall


def _handle_adapt_linkedin(payload: dict, ctx: SyscallContext) -> dict:
    from apps.social.public import adapt_linkedin_metrics

    canonical = adapt_linkedin_metrics(payload.get("data", {}))
    return {"canonical": canonical}


def _handle_social_performance_signals(payload: dict, ctx: SyscallContext) -> dict:
    from apps.social.public import get_social_performance_signals

    signals = list(
        get_social_performance_signals(
            user_id=payload.get("user_id") or ctx.user_id or None,
            limit=int(payload.get("limit", 3) or 3),
        )
        or []
    )
    return {"signals": signals, "count": len(signals)}


_GOAL_METRIC_KEYS = {
    "impressions": "total_impressions",
    "clicks": "total_clicks",
    "posts": "post_count",
}


def _handle_social_goal_metric(payload: dict, ctx: SyscallContext) -> dict:
    """Cumulative social counters, for MasterPlan goal attainment.

    ``get_performance_signals`` returns only the advisory signal list — it discards the
    ``overview`` counters entirely — so goal attainment needs its own contract.

    Social reads from Mongo and degrades gracefully; a degraded summary reports
    ``supported: False`` rather than a misleading 0, so the caller falls back to the
    existing formula instead of scoring against a phantom zero.
    """
    from apps.social.services.social_performance_service import summarize_social_performance

    unit = str(payload.get("unit") or "").strip().lower()
    key = _GOAL_METRIC_KEYS.get(unit)
    if key is None:
        return {"supported": False, "unit": unit, "value": 0.0}

    summary = summarize_social_performance(
        user_id=payload.get("user_id") or ctx.user_id or None,
        limit=int(payload.get("limit", 500) or 500),
    )
    if summary.get("status") == "degraded":
        return {"supported": False, "unit": unit, "value": 0.0, "reason": "degraded"}

    overview = summary.get("overview") or {}
    return {
        "supported": True,
        "unit": unit,
        "value": float(overview.get(key) or 0.0),
        "scope": "user",
    }


def register_all() -> None:
    register_syscall(
        "sys.v1.social.adapt_linkedin",
        _handle_adapt_linkedin,
        "social.read",
        "Adapt LinkedIn metrics into canonical analytics format",
        input_schema={"properties": {"data": {"type": "dict"}}},
        stable=False,
    )
    register_syscall(
        "sys.v1.social.get_performance_signals",
        _handle_social_performance_signals,
        "social.read",
        "Return recent social performance signals",
        input_schema={
            "properties": {
                "user_id": {"type": "string"},
                "limit": {"type": "integer"},
            }
        },
        stable=False,
    )
    register_syscall(
        "sys.v1.social.get_goal_metric",
        _handle_social_goal_metric,
        "social.read",
        "Cumulative social counters for MasterPlan goal attainment (impressions/clicks/posts).",
        input_schema={
            "required": ["unit"],
            "properties": {
                "unit": {"type": "string"},
                "user_id": {"type": "string"},
                "masterplan_id": {"type": "integer"},
            },
        },
        stable=False,
    )
