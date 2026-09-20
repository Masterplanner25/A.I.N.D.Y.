from datetime import datetime, timezone
import math
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from pymongo.errors import PyMongoError, ServerSelectionTimeoutError
from pymongo.database import Database
from sqlalchemy.orm import Session

from AINDY.core.execution_gate import to_envelope
from AINDY.db.database import get_db
from AINDY.platform_layer.rate_limiter import limiter
from AINDY.db.mongo_setup import get_optional_mongo_db
from AINDY.platform_layer.app_runtime import execute_with_pipeline_sync
from AINDY.services.auth_service import get_current_user
from apps.social.models.social_models import FeedItem, SocialPost, SocialProfile, TrustTier
from apps.social.services.comment_service import (
    CommentValidationError,
    create_comment,
    list_comments,
)
from apps.social.services.bridge_feed_service import get_bridge_feed_events
from apps.social.services.identity_binding_service import resolve_canonical_username
from apps.social.services.social_metrics_history_service import record_metric_deltas
from apps.social.services.social_performance_service import (
    compute_conversion_signal,
    compute_engagement_score,
    summarize_social_performance,
)

router = APIRouter(prefix="/social", tags=["Social Layer"], dependencies=[Depends(get_current_user)])


class SocialInteractionRequest(BaseModel):
    action: str
    amount: int = 1


class SocialCommentRequest(BaseModel):
    content: str
    parent_comment_id: Optional[str] = None
    author_username: Optional[str] = None


TRUST_TIER_WEIGHTS = {
    TrustTier.INNER_CIRCLE: 2.0,
    TrustTier.COLLAB: 1.5,
    TrustTier.OBSERVER: 1.0,
    TrustTier.SYSTEM: 1.2,
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _compute_visibility_score(post: SocialPost) -> float:
    trust_weight = TRUST_TIER_WEIGHTS.get(post.trust_tier_required, 1.0)
    engagement_total = max(post.likes, 0) + max(post.boosts, 0) * 2 + max(post.comments_count, 0)
    engagement_score = math.log1p(engagement_total) / 5.0
    return trust_weight * (1.0 + min(engagement_score, 1.0))


def _refresh_post_metrics(post_doc: dict) -> dict:
    post_doc["engagement_score"] = compute_engagement_score(post_doc)
    post_doc["conversion_signal"] = compute_conversion_signal(post_doc)
    return post_doc


def _build_social_performance_memory_hint(
    *,
    user_id: str,
    post_doc: dict,
    signal_type: str,
    reason: str,
) -> dict:
    return {
        "event_type": "social_performance",
        "content": f"Social performance {signal_type}: {str(post_doc.get('content', ''))[:160]}",
        "source": "social_router",
        "tags": ["social", "performance", signal_type],
        "node_type": "insight" if signal_type == "high" else "failure",
        "force": True,
        "user_id": user_id,
        "agent_namespace": "social",
        "extra": {
            "post_id": str(post_doc.get("id")),
            "engagement_score": float(post_doc.get("engagement_score", 0.0) or 0.0),
            "conversion_signal": float(post_doc.get("conversion_signal", 0.0) or 0.0),
            "impressions": int(post_doc.get("impressions", 0) or 0),
            "clicks": int(post_doc.get("clicks", 0) or 0),
            "reason": reason,
        },
    }


def _maybe_capture_performance_signal(
    *,
    db: Database,
    user_id: str,
    post_doc: dict,
) -> tuple[dict, list[dict]]:
    refreshed = _refresh_post_metrics(dict(post_doc))
    db["posts"].update_one(
        {"id": refreshed["id"]},
        {
            "$set": {
                "engagement_score": refreshed["engagement_score"],
                "conversion_signal": refreshed["conversion_signal"],
            }
        },
    )
    hints: list[dict] = []
    if refreshed["impressions"] >= 10 and refreshed["engagement_score"] >= 8.0:
        hints.append(
            _build_social_performance_memory_hint(
                user_id=user_id,
                post_doc=refreshed,
                signal_type="high",
                reason="high_engagement",
            )
        )
    elif refreshed["impressions"] >= 10 and refreshed["engagement_score"] <= 2.0:
        hints.append(
            _build_social_performance_memory_hint(
                user_id=user_id,
                post_doc=refreshed,
                signal_type="low",
                reason="low_engagement",
            )
        )
    return refreshed, hints


def _compute_infinity_ranked_score(
    post: SocialPost,
    author_master_score: float,
) -> float:
    try:
        age_hours = (_now_utc() - _ensure_aware_utc(post.created_at)).total_seconds() / 3600
        recency_score = math.exp(-age_hours / 24)
    except Exception:
        recency_score = 0.5

    author_component = min(1.0, max(0.0, author_master_score / 100.0))
    raw_trust = TRUST_TIER_WEIGHTS.get(post.trust_tier_required, 1.0)
    trust_component = min(1.0, raw_trust / 2.0)

    return round(
        (recency_score * 0.4) + (author_component * 0.4) + (trust_component * 0.2),
        4,
    )


def _with_execution_envelope(payload):
    envelope = to_envelope(
        eu_id=None,
        trace_id=None,
        status="SUCCESS",
        output=None,
        error=None,
        duration_ms=None,
        attempt_count=1,
    )
    if hasattr(payload, "status_code") and hasattr(payload, "body"):
        return payload
    if isinstance(payload, dict):
        data = payload.get("data")
        result = dict(data) if isinstance(data, dict) else dict(payload)
        result.setdefault("execution_envelope", envelope)
        return result
    return {"data": payload, "execution_envelope": envelope}


def social_feed_response_adapter(*, route_name, canonical, status_code, trace_headers):
    """Exact response adapter for `social.feed.get`.

    Mirrors the legacy social envelope so existing clients are unaffected (`data`
    stays the post list), but exposes the bridge-event channel in the top-level
    `events` field. The feed handler returns `data={"posts": [...], "events": [...]}`;
    this splits them. Errors are handled here because `adapt_response` invokes the
    exact adapter before its own error branch.
    """
    from fastapi.encoders import jsonable_encoder
    from fastapi.responses import JSONResponse

    meta = canonical.get("metadata", {}) or {}
    if canonical.get("status") == "error":
        return JSONResponse(
            status_code=int(meta.get("status_code") or status_code),
            content={"detail": jsonable_encoder(meta.get("error", "Execution failed"))},
            headers=trace_headers,
        )

    payload = canonical.get("data")
    if isinstance(payload, dict) and "posts" in payload:
        posts = payload.get("posts") or []
        events = payload.get("events") or []
    else:
        # Degraded / unexpected payloads fall back to the legacy shape.
        posts = payload if payload is not None else []
        events = []

    body = {
        "status": "SUCCESS",
        "data": posts,
        "result": posts,
        "events": events,
        "next_action": meta.get("next_action"),
        "trace_id": str(canonical.get("trace_id") or ""),
    }
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(body),
        headers=trace_headers,
    )


def _mongo_degraded_payload(reason: str, *, data=None):
    return {
        "status": "degraded",
        "data": [] if data is None else data,
        "reason": reason,
    }


def _resolve_comment_author(
    db: Database, sql_db: Session, user_id: str, supplied: Optional[str]
) -> str:
    """Best-effort display name for a comment author.

    Prefers the canonical users.username (source of truth), then a client-supplied
    value, then the author's social profile, then a short id slug so a comment
    always renders.
    """
    canonical, is_canonical = resolve_canonical_username(sql_db, user_id)
    if is_canonical and canonical:
        return canonical
    if supplied and supplied.strip():
        return supplied.strip()
    try:
        profile = db["profiles"].find_one({"user_id": user_id})
    except (ServerSelectionTimeoutError, PyMongoError):
        profile = None
    if profile and profile.get("username"):
        return str(profile["username"])
    return f"user-{user_id[:8]}"


def _project_profile_metrics(profile, sql_db):
    """Overlay the analytics-owned metrics onto a profile's ``metrics_snapshot``,
    read-through from ``apps.analytics.public`` (the single source of truth) rather
    than serving the stored copy. ``infinity_score`` (= analytics ``master_score``)
    and ``execution_speed_score`` are projected live; the social/task-owned fields
    (``twr_score``, ``trust_score``, ``execution_velocity``) are left untouched.

    Best-effort: returns the profile unchanged if it has no ``user_id``, no analytics
    score exists, or the lookup fails.
    """
    if not isinstance(profile, dict):
        return profile
    user_id = profile.get("user_id")
    if not user_id:
        return profile
    try:
        from apps.analytics.public import get_user_score

        score = get_user_score(str(user_id), sql_db)
    except Exception:
        score = None
    if not score:
        return profile
    snapshot = dict(profile.get("metrics_snapshot") or {})
    snapshot["infinity_score"] = float(score.get("master_score") or 0.0)
    snapshot["execution_speed_score"] = float(score.get("execution_speed_score") or 0.0)
    return {**profile, "metrics_snapshot": snapshot}


@router.post("/profile")
@limiter.limit("30/minute")
def upsert_profile(
    request: Request,
    profile_data: SocialProfile,
    db: Database | None = Depends(get_optional_mongo_db),
    sql_db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        if db is None:
            return _mongo_degraded_payload("mongodb_unavailable")
        user_id = str(current_user["sub"])

        # Canonical users.username is the source of truth. When present it
        # overrides the client value and marks the profile verified; when absent
        # the social-supplied username is kept, flagged unverified.
        canonical, is_canonical = resolve_canonical_username(sql_db, user_id)
        effective_username = canonical if is_canonical else (profile_data.username or "").strip()
        if not effective_username:
            raise HTTPException(
                status_code=422,
                detail={"error": "username_required", "message": "A username is required"},
            )

        try:
            profiles = db["profiles"]
            # The owner's profile is keyed by user_id (so a username change
            # reconciles in place rather than orphaning the old document).
            existing = profiles.find_one({"user_id": user_id})

            # Reject taking a username already held by a different user — unless
            # ours is canonical, in which case canonical authority wins and the
            # other (necessarily unverified) profile reconciles on its next write.
            squatter = profiles.find_one({"username": effective_username})
            if squatter and squatter.get("user_id") != user_id and not is_canonical:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "error": "profile_forbidden",
                        "message": "Cannot modify another user's profile",
                    },
                )

            update_data = profile_data.dict(exclude={"id", "joined_at"})
            update_data["username"] = effective_username
            update_data["username_verified"] = is_canonical
            update_data["user_id"] = user_id
            update_data["updated_at"] = _now_utc()

            if existing:
                profiles.update_one({"user_id": user_id}, {"$set": update_data})
                return _project_profile_metrics({**existing, **update_data}, sql_db)

            new_profile = profile_data.dict()
            new_profile.update(update_data)
            db["profiles"].insert_one(new_profile)
            return _project_profile_metrics(new_profile, sql_db)
        except ServerSelectionTimeoutError:
            return _mongo_degraded_payload("mongodb_unavailable")
        except PyMongoError as exc:
            return _mongo_degraded_payload(str(exc))

    result = execute_with_pipeline_sync(
        request=request,
        route_name="social.profile.upsert",
        handler=handler,
        user_id=str(current_user["sub"]),
        metadata={"db": sql_db},
    )
    return _with_execution_envelope(result)


@router.get("/profile/{username}")
@limiter.limit("60/minute")
def get_profile(
    request: Request,
    username: str,
    db: Database | None = Depends(get_optional_mongo_db),
    sql_db: Session = Depends(get_db),
):
    def handler(ctx):
        if db is None:
            return _mongo_degraded_payload("mongodb_unavailable")
        try:
            profile = db["profiles"].find_one({"username": username})
            if not profile:
                raise HTTPException(
                    status_code=404,
                    detail={"error": "profile_not_found", "message": "Profile not found"},
                )
            return _project_profile_metrics(profile, sql_db)
        except ServerSelectionTimeoutError:
            return _mongo_degraded_payload("mongodb_unavailable")
        except PyMongoError as exc:
            return _mongo_degraded_payload(str(exc))

    try:
        return execute_with_pipeline_sync(
            request=request,
            route_name="social.profile.get",
            handler=handler,
            metadata={"db": sql_db},
        )
    except ServerSelectionTimeoutError:
        return _mongo_degraded_payload("mongodb_unavailable")
    except PyMongoError as exc:
        return _mongo_degraded_payload(str(exc))


@router.post("/post")
@limiter.limit("30/minute")
def create_post(
    request: Request,
    post: SocialPost,
    db: Database | None = Depends(get_optional_mongo_db),
    sql_db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        if db is None:
            # The social layer is Mongo-backed. When Mongo isn't available the post cannot be
            # persisted — say so with a 503 instead of returning a success-wrapped degraded
            # payload, which made the client believe the post succeeded (form cleared, feed
            # refetched empty) while nothing was saved. Honest failure > silent data loss.
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "social_unavailable",
                    "message": "The social layer is unavailable — your post was not saved.",
                },
            )
        post_data = post.dict()
        user_id = str(current_user["sub"])
        post_data["user_id"] = user_id
        # Bind the denormalized author_username to the canonical users.username
        # when the user has one, so feed labels match the account identity.
        canonical, is_canonical = resolve_canonical_username(sql_db, user_id)
        if is_canonical:
            post_data["author_username"] = canonical
        author_username = post_data.get("author_username") or ""
        post_data["impressions"] = int(post_data.get("impressions", 0) or 0)
        post_data["clicks"] = int(post_data.get("clicks", 0) or 0)
        post_data["engagement_score"] = float(post_data.get("engagement_score", 0.0) or 0.0)
        post_data["conversion_signal"] = float(post_data.get("conversion_signal", 0.0) or 0.0)
        try:
            db["posts"].insert_one(post_data)
        except ServerSelectionTimeoutError:
            return _mongo_degraded_payload("mongodb_unavailable")
        except PyMongoError as exc:
            return _mongo_degraded_payload(str(exc))
        # insert_one mutates post_data in place, adding a Mongo `_id` (ObjectId). Returning it
        # raw made FastAPI's JSON encoder raise "'ObjectId' object is not iterable" -> 500 on
        # every successful post. The app keys posts by its own `id`, not `_id`, so drop it (the
        # feed already sheds it by rebuilding through the SocialPost model).
        post_data.pop("_id", None)
        return {
            "data": post_data,
            "execution_hints": {
                "memory": [
                    {
                        "event_type": "social_post",
                        "content": f"Social Broadcast: @{author_username} | {post.content}",
                        "source": "social_router",
                        "tags": ["social", "broadcast", post.trust_tier_required] + post.tags,
                        "node_type": "outcome",
                        "user_id": str(current_user["sub"]),
                        "agent_namespace": "social",
                    }
                ]
            },
        }

    result = execute_with_pipeline_sync(
        request=request,
        route_name="social.post.create",
        handler=handler,
        user_id=str(current_user["sub"]),
        metadata={"db": sql_db},
    )
    return _with_execution_envelope(result)


@router.get("/feed")
@limiter.limit("60/minute")
def get_feed(
    request: Request,
    limit: int = 20,
    trust_filter: Optional[str] = None,
    db: Database | None = Depends(get_optional_mongo_db),
    sql_db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        if db is None:
            # Mongo-backed; when it's unavailable, surface it as unavailable (503 -> the
            # client's "Could not load the feed" state) rather than an empty feed, which reads
            # as "you have no posts" and hides that the social layer is simply off.
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "social_unavailable",
                    "message": "The social layer is unavailable.",
                },
            )
        posts_collection = db["posts"]
        query = {}
        if trust_filter:
            query["trust_tier_required"] = trust_filter

        try:
            cursor = posts_collection.find(query).sort("created_at", -1).limit(limit * 2)
            post_docs = list(cursor)
        except ServerSelectionTimeoutError:
            return _mongo_degraded_payload("mongodb_unavailable")
        except PyMongoError as exc:
            return _mongo_degraded_payload(str(exc))
        memory_hints: list[dict] = []

        if post_docs:
            post_ids = [doc.get("id") for doc in post_docs if doc.get("id")]
            if post_ids:
                try:
                    posts_collection.update_many(
                        {"id": {"$in": post_ids}},
                        {"$inc": {"impressions": 1}},
                    )
                    refreshed_docs = [
                        _maybe_capture_performance_signal(
                            db=db,
                            user_id=str(current_user["sub"]),
                            post_doc=post_doc,
                        )
                        for post_doc in posts_collection.find({"id": {"$in": post_ids}})
                    ]
                except ServerSelectionTimeoutError:
                    return _mongo_degraded_payload("mongodb_unavailable")
                except PyMongoError as exc:
                    return _mongo_degraded_payload(str(exc))
                post_docs = [item[0] for item in refreshed_docs]
                for _, hints in refreshed_docs:
                    memory_hints.extend(hints)
                # Record the impression delta per post into durable history,
                # attributed to the post owner. Best-effort — never breaks feed.
                for post_doc in post_docs:
                    record_metric_deltas(
                        post_id=post_doc.get("id"),
                        deltas={"impressions": 1},
                        user_id=post_doc.get("user_id"),
                    )

        author_ids = list({doc.get("author_id") for doc in post_docs if doc.get("author_id")})
        from apps.social.services.social_service import get_user_scores
        author_scores = get_user_scores(sql_db, author_ids)

        feed_items = []
        for post_doc in post_docs:
            try:
                post_obj = SocialPost(**post_doc)
                author_master = author_scores.get(post_obj.author_id, 50.0)
                relevance = _compute_infinity_ranked_score(post_obj, author_master)
                feed_items.append(
                    FeedItem(
                        post=post_obj,
                        relevance_score=relevance,
                        reason=f"Infinity score: {author_master:.0f} | tier: {post_obj.trust_tier_required}",
                    )
                )
            except Exception:
                continue

        feed_items.sort(key=lambda item: item.relevance_score, reverse=True)
        # System/public bridge events ride alongside posts in a separate
        # `events` channel (see social_feed_response_adapter). Best-effort.
        bridge_events = get_bridge_feed_events(sql_db, limit=20)
        return {
            "data": {"posts": feed_items[:limit], "events": bridge_events},
            "execution_hints": {"memory": memory_hints},
        }

    return execute_with_pipeline_sync(
        request=request,
        route_name="social.feed.get",
        handler=handler,
        user_id=str(current_user["sub"]),
        metadata={"db": sql_db},
    )


@router.post("/posts/{post_id}/interact")
@limiter.limit("30/minute")
def record_post_interaction(
    request: Request,
    post_id: str,
    body: SocialInteractionRequest,
    db: Database | None = Depends(get_optional_mongo_db),
    sql_db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        if db is None:
            return _mongo_degraded_payload("mongodb_unavailable")
        action = (body.action or "").strip().lower()
        if action not in {"view", "click", "like", "boost", "comment"}:
            raise HTTPException(
                status_code=422,
                detail={"error": "invalid_social_action", "message": "Unsupported social action"},
            )
        field = {
            "view": "impressions",
            "click": "clicks",
            "like": "likes",
            "boost": "boosts",
            "comment": "comments_count",
        }[action]
        amount = max(1, int(body.amount or 1))
        posts = db["posts"]
        try:
            post_doc = posts.find_one({"id": post_id})
        except ServerSelectionTimeoutError:
            return _mongo_degraded_payload("mongodb_unavailable")
        except PyMongoError as exc:
            return _mongo_degraded_payload(str(exc))
        if not post_doc:
            raise HTTPException(
                status_code=404,
                detail={"error": "post_not_found", "message": "Post not found"},
            )

        try:
            posts.update_one({"id": post_id}, {"$inc": {field: amount}})
            updated = posts.find_one({"id": post_id}) or post_doc
        except ServerSelectionTimeoutError:
            return _mongo_degraded_payload("mongodb_unavailable")
        except PyMongoError as exc:
            return _mongo_degraded_payload(str(exc))
        # Record the interaction delta into durable history, attributed to the
        # post owner. Best-effort — never breaks the interaction.
        record_metric_deltas(
            post_id=post_id,
            deltas={field: amount},
            user_id=updated.get("user_id"),
        )
        try:
            updated, memory_hints = _maybe_capture_performance_signal(
                db=db,
                user_id=str(current_user["sub"]),
                post_doc=updated,
            )
        except ServerSelectionTimeoutError:
            return _mongo_degraded_payload("mongodb_unavailable")
        except PyMongoError as exc:
            return _mongo_degraded_payload(str(exc))
        return {
            "data": {
                "post_id": post_id,
                "action": action,
                "impressions": int(updated.get("impressions", 0) or 0),
                "clicks": int(updated.get("clicks", 0) or 0),
                "likes": int(updated.get("likes", 0) or 0),
                "boosts": int(updated.get("boosts", 0) or 0),
                "comments_count": int(updated.get("comments_count", 0) or 0),
                "engagement_score": float(updated.get("engagement_score", 0.0) or 0.0),
                "conversion_signal": float(updated.get("conversion_signal", 0.0) or 0.0),
            },
            "execution_hints": {"memory": memory_hints},
        }

    result = execute_with_pipeline_sync(
        request=request,
        route_name="social.post.interact",
        handler=handler,
        user_id=str(current_user["sub"]),
        metadata={"db": sql_db},
    )
    return _with_execution_envelope(result)


@router.post("/posts/{post_id}/comments")
@limiter.limit("30/minute")
def create_post_comment(
    request: Request,
    post_id: str,
    body: SocialCommentRequest,
    db: Database | None = Depends(get_optional_mongo_db),
    sql_db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        if db is None:
            return _mongo_degraded_payload("mongodb_unavailable")
        user_id = str(current_user["sub"])
        try:
            author_username = _resolve_comment_author(db, sql_db, user_id, body.author_username)
            comment = create_comment(
                db,
                post_id=post_id,
                author_id=user_id,
                author_username=author_username,
                content=body.content,
                parent_comment_id=body.parent_comment_id,
            )
        except CommentValidationError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"error": exc.error, "message": exc.message},
            )
        except ServerSelectionTimeoutError:
            return _mongo_degraded_payload("mongodb_unavailable")
        except PyMongoError as exc:
            return _mongo_degraded_payload(str(exc))

        # comments_count just changed — refresh derived engagement metrics and
        # collect any high/low performance memory hints, mirroring /interact.
        memory_hints: list[dict] = []
        try:
            post_doc = db["posts"].find_one({"id": post_id})
            if post_doc:
                # Record the comment delta into durable history (post owner).
                record_metric_deltas(
                    post_id=post_id,
                    deltas={"comments_count": 1},
                    user_id=post_doc.get("user_id"),
                )
                _, memory_hints = _maybe_capture_performance_signal(
                    db=db,
                    user_id=user_id,
                    post_doc=post_doc,
                )
        except (ServerSelectionTimeoutError, PyMongoError):
            memory_hints = []

        hints = list(memory_hints)
        hints.append(
            {
                "event_type": "social_comment",
                "content": f"Comment by @{author_username}: {comment['content'][:160]}",
                "source": "social_router",
                "tags": ["social", "comment"],
                "node_type": "outcome",
                "user_id": user_id,
                "agent_namespace": "social",
            }
        )
        return {"data": comment, "execution_hints": {"memory": hints}}

    result = execute_with_pipeline_sync(
        request=request,
        route_name="social.post.comment.create",
        handler=handler,
        user_id=str(current_user["sub"]),
        metadata={"db": sql_db},
    )
    return _with_execution_envelope(result)


@router.get("/posts/{post_id}/comments")
@limiter.limit("60/minute")
def list_post_comments(
    request: Request,
    post_id: str,
    limit: int = 100,
    db: Database | None = Depends(get_optional_mongo_db),
    sql_db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        if db is None:
            return _mongo_degraded_payload("mongodb_unavailable")
        try:
            comments = list_comments(db, post_id=post_id, limit=limit)
        except ServerSelectionTimeoutError:
            return _mongo_degraded_payload("mongodb_unavailable")
        except PyMongoError as exc:
            return _mongo_degraded_payload(str(exc))
        return {"data": comments}

    result = execute_with_pipeline_sync(
        request=request,
        route_name="social.post.comment.list",
        handler=handler,
        user_id=str(current_user["sub"]),
        metadata={"db": sql_db},
    )
    if isinstance(result, dict) and result.get("status") == "degraded":
        return _with_execution_envelope(result)
    return result


@router.get("/analytics")
@limiter.limit("60/minute")
def get_social_analytics(
    request: Request,
    sql_db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = execute_with_pipeline_sync(
        request=request,
        route_name="social.analytics.get",
        handler=lambda ctx: summarize_social_performance(user_id=str(current_user["sub"])),
        user_id=str(current_user["sub"]),
        metadata={"db": sql_db},
    )
    if isinstance(result, dict) and result.get("status") == "degraded":
        return _with_execution_envelope(result)
    return result

