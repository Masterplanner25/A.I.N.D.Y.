from fastapi import APIRouter, Depends, Request
from typing import Optional

from pydantic import BaseModel
from sqlalchemy.orm import Session
from AINDY.core.execution_gate import to_envelope
from AINDY.core.execution_helper import execute_with_pipeline_sync
from apps.search.schemas.seo import (
    SEOInput,
    MetaInput,
    TitleInput,
    DraftCreateInput,
    DraftUpdateInput,
    DraftAnalyzeInput,
    DraftPruneInput,
)
from AINDY.services.auth_service import get_current_user
from AINDY.db.database import get_db
from AINDY.platform_layer.rate_limiter import limiter
from apps.search.services.title_generation import generate_title_candidates
from apps.search.services.draft_service import (
    create_draft,
    delete_draft,
    get_draft,
    list_drafts,
    prune_analyses,
    record_analysis,
    update_draft,
)
from apps.search.services.search_service import (
    analyze_seo_content,
    execute_durable_search,
    generate_meta as generate_meta_result,
    suggest_seo_improvements,
)

router = APIRouter(prefix="/seo", tags=["SEO"], dependencies=[Depends(get_current_user)])


def _execute_seo(
    request: Request,
    route_name: str,
    handler,
    *,
    db: Session | None = None,
    user_id: str | None = None,
):
    metadata = {"source": "seo_routes"}
    if db is not None:
        metadata["db"] = db
    return execute_with_pipeline_sync(
        request=request,
        route_name=route_name,
        handler=handler,
        user_id=user_id,
        metadata=metadata,
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


class LegacyContentInput(BaseModel):
    content: str
    # The client calls these compat routes, not `/analyze` — see `api-routes.test.js`, which
    # pins ANALYZE_SEO to "/apps/seo/analyze_seo/". A new field added only to `SEOInput` would
    # therefore be unreachable from the UI, which is the surface it exists for.
    title: Optional[str] = None
    target_keywords: Optional[list[str]] = None


@router.post("/analyze")
@limiter.limit("30/minute")
def analyze_seo(
    request: Request,
    data: SEOInput,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    from apps.analytics.public import save_calculation
    user_id = str(current_user["sub"])

    results = analyze_seo_content(
        data.text, data.top_n, db=db, user_id=user_id, title=data.title,
        target_keywords=data.target_keywords,
    )

    # Save key SEO metrics
    save_calculation(db, "seo_readability", results["readability"])
    save_calculation(db, "seo_word_count", results["word_count"])

    # Optionally save average density
    avg_density = 0.0
    if results["keyword_densities"]:
        avg_density = sum(results["keyword_densities"].values()) / len(results["keyword_densities"])
        save_calculation(db, "seo_avg_keyword_density", round(avg_density, 2))

    def handler(_ctx):
        return results
    return _with_execution_envelope(
        _execute_seo(request, "seo.analyze", handler, db=db, user_id=user_id)
    )

@router.post("/meta")
@limiter.limit("30/minute")
def generate_meta(
    request: Request,
    data: MetaInput,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])

    def handler(_ctx):
        def _build(memory: dict):
            result = generate_meta_result(data.text, data.limit)
            result["memory"] = memory
            return result

        return execute_durable_search(
            db=db,
            user_id=user_id,
            query=data.text[:200],
            search_type="seo_meta",
            memory_tags=["seo", "search", "meta"],
            builder=_build,
            memory_limit=1,
        )

    return _with_execution_envelope(
        _execute_seo(request, "seo.meta", handler, db=db, user_id=user_id)
    )


@router.post("/title")
@limiter.limit("15/minute")
def generate_title(
    request: Request,
    data: TitleInput,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Propose title options for an article. Never returns a replacement for the writer's own.

    Rate-limited harder than the analysis routes (15/min vs 30) because this one costs an
    external model call per request, where the rest are local computation.
    """
    user_id = str(current_user["sub"])

    def handler(_ctx):
        return generate_title_candidates(
            data.text,
            count=data.count or 5,
            existing_title=data.current_title,
            target_keywords=data.target_keywords,
            user_id=user_id,
            db=db,
        )

    return _with_execution_envelope(
        _execute_seo(request, "seo.title", handler, db=db, user_id=user_id)
    )


@router.post("/suggest")
@limiter.limit("30/minute")
def suggest_improvements(
    request: Request,
    data: SEOInput,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])

    def handler(_ctx):
        return suggest_seo_improvements(data.text, data.top_n, db=db, user_id=user_id)

    return _with_execution_envelope(
        _execute_seo(request, "seo.suggest", handler, db=db, user_id=user_id)
    )


@router.post("/analyze_seo/")
@limiter.limit("30/minute")
def analyze_seo_compat(
    request: Request,
    data: LegacyContentInput,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])

    def handler(_ctx):
        return analyze_seo_content(
            data.content, 10, db=db, user_id=user_id, title=data.title,
            target_keywords=data.target_keywords,
        )

    return _with_execution_envelope(
        _execute_seo(request, "seo.analyze.compat", handler, db=db, user_id=user_id)
    )


@router.post("/generate_meta/")
@limiter.limit("30/minute")
def generate_meta_compat(
    request: Request,
    data: LegacyContentInput,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])

    def handler(_ctx):
        def _build(memory: dict):
            result = generate_meta_result(data.content, 160)
            result["memory"] = memory
            return result

        return execute_durable_search(
            db=db,
            user_id=user_id,
            query=data.content[:200],
            search_type="seo_meta",
            memory_tags=["seo", "search", "meta"],
            builder=_build,
            memory_limit=1,
        )

    return _with_execution_envelope(
        _execute_seo(request, "seo.meta.compat", handler, db=db, user_id=user_id)
    )


@router.post("/suggest_improvements/")
@limiter.limit("30/minute")
def suggest_improvements_compat(
    request: Request,
    data: LegacyContentInput,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])

    def handler(_ctx):
        return suggest_seo_improvements(data.content, db=db, user_id=user_id)

    return _with_execution_envelope(
        _execute_seo(request, "seo.suggest.compat", handler, db=db, user_id=user_id)
    )


# ── Drafts ─────────────────────────────────────────────────────────────────────────
#
# The unit that makes the tool a loop rather than a set of readings taken once
# (SEO_EDITING_AID_SPEC §4). A draft holds its own content, title and target keywords, so
# re-analysing it is a request with no body: two analyses of the same draft are guaranteed to
# have been measured against the same targets, which is what makes them comparable.


@router.post("/drafts")
@limiter.limit("30/minute")
def create_seo_draft(
    request: Request,
    data: DraftCreateInput,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])

    def handler(_ctx):
        try:
            return create_draft(
                db,
                user_id=user_id,
                name=data.name,
                content=data.content or "",
                title=data.title,
                target_keywords=data.target_keywords,
            )
        except ValueError as exc:
            # Raised before pipeline entry would surface as an opaque internal_error
            # (PRE-PIPELINE-RAISE-500S); returned as an HTTP_ marker it reaches the caller as
            # the 422 it is.
            raise ValueError(f"HTTP_422:{exc}") from exc

    return _with_execution_envelope(
        _execute_seo(request, "seo.drafts.create", handler, db=db, user_id=user_id)
    )


@router.get("/drafts")
@limiter.limit("60/minute")
def list_seo_drafts(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])

    def handler(_ctx):
        return {"drafts": list_drafts(db, user_id=user_id)}

    return _with_execution_envelope(
        _execute_seo(request, "seo.drafts.list", handler, db=db, user_id=user_id)
    )


@router.get("/drafts/{draft_id}")
@limiter.limit("60/minute")
def get_seo_draft(
    request: Request,
    draft_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])

    def handler(_ctx):
        draft = get_draft(db, user_id=user_id, draft_id=draft_id)
        if draft is None:
            raise ValueError("HTTP_404:draft not found")
        return draft

    return _with_execution_envelope(
        _execute_seo(request, "seo.drafts.get", handler, db=db, user_id=user_id)
    )


@router.patch("/drafts/{draft_id}")
@limiter.limit("60/minute")
def update_seo_draft(
    request: Request,
    draft_id: str,
    data: DraftUpdateInput,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])

    def handler(_ctx):
        draft = update_draft(
            db,
            user_id=user_id,
            draft_id=draft_id,
            name=data.name,
            content=data.content,
            title=data.title,
            target_keywords=data.target_keywords,
            published_url=data.published_url,
        )
        if draft is None:
            raise ValueError("HTTP_404:draft not found")
        return draft

    return _with_execution_envelope(
        _execute_seo(request, "seo.drafts.update", handler, db=db, user_id=user_id)
    )


@router.delete("/drafts/{draft_id}")
@limiter.limit("30/minute")
def delete_seo_draft(
    request: Request,
    draft_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])

    def handler(_ctx):
        if not delete_draft(db, user_id=user_id, draft_id=draft_id):
            raise ValueError("HTTP_404:draft not found")
        return {"deleted": True, "draft_id": draft_id}

    return _with_execution_envelope(
        _execute_seo(request, "seo.drafts.delete", handler, db=db, user_id=user_id)
    )


@router.post("/drafts/{draft_id}/analyze")
@limiter.limit("30/minute")
def analyze_seo_draft(
    request: Request,
    draft_id: str,
    data: DraftAnalyzeInput,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Analyse the draft as it stands, and keep the reading.

    ★ The request carries no text. The draft is the source of the content, the title AND the
    target keywords, so two analyses of one draft cannot silently have been measured against
    different targets — which would make them incomparable while still looking comparable.
    """
    user_id = str(current_user["sub"])

    def handler(_ctx):
        draft = get_draft(db, user_id=user_id, draft_id=draft_id)
        if draft is None:
            raise ValueError("HTTP_404:draft not found")
        analysis = analyze_seo_content(
            draft["content"],
            data.top_n or 10,
            db=db,
            user_id=user_id,
            title=draft["title"] or None,
            target_keywords=draft["target_keywords"] or None,
        )
        recorded = record_analysis(
            db, user_id=user_id, draft_id=draft_id, result=analysis
        )
        refreshed = get_draft(db, user_id=user_id, draft_id=draft_id) or {}
        return {
            "analysis": analysis,
            "recorded": recorded,
            "deltas": refreshed.get("deltas"),
            "retention": refreshed.get("retention"),
        }

    return _with_execution_envelope(
        _execute_seo(request, "seo.drafts.analyze", handler, db=db, user_id=user_id)
    )


@router.post("/drafts/{draft_id}/prune")
@limiter.limit("15/minute")
def prune_seo_draft_analyses(
    request: Request,
    draft_id: str,
    data: DraftPruneInput,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Delete the analyses a person confirmed. Never called by the system on its own.

    Retention here is proposed and confirmed, not enforced: a silent cap would remove the
    earliest readings, which are exactly what a before/after comparison is measured against.
    """
    user_id = str(current_user["sub"])

    def handler(_ctx):
        return prune_analyses(
            db, user_id=user_id, draft_id=draft_id, analysis_ids=data.analysis_ids
        )

    return _with_execution_envelope(
        _execute_seo(request, "seo.drafts.prune", handler, db=db, user_id=user_id)
    )
