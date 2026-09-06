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


def _handle_ensure_profile(payload: dict, ctx: SyscallContext) -> dict:
    """Create the user's social profile if they do not have one yet.

    Exists so signup can provision a profile the way it already provisions a score and an
    initial agent run. Before this, `signup_initialization_service` created neither, so a
    freshly registered user got a 404 from `GET /apps/social/profile/{username}` and the
    profile screen opened in create-mode for every new account.

    A syscall rather than a direct call because `identity` declares an empty
    `APP_DEPENDS_ON` and must not import `apps.social`. The syscall boundary is the
    runtime-mediated way across.

    ★ This never raises for a missing Mongo. The social layer is Mongo-backed and
    **degradable by design** — `docker-compose.prod.yml` ships without Mongo — so a
    registration must not fail because the optional datastore is absent. An unavailable
    Mongo returns `created=False, degraded=True`, which is a fact about the world rather
    than an error.
    """
    from pymongo.errors import PyMongoError, ServerSelectionTimeoutError

    from AINDY.db.database import SessionLocal
    from AINDY.db.mongo_setup import MONGO_DB_NAME, get_mongo_client
    from apps.social.services.identity_binding_service import resolve_canonical_username

    user_id = str(payload.get("user_id") or ctx.user_id or "").strip()
    if not user_id:
        raise ValueError("sys.v1.social.ensure_profile requires 'user_id'")

    client = get_mongo_client()
    if client is None:
        return {"created": False, "degraded": True, "reason": "mongodb_unavailable"}

    external_db = ctx.metadata.get("_db")
    db = external_db if external_db is not None else SessionLocal()
    owns_session = external_db is None
    try:
        # The canonical `users.username` is the source of truth (SOCIAL-IDENTITY-1). At
        # signup it is already set, so the profile is created verified rather than
        # inheriting the unverified social-only path the HTTP route falls back to.
        canonical, is_canonical = resolve_canonical_username(db, user_id)
        if not canonical:
            return {"created": False, "degraded": False, "reason": "no_canonical_username"}

        try:
            profiles = client[MONGO_DB_NAME]["profiles"]
            if profiles.find_one({"user_id": user_id}):
                return {"created": False, "degraded": False, "reason": "already_exists",
                        "username": canonical}

            from apps.social.models.social_models import SocialProfile

            profile = SocialProfile(username=canonical).dict()
            profile["user_id"] = user_id
            profile["username_verified"] = is_canonical
            profiles.insert_one(profile)
            return {"created": True, "degraded": False, "username": canonical}
        except ServerSelectionTimeoutError:
            return {"created": False, "degraded": True, "reason": "mongodb_unavailable"}
        except PyMongoError as exc:
            return {"created": False, "degraded": True, "reason": str(exc)}
    finally:
        if owns_session:
            db.close()


def register_all() -> None:
    register_syscall(
        "sys.v1.social.ensure_profile",
        _handle_ensure_profile,
        "social.write",
        "Create the user's social profile if absent (idempotent; degrades when Mongo is off)",
        input_schema={"properties": {"user_id": {"type": "string"}}},
        stable=False,
    )
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
