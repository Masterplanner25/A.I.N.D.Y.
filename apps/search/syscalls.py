"""Search domain syscall handlers."""
from __future__ import annotations

import logging

from AINDY.kernel.syscall_registry import SyscallContext, register_syscall

logger = logging.getLogger(__name__)


def _session_from_context(ctx: SyscallContext):
    from AINDY.db.database import SessionLocal

    external_db = ctx.metadata.get("_db")
    if external_db is not None:
        return external_db, False
    return SessionLocal(), True


def _handle_leadgen_search(payload: dict, ctx: SyscallContext) -> dict:
    from apps.search.services.leadgen_service import create_lead_results

    query = payload.get("query", "")
    if not query:
        raise ValueError("sys.v1.leadgen.search requires 'query'")

    db, owns_session = _session_from_context(ctx)
    try:
        raw = create_lead_results(db, query, user_id=ctx.user_id)
        serialized = [
            {
                "company": row.company,
                "url": row.url,
                "fit_score": row.fit_score,
                "intent_score": row.intent_score,
                "data_quality_score": row.data_quality_score,
                "overall_score": row.overall_score,
                "reasoning": row.reasoning,
                "search_score": search_score,
                "created_at": (
                    row.created_at.isoformat()
                    if hasattr(row.created_at, "isoformat")
                    else str(row.created_at or "")
                ),
            }
            for row, search_score in raw
        ]
        return {"search_results": serialized, "count": len(serialized)}
    finally:
        if owns_session:
            db.close()


def _handle_leadgen_search_ai(payload: dict, ctx: SyscallContext) -> dict:
    from apps.search.services.leadgen_service import run_ai_search

    query = payload.get("query", "")
    if not query:
        raise ValueError("sys.v1.leadgen.search_ai requires 'query'")

    db, owns_session = _session_from_context(ctx)
    try:
        leads = run_ai_search(query=query, user_id=ctx.user_id, db=db)
        return {"leads": leads, "count": len(leads)}
    finally:
        if owns_session:
            db.close()


def _handle_leadgen_store(payload: dict, ctx: SyscallContext) -> dict:
    from AINDY.core.execution_signal_helper import queue_memory_capture
    from apps.search.services.search_service import persist_search_result

    query: str = payload.get("query", "")
    results: list = payload.get("results") or []

    db, owns_session = _session_from_context(ctx)
    try:
        if ctx.user_id and results:
            queue_memory_capture(
                db=db,
                user_id=ctx.user_id,
                agent_namespace="leadgen",
                event_type="leadgen_search",
                content=f"LeadGen '{query[:80]}': {len(results)} results",
                source="flow_engine:leadgen",
                tags=["leadgen", "search", "outcome"],
            )

        if ctx.user_id and query and results:
            try:
                persist_search_result(
                    db=db,
                    user_id=ctx.user_id,
                    query=query,
                    result={"query": query, "count": len(results), "results": results},
                    search_type="leadgen",
                )
            except Exception as exc:
                logger.warning("[sys.v1.leadgen.store] cache persist failed (non-fatal): %s", exc)

        return {"stored": True, "count": len(results)}
    finally:
        if owns_session:
            db.close()


def _handle_leadgen_act(payload: dict, ctx: SyscallContext) -> dict:
    from apps.search.services.lead_execution_service import LeadExecutionService

    db, owns_session = _session_from_context(ctx)
    try:
        svc = LeadExecutionService(db=db, user_id=ctx.user_id)
        if bool(payload.get("apply", False)):
            return svc.execute(
                channel=payload.get("channel", "draft"),
                trigger=payload.get("trigger", "agent"),
            )
        return {"dry_run": True, **svc.plan()}
    finally:
        if owns_session:
            db.close()


def _handle_research_query(payload: dict, ctx: SyscallContext) -> dict:
    from apps.search.services.research_engine import web_search

    query = payload.get("query", "")
    if not query:
        raise ValueError("sys.v1.research.query requires 'query'")

    raw = web_search(query)
    return {"raw_result": _research_excerpt(raw)}


#: The agent's research result. It was `raw[:2000]` from the initial extraction, which cut mid-word
#: with no marker ("…The goal is no", 2026-09-25) and, since runtime 2.24.0, would be what a
#: `$from_step` reference carries to the next step (FR-46 ask 4: the runtime truncates nothing,
#: this cut is ours). 6000 matches the findings digest's cap (`apps/agent/services/run_findings.py`).
RESEARCH_RESULT_MAX_CHARS = 6000
RESEARCH_TRUNCATED_MARKER = " … [truncated]"


def _research_excerpt(raw: str | None, limit: int = RESEARCH_RESULT_MAX_CHARS) -> str:
    """At most `limit` characters, cut at a word boundary and marked when anything was dropped."""
    text = raw or ""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    boundary = max(cut.rfind(" "), cut.rfind("\n"))
    if boundary > limit // 2:
        cut = cut[:boundary]
    return cut.rstrip() + RESEARCH_TRUNCATED_MARKER


def _outcome_weights_for(db, user_id, query: str) -> dict[str, float] | None:
    """Per-result outcome weights for ranking, or ``None`` when the feature is off.

    Flag-gated (``AINDY_SEARCH_OUTCOME_WEIGHTING``): returns ``None`` unless the
    weighting is enabled and there is a user to attribute feedback to, so the
    default ranking path is byte-for-byte unchanged (Search v4 §8).
    """
    from apps.search.services.search_scoring import outcome_weighting_enabled

    if not outcome_weighting_enabled() or not user_id:
        return None
    try:
        from apps.search.services.feedback_service import get_result_outcome_weights

        return get_result_outcome_weights(db, user_id, query) or None
    except Exception as exc:  # pragma: no cover - ranking must never fail on feedback
        logger.warning("[sys.v1.search.query] outcome-weight lookup failed (non-fatal): %s", exc)
        return None


def _memory_to_item(item):
    """Map a recalled memory item onto the shared SearchResultItem shape."""
    from apps.search.schemas.search_schema import SearchResultItem

    if isinstance(item, dict):
        title = str(item.get("title") or item.get("node_type") or item.get("type") or "memory")
        snippet = str(
            item.get("content") or item.get("summary") or item.get("text") or ""
        )[:240] or None
        metadata = {
            k: item[k] for k in ("id", "node_type", "tags", "score") if k in item
        }
        return SearchResultItem(title=title, snippet=snippet, metadata=metadata)
    return SearchResultItem(title="memory", snippet=str(item)[:240] or None)


def _handle_search_query(payload: dict, ctx: SyscallContext) -> dict:
    """Unified search syscall — one contract over leadgen, research, SEO, memory.

    Routes by ``search_type`` and returns a normalized ``SearchResponse`` dump so
    every surface answers with the same ranked structure (Evolution Plan — Step 5).
    """
    from apps.search.schemas.search_schema import (
        SEARCH_TYPE_LEAD_PREVIEW,
        SEARCH_TYPE_LEADGEN,
        SEARCH_TYPE_RESEARCH,
        SEARCH_TYPE_SEO,
        SearchMemoryRef,
        SearchResponse,
        to_search_response,
    )
    from apps.search.services import search_service

    query = (payload.get("query") or "").strip()
    if not query:
        raise ValueError("sys.v1.search.query requires 'query'")
    search_type = (payload.get("search_type") or SEARCH_TYPE_RESEARCH).lower()
    limit = max(1, int(payload.get("limit") or 3))

    db, owns_session = _session_from_context(ctx)
    try:
        outcome_weights = _outcome_weights_for(db, ctx.user_id, query)
        if search_type in (SEARCH_TYPE_LEADGEN, SEARCH_TYPE_LEAD_PREVIEW):
            raw = search_service.search_leads(
                query, db=db, user_id=ctx.user_id, max_results=limit
            )
            response = to_search_response(
                raw, search_type=SEARCH_TYPE_LEADGEN, outcome_weights=outcome_weights
            )
        elif search_type in (SEARCH_TYPE_SEO, "seo"):
            raw = search_service.analyze_seo_content(query, db=db, user_id=ctx.user_id)
            response = to_search_response(raw, search_type=SEARCH_TYPE_SEO)
        elif search_type == "memory":
            mem = search_service.search_memory(
                query, db=db, user_id=ctx.user_id, limit=limit
            )
            response = SearchResponse(
                query=query,
                search_type="memory",
                results=[_memory_to_item(it) for it in (mem.get("items") or [])],
                memory=SearchMemoryRef(
                    count=int(mem.get("count") or 0),
                    ids=[str(i) for i in (mem.get("ids") or [])],
                ),
            )
        else:
            raw = search_service.unified_query(query, db=db, user_id=ctx.user_id)
            response = to_search_response(
                raw, search_type=SEARCH_TYPE_RESEARCH, outcome_weights=outcome_weights
            )
        return response.model_dump()
    finally:
        if owns_session:
            db.close()


def _handle_search_performance_signals(payload: dict, ctx: SyscallContext) -> dict:
    from apps.search.services.search_performance_service import get_search_performance_signals

    db, owns_session = _session_from_context(ctx)
    try:
        signals = list(
            get_search_performance_signals(
                db,
                user_id=payload.get("user_id") or ctx.user_id or None,
                limit=int(payload.get("limit", 3) or 3),
            )
            or []
        )
        return {"signals": signals, "count": len(signals)}
    finally:
        if owns_session:
            db.close()


def _handle_search_record_feedback(payload: dict, ctx: SyscallContext) -> dict:
    from apps.search.services.feedback_service import record_feedback

    db, owns_session = _session_from_context(ctx)
    try:
        return record_feedback(
            db,
            user_id=payload.get("user_id") or ctx.user_id,
            query=payload.get("query", ""),
            result_ref=payload.get("result_ref", ""),
            signal=payload.get("signal", ""),
            history_id=payload.get("history_id"),
        )
    finally:
        if owns_session:
            db.close()


def register_search_syscall_handlers() -> None:
    register_syscall(
        name="sys.v1.leadgen.search",
        handler=_handle_leadgen_search,
        capability="leadgen.search",
        description="B2B lead search via create_lead_results.",
        stable=False,
    )
    register_syscall(
        name="sys.v1.leadgen.search_ai",
        handler=_handle_leadgen_search_ai,
        capability="leadgen.search_ai",
        description="AI-powered B2B lead search.",
        stable=False,
    )
    register_syscall(
        name="sys.v1.leadgen.store",
        handler=_handle_leadgen_store,
        capability="leadgen.store",
        description="Persist leadgen results to memory bridge and search cache.",
        stable=False,
    )
    register_syscall(
        name="sys.v1.leadgen.act",
        handler=_handle_leadgen_act,
        capability="leadgen.act",
        description="Act on scored leads: gated, revertible outreach drafts (Execution Layer).",
        stable=False,
    )
    register_syscall(
        name="sys.v1.research.query",
        handler=_handle_research_query,
        capability="research.query",
        description="Web research query.",
        stable=False,
    )
    register_syscall(
        name="sys.v1.search.query",
        handler=_handle_search_query,
        capability="search.query",
        description="Unified search across leadgen, research, SEO, and memory surfaces.",
        stable=False,
    )
    register_syscall(
        name="sys.v1.search.get_performance_signals",
        handler=_handle_search_performance_signals,
        capability="search.read",
        description="Recent leadgen-yield signals for the Infinity support state (re-tether).",
        stable=False,
    )
    register_syscall(
        name="sys.v1.search.record_feedback",
        handler=_handle_search_record_feedback,
        capability="search.feedback",
        description="Record implicit/explicit feedback on a search result (Search v4 outcome signal).",
        stable=False,
    )
