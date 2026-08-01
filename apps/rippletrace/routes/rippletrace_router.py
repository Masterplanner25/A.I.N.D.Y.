from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from uuid import UUID

from AINDY.core.execution_gate import to_envelope
from AINDY.core.execution_helper import execute_with_pipeline

from AINDY.db.database import get_db
from AINDY.platform_layer.rate_limiter import limiter

from apps.rippletrace.services import content_ingest
from apps.rippletrace.services import ripple_detection
from apps.rippletrace.services import rippletrace_services
from apps.rippletrace.services.content_fetch import ContentFetchError
from apps.rippletrace.services.mention_search import MentionSearchUnavailable
from AINDY.services.auth_service import get_current_user
from apps.rippletrace.services import causal_engine
from apps.rippletrace.services import learning_engine
from apps.rippletrace.services import narrative_engine
from apps.rippletrace.services import playbook_engine
from apps.rippletrace.services import prediction_engine
from apps.rippletrace.services import recommendation_engine
from apps.rippletrace.services import strategy_engine
from apps.rippletrace.services import rippletrace_service
from apps.rippletrace.services.rippletrace_service import (
    build_trace_graph,
    calculate_ripple_span,
    detect_root_event,
    detect_terminal_events,
    generate_trace_insights,
)


router = APIRouter(
    prefix="/rippletrace",
    tags=["RippleTrace"],
    dependencies=[Depends(get_current_user)],
)


def uuid_or_none(value):
    """Ownership filters compare against a UUID column; a malformed id must not 500."""
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


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


# === Schemas ===
class DropPoint(BaseModel):
    id: str
    title: str
    platform: str
    url: Optional[str] = None
    date_dropped: Optional[datetime] = None
    core_themes: List[str]
    tagged_entities: List[str]
    intent: str


class Ping(BaseModel):
    id: str
    drop_point_id: str
    ping_type: str
    source_platform: str
    date_detected: Optional[datetime] = None
    connection_summary: Optional[str] = None
    external_url: Optional[str] = None
    reaction_notes: Optional[str] = None
    strength: Optional[float] = Field(1.0, ge=0.0)


class IngestUrlRequest(BaseModel):
    """A URL the user published. Whether it is a page or a feed is detected, not asked."""

    url: str = Field(..., min_length=1, max_length=2048)


class ContentSourceUpdate(BaseModel):
    active: bool


class RippleEvent(BaseModel):
    ping_type: str
    source_platform: Optional[str] = "AINDY"
    summary: Optional[str] = None
    url: Optional[str] = None
    notes: Optional[str] = None
    drop_point_id: Optional[str] = "bridge"


# === ROUTES ===

@router.post("/drop_point")
@limiter.limit("30/minute")
async def create_drop_point(
    request: Request,
    dp: DropPoint,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        return rippletrace_services.add_drop_point(
            db, dp, user_id=str(current_user["sub"])
        )

    result = await execute_with_pipeline(request, "rippletrace_create_drop_point", handler)
    return _with_execution_envelope(result)


@router.post("/ping")
@limiter.limit("30/minute")
async def create_ping(
    request: Request,
    pg: Ping,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        return rippletrace_services.add_ping(
            db, pg, user_id=str(current_user["sub"])
        )

    result = await execute_with_pipeline(request, "rippletrace_create_ping", handler)
    return _with_execution_envelope(result)


@router.get("/ripples/{drop_point_id}")
@limiter.limit("60/minute")
async def get_ripples(
    request: Request,
    drop_point_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        return rippletrace_services.get_ripples(
            db, drop_point_id, user_id=str(current_user["sub"])
        )

    return await execute_with_pipeline(request, "rippletrace_get_ripples", handler)


@router.get("/drop_points")
@limiter.limit("60/minute")
async def all_drop_points(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        return rippletrace_services.get_all_drop_points(
            db, user_id=str(current_user["sub"])
        )

    return await execute_with_pipeline(request, "rippletrace_all_drop_points", handler)


@router.get("/pings")
@limiter.limit("60/minute")
async def all_pings(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        return rippletrace_services.get_all_pings(
            db, user_id=str(current_user["sub"])
        )

    return await execute_with_pipeline(request, "rippletrace_all_pings", handler)


@router.get("/recent")
@limiter.limit("60/minute")
async def recent_ripples(
    request: Request,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        return rippletrace_services.get_recent_ripples(
            db, limit, user_id=str(current_user["sub"])
        )

    return await execute_with_pipeline(request, "rippletrace_recent", handler)


# === Content ingestion ===
# Registered well above the `/{trace_id}` catch-all at the bottom of this module —
# routes are matched in declaration order, so `/sources` declared after it would be
# swallowed as a trace id.


@router.post("/ingest")
@limiter.limit("10/minute")
async def ingest_content_url(
    request: Request,
    body: IngestUrlRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Ingest a published URL. A feed becomes a subscription; a page becomes one drop point."""

    def handler(ctx):
        try:
            return content_ingest.ingest_url(
                db, url=body.url, user_id=str(current_user["sub"])
            )
        except ContentFetchError as exc:
            # A bad or non-public URL is the user's input being wrong, not a server
            # fault — surface the reason instead of a generic 500.
            raise HTTPException(
                status_code=422,
                detail={"error": "content_fetch_failed", "message": str(exc)},
            ) from exc

    result = await execute_with_pipeline(request, "rippletrace_ingest_url", handler)
    return _with_execution_envelope(result)


@router.post("/detect")
@limiter.limit("5/minute")
async def detect_ripples(
    request: Request,
    limit: int = 5,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Search the web for echoes of this user's drop points that are due for a check."""

    def handler(ctx):
        try:
            return ripple_detection.detect_batch(
                db,
                user_id=str(current_user["sub"]),
                limit=max(1, min(ripple_detection.MAX_DROP_POINTS_PER_RUN, int(limit))),
            )
        except MentionSearchUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail={"error": "mention_search_unavailable", "message": str(exc)},
            ) from exc

    result = await execute_with_pipeline(request, "rippletrace_detect_batch", handler)
    return _with_execution_envelope(result)


@router.post("/drop_points/{drop_point_id}/detect")
@limiter.limit("10/minute")
async def detect_ripples_for_drop_point(
    request: Request,
    drop_point_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        from apps.rippletrace.models import DropPointDB

        user_id = str(current_user["sub"])
        drop_point = (
            db.query(DropPointDB)
            .filter(DropPointDB.id == drop_point_id, DropPointDB.user_id == uuid_or_none(user_id))
            .first()
        )
        if drop_point is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "drop_point_not_found", "message": "Drop point not found"},
            )
        try:
            return ripple_detection.detect_for_drop_point(db, drop_point, user_id=user_id)
        except MentionSearchUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail={"error": "mention_search_unavailable", "message": str(exc)},
            ) from exc

    result = await execute_with_pipeline(request, "rippletrace_detect_drop_point", handler)
    return _with_execution_envelope(result)


@router.get("/sources")
@limiter.limit("60/minute")
async def list_content_sources(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        return {"sources": content_ingest.list_sources(db, user_id=str(current_user["sub"]))}

    result = await execute_with_pipeline(request, "rippletrace_list_sources", handler)
    return _with_execution_envelope(result)


@router.post("/sources/{source_id}/poll")
@limiter.limit("10/minute")
async def poll_content_source(
    request: Request,
    source_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        source = content_ingest.get_source(
            db, source_id=source_id, user_id=str(current_user["sub"])
        )
        if source is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "source_not_found", "message": "Content source not found"},
            )
        outcome = content_ingest.poll_source(db, source)
        return {"source": content_ingest.source_to_dict(source), **outcome}

    result = await execute_with_pipeline(request, "rippletrace_poll_source", handler)
    return _with_execution_envelope(result)


@router.patch("/sources/{source_id}")
@limiter.limit("30/minute")
async def update_content_source(
    request: Request,
    source_id: str,
    body: ContentSourceUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        updated = content_ingest.set_source_active(
            db,
            source_id=source_id,
            user_id=str(current_user["sub"]),
            active=body.active,
        )
        if updated is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "source_not_found", "message": "Content source not found"},
            )
        return updated

    result = await execute_with_pipeline(request, "rippletrace_update_source", handler)
    return _with_execution_envelope(result)


@router.delete("/sources/{source_id}")
@limiter.limit("30/minute")
async def delete_content_source(
    request: Request,
    source_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        if not content_ingest.delete_source(
            db, source_id=source_id, user_id=str(current_user["sub"])
        ):
            raise HTTPException(
                status_code=404,
                detail={"error": "source_not_found", "message": "Content source not found"},
            )
        return {"deleted": True, "id": source_id}

    result = await execute_with_pipeline(request, "rippletrace_delete_source", handler)
    return _with_execution_envelope(result)


@router.post("/event")
@limiter.limit("30/minute")
async def log_ripple_event(
    request: Request,
    event: RippleEvent,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        # convert direct event emission → execution_signals
        return {
            "data": {
                "status": "logged",
                "event": event.model_dump(),
            },
            "execution_signals": {
                "events": [
                    {
                        "type": "ripple_event",
                        "payload": event.model_dump(),
                    }
                ]
            },
        }

    result = await execute_with_pipeline(request, "rippletrace_log_event", handler)
    return _with_execution_envelope(result)


@router.get("/causal/graph")
@limiter.limit("30/minute")
async def get_causal_graph(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        return causal_engine.build_causal_graph(db)

    result = await execute_with_pipeline(request, "rippletrace_causal_graph", handler)
    return _with_execution_envelope(result)


@router.get("/influence/graph")
@limiter.limit("30/minute")
async def get_influence_graph(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    # Canonical, user-authable influence graph. The only prior influence_graph route lived in
    # the deprecated legacy surface router behind verify_api_key, so the user-facing GraphView
    # got 401 — and a 401 trips the client's global session-expired logout, bouncing the user
    # back to sign-in. This mirrors /causal/graph so GraphView can read it with a user token.
    from apps.rippletrace.services import influence_graph as influence_engine

    def handler(ctx):
        return influence_engine.build_influence_graph(db)

    result = await execute_with_pipeline(request, "rippletrace_influence_graph", handler)
    return _with_execution_envelope(result)


@router.get("/causal/chain/{drop_point_id}")
@limiter.limit("60/minute")
async def get_causal_chain_view(
    request: Request,
    drop_point_id: str,
    depth: int = 3,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        return causal_engine.get_causal_chain(drop_point_id, db, depth=depth)

    result = await execute_with_pipeline(request, "rippletrace_causal_chain", handler)
    return _with_execution_envelope(result)


@router.get("/narrative/summary")
@limiter.limit("30/minute")
async def get_narrative_summary(
    request: Request,
    limit: int = 3,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        return narrative_engine.narrative_summary(db, limit=limit)

    result = await execute_with_pipeline(request, "rippletrace_narrative_summary", handler)
    return _with_execution_envelope(result)


@router.get("/narrative/{drop_point_id}")
@limiter.limit("30/minute")
async def get_narrative(
    request: Request,
    drop_point_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        return narrative_engine.generate_narrative(drop_point_id, db)

    result = await execute_with_pipeline(request, "rippletrace_narrative", handler)
    return _with_execution_envelope(result)


@router.get("/predictions/summary")
@limiter.limit("30/minute")
async def get_predictions_summary(
    request: Request,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        return prediction_engine.prediction_summary(db, limit=limit)

    result = await execute_with_pipeline(request, "rippletrace_predictions_summary", handler)
    return _with_execution_envelope(result)


@router.get("/predictions/{drop_point_id}")
@limiter.limit("30/minute")
async def get_drop_point_prediction(
    request: Request,
    drop_point_id: str,
    record_learning: bool = True,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        return prediction_engine.predict_drop_point(
            drop_point_id, db, record_learning=record_learning
        )

    result = await execute_with_pipeline(request, "rippletrace_predict", handler)
    return _with_execution_envelope(result)


@router.get("/recommendations/system")
@limiter.limit("30/minute")
async def get_system_recommendations(
    request: Request,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        return recommendation_engine.system_recommendations(db, limit=limit)

    result = await execute_with_pipeline(request, "rippletrace_recommendations_system", handler)
    return _with_execution_envelope(result)


@router.get("/recommendations/summary")
@limiter.limit("30/minute")
async def get_recommendations_summary(
    request: Request,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        return recommendation_engine.recommendations_summary(db, limit=limit)

    result = await execute_with_pipeline(request, "rippletrace_recommendations_summary", handler)
    return _with_execution_envelope(result)


@router.get("/recommendations/{drop_point_id}")
@limiter.limit("30/minute")
async def get_drop_point_recommendation(
    request: Request,
    drop_point_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        return recommendation_engine.recommend_for_drop_point(drop_point_id, db)

    result = await execute_with_pipeline(request, "rippletrace_recommend", handler)
    return _with_execution_envelope(result)


@router.get("/learning/stats")
@limiter.limit("60/minute")
async def get_learning_stats(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        return learning_engine.learning_stats(db)

    result = await execute_with_pipeline(request, "rippletrace_learning_stats", handler)
    return _with_execution_envelope(result)


@router.post("/learning/evaluate/{drop_point_id}")
@limiter.limit("10/minute")
async def evaluate_learning_outcome(
    request: Request,
    drop_point_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        return learning_engine.evaluate_outcome(drop_point_id, db)

    result = await execute_with_pipeline(request, "rippletrace_learning_evaluate", handler)
    return _with_execution_envelope(result)


@router.post("/learning/adjust")
@limiter.limit("5/minute")
async def adjust_learning_thresholds(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        return learning_engine.adjust_thresholds(db)

    result = await execute_with_pipeline(request, "rippletrace_learning_adjust", handler)
    return _with_execution_envelope(result)


@router.get("/playbooks")
@limiter.limit("60/minute")
async def list_playbooks_view(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        return playbook_engine.list_playbooks(db)

    result = await execute_with_pipeline(request, "rippletrace_playbooks_list", handler)
    return _with_execution_envelope(result)


@router.get("/playbooks/match/{drop_point_id}")
@limiter.limit("30/minute")
async def match_playbooks_view(
    request: Request,
    drop_point_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        return playbook_engine.match_playbooks(drop_point_id, db)

    result = await execute_with_pipeline(request, "rippletrace_playbooks_match", handler)
    return _with_execution_envelope(result)


@router.get("/playbooks/{playbook_id}")
@limiter.limit("60/minute")
async def get_playbook_view(
    request: Request,
    playbook_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        result = playbook_engine.get_playbook(playbook_id, db)
        if result is None:
            raise HTTPException(status_code=404, detail=f"Playbook {playbook_id} not found")
        return result

    result = await execute_with_pipeline(request, "rippletrace_playbook_get", handler)
    return _with_execution_envelope(result)


@router.get("/strategies")
@limiter.limit("60/minute")
async def list_strategies_view(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        return strategy_engine.list_strategies(db)

    result = await execute_with_pipeline(request, "rippletrace_strategies_list", handler)
    return _with_execution_envelope(result)


@router.get("/strategies/build")
@limiter.limit("10/minute")
async def build_strategies_view(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        return strategy_engine.build_strategies(db)

    result = await execute_with_pipeline(request, "rippletrace_strategies_build", handler)
    return _with_execution_envelope(result)


@router.get("/strategies/match/{drop_point_id}")
@limiter.limit("30/minute")
async def match_strategies_view(
    request: Request,
    drop_point_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        return strategy_engine.match_strategies(drop_point_id, db)

    result = await execute_with_pipeline(request, "rippletrace_strategies_match", handler)
    return _with_execution_envelope(result)


@router.get("/strategies/{strategy_id}")
@limiter.limit("60/minute")
async def get_strategy_view(
    request: Request,
    strategy_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        result = strategy_engine.get_strategy(strategy_id, db)
        if result is None:
            raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")
        return result

    result = await execute_with_pipeline(request, "rippletrace_strategy_get", handler)
    return _with_execution_envelope(result)


@router.get("/event/{event_id}/downstream")
@limiter.limit("60/minute")
async def get_event_downstream(
    request: Request,
    event_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        return rippletrace_service.get_downstream_effects(db, event_id)

    result = await execute_with_pipeline(request, "rippletrace_event_downstream", handler)
    return _with_execution_envelope(result)


@router.get("/event/{event_id}/upstream")
@limiter.limit("60/minute")
async def get_event_upstream(
    request: Request,
    event_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        return rippletrace_service.get_upstream_causes(db, event_id)

    result = await execute_with_pipeline(request, "rippletrace_event_upstream", handler)
    return _with_execution_envelope(result)


@router.get("/{trace_id}")
@limiter.limit("60/minute")
async def get_trace_graph(
    request: Request,
    trace_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    def handler(ctx):
        from apps.rippletrace.services.rippletrace_service import count_trace_events

        user_id = str(current_user["sub"])
        events = count_trace_events(db, trace_id, user_id)

        if events == 0:
            return {
                "trace_id": trace_id,
                "nodes": [],
                "edges": [],
                "root_event": None,
                "terminal_events": [],
                "ripple_span": {
                    "node_count": 0,
                    "edge_count": 0,
                    "depth": 0,
                    "terminal_count": 0,
                },
                "insights": {
                    "root_cause": None,
                    "dominant_path": [],
                    "failure_clusters": [],
                    "summary": "No causal insight available for this trace.",
                    "recommendations": [],
                },
            }

        graph = build_trace_graph(db, trace_id)

        return {
            "trace_id": trace_id,
            "nodes": graph["nodes"],
            "edges": graph["edges"],
            "root_event": detect_root_event(db, trace_id),
            "terminal_events": detect_terminal_events(db, trace_id),
            "ripple_span": calculate_ripple_span(db, trace_id),
            "insights": generate_trace_insights(db, trace_id),
        }

    return await execute_with_pipeline(request, "rippletrace_trace_graph", handler)
