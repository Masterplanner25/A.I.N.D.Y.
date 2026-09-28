import json
import logging
import math
import re
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from AINDY.db.dao.memory_node_dao import MemoryNodeDAO
from apps.search.models import SearchHistory
from AINDY.runtime.memory import MemoryOrchestrator, memory_items_to_dicts
from apps.search.services.search_scoring import score_research_result
from apps.search.services.seo_services import (
    count_characters,
    generate_meta_description,
    seo_analysis,
)

logger = logging.getLogger(__name__)


def _normalized_search_query(query: str) -> str:
    return (query or "").strip()


def build_learning_context(result: dict[str, Any] | None, *, default_search_type: str | None = None) -> dict[str, Any]:
    payload = result if isinstance(result, dict) else {}
    memory = payload.get("memory") if isinstance(payload.get("memory"), dict) else {}
    memory_ids = list(memory.get("ids") or [])
    memory_count = memory.get("count")
    if memory_count is None:
        items = memory.get("items") or []
        memory_count = len(items) if isinstance(items, list) else 0
    memory_count = int(memory_count or 0)
    return {
        "search_type": payload.get("search_type") or default_search_type,
        "history_id": payload.get("history_id"),
        "search_score": payload.get("search_score"),
        "memory_count": memory_count,
        "memory_ids": memory_ids,
        "recalled_memory": memory_count > 0,
    }


def attach_learning_context(result: dict[str, Any] | None, *, default_search_type: str | None = None) -> dict[str, Any]:
    payload = result if isinstance(result, dict) else {}
    payload.setdefault(
        "learning_context",
        build_learning_context(payload, default_search_type=default_search_type),
    )
    return payload


def persist_search_result(
    *,
    db,
    user_id: str | None,
    query: str,
    result: dict[str, Any],
    search_type: str,
) -> dict[str, Any]:
    normalized_query = _normalized_search_query(query)
    if not db or not user_id or not normalized_query or not hasattr(db, "add"):
        return result
    try:
        payload = dict(result or {})
        payload["search_type"] = search_type
        history = SearchHistory(
            id=str(uuid.uuid4()),
            user_id=uuid.UUID(str(user_id)),
            query=normalized_query,
            result=payload,
        )
        db.add(history)
        db.commit()
        db.refresh(history)
        payload["history_id"] = history.id
        return payload
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            logger.debug("persist_search_result rollback skipped", exc_info=True)
        logger.warning("persist_search_result failed: %s", exc)
        return result


def get_search_history(db, user_id: str, *, limit: int = 25, search_type: str | None = None) -> list[SearchHistory]:
    query = (
        db.query(SearchHistory)
        .filter(SearchHistory.user_id == uuid.UUID(str(user_id)))
        .order_by(SearchHistory.created_at.desc())
    )
    if search_type:
        items = query.limit(max(limit * 2, limit)).all()
        return [item for item in items if (item.result or {}).get("search_type") == search_type][:limit]
    return query.limit(limit).all()


def get_search_history_item(db, user_id: str, history_id: str) -> SearchHistory | None:
    return (
        db.query(SearchHistory)
        .filter(
            SearchHistory.id == history_id,
            SearchHistory.user_id == uuid.UUID(str(user_id)),
        )
        .first()
    )


def delete_search_history_item(db, user_id: str, history_id: str) -> bool:
    item = get_search_history_item(db, user_id, history_id)
    if not item:
        return False
    db.delete(item)
    db.commit()
    return True


def get_cached_search_result(
    *,
    db,
    user_id: str | None,
    query: str,
    search_type: str,
) -> dict[str, Any] | None:
    normalized_query = _normalized_search_query(query)
    if not db or not user_id or not normalized_query or not hasattr(db, "query"):
        return None
    item = (
        db.query(SearchHistory)
        .filter(
            SearchHistory.user_id == uuid.UUID(str(user_id)),
            SearchHistory.query == normalized_query,
        )
        .order_by(SearchHistory.created_at.desc())
        .first()
    )
    if not item:
        return None
    payload = dict(item.result or {})
    if payload.get("search_type") != search_type:
        return None
    payload["history_id"] = item.id
    return payload


def execute_durable_search(
    *,
    db,
    user_id: str | None,
    query: str,
    search_type: str,
    memory_tags: list[str] | None,
    builder: Callable[[dict[str, Any]], dict[str, Any]],
    memory_limit: int = 3,
) -> dict[str, Any]:
    normalized_query = _normalized_search_query(query)
    cached = get_cached_search_result(
        db=db,
        user_id=user_id,
        query=normalized_query,
        search_type=search_type,
    )
    if cached:
        return attach_learning_context(cached, default_search_type=search_type)

    memory = search_memory(
        normalized_query,
        db=db,
        user_id=user_id,
        tags=memory_tags or [],
        limit=memory_limit,
    )
    result = dict(builder(memory) or {})
    result.setdefault("query", normalized_query)
    result.setdefault("memory", memory)
    persisted = persist_search_result(
        db=db,
        user_id=user_id,
        query=normalized_query,
        result=result,
        search_type=search_type,
    )
    return attach_learning_context(persisted, default_search_type=search_type)


def search_memory(query: str, db, user_id: str | None = None, tags: list[str] | None = None, limit: int = 5) -> dict[str, Any]:
    if not user_id or not db:
        return {"items": [], "ids": [], "formatted": "", "count": 0}
    try:
        orchestrator = MemoryOrchestrator(MemoryNodeDAO)
        context = orchestrator.get_context(
            user_id=str(user_id),
            query=query,
            task_type="analysis",
            db=db,
            max_tokens=500,
            metadata={
                "tags": tags or [],
                "limit": limit,
            },
        )
        # ★ `memory_items_to_dicts`, not `context.items`. The items are `MemoryItem`
        # OBJECTS, and this dict is embedded in every search result that
        # `execute_durable_search` then writes to `search_history.result` — a JSON column.
        # `json.dumps` cannot serialise a MemoryItem, so the INSERT raised, and
        # `persist_search_result` caught it, logged a warning and returned the unpersisted
        # result. The caller got its answer, so nothing looked wrong.
        #
        # Effect: EVERY SEO analysis silently failed to save. `search_history` held 0 rows
        # on 2026-09-06, the "Recent SEO Analyses" panel was permanently empty, and the
        # owner reported it as "there's no save button for any of it" — the save was wired
        # the whole time and losing every write.
        #
        # ★ It is conditional on recall finding something, which is why it was not caught
        # earlier: with an empty memory `items` is `[]`, which serialises fine and persists
        # correctly. The feature broke as memory filled up, and every test that recalls
        # nothing still passes.
        #
        # `memory_items_to_dicts` is the runtime's own converter and is already used this
        # way in `automation/flows/flow_definitions.py:361`.
        return {
            "items": memory_items_to_dicts(context.items),
            "ids": context.ids,
            "formatted": context.formatted,
            "count": len(context.items),
        }
    except Exception as exc:
        logger.warning("search_memory failed: %s", exc)
        return {"items": [], "ids": [], "formatted": "", "count": 0}


def search_seo(
    text: str,
    top_n: int = 10,
    *,
    title: str | None = None,
    target_keywords: list[str] | None = None,
) -> dict[str, Any]:
    # ★ No blended `search_score` (SEO_EDITING_AID_SPEC §5 Q3, owner 2026-09-11: drop it).
    # It averaged readability, mean keyword density and word count into one number. With
    # target-keyword coverage and the repetition report on the same page, a single averaged
    # figure was the least informative thing there — and averaging densities across whatever
    # keywords happened to be frequent was a questionable summary before targets existed.
    # The measurements it blended are all still returned individually.
    return seo_analysis(text, top_n, title=title, target_keywords=target_keywords)


def analyze_seo_content(
    text: str,
    top_n: int = 10,
    *,
    db=None,
    user_id: str | None = None,
    title: str | None = None,
    target_keywords: list[str] | None = None,
) -> dict[str, Any]:
    def _build(memory: dict[str, Any]) -> dict[str, Any]:
        analysis = search_seo(
            text, top_n=top_n, title=title, target_keywords=target_keywords
        )
        analysis["memory"] = memory
        return analysis

    return execute_durable_search(
        db=db,
        user_id=user_id,
        query=text,
        search_type="seo_analysis",
        memory_tags=["seo", "search", "content"],
        builder=_build,
        memory_limit=2,
    )


def suggest_seo_improvements(text: str, top_n: int = 5, *, db=None, user_id: str | None = None) -> dict[str, Any]:
    analysis = analyze_seo_content(text, top_n=top_n, db=db, user_id=user_id)
    suggestions: list[str] = []
    readability = float(analysis.get("readability", 0.0) or 0.0)
    word_count = int(analysis.get("word_count", 0) or 0)
    keyword_densities = analysis.get("keyword_densities") or {}
    top_keywords = analysis.get("top_keywords") or []

    if readability < 50:
        suggestions.append("Improve readability with shorter sentences and simpler phrasing.")
    if word_count < 300:
        suggestions.append("Increase content depth; the current article is likely too short for competitive ranking.")
    elif word_count > 2500:
        suggestions.append("Consider tightening the article to improve clarity and scannability.")

    weak_keywords = [kw for kw, density in keyword_densities.items() if density < 0.5][:3]
    high_keywords = [kw for kw, density in keyword_densities.items() if density > 3.0][:3]
    if weak_keywords:
        suggestions.append(f"Strengthen topical coverage around: {', '.join(weak_keywords)}.")
    if high_keywords:
        suggestions.append(f"Reduce overuse of: {', '.join(high_keywords)}.")
    if top_keywords:
        suggestions.append(f"Build headings and meta copy around the strongest terms: {', '.join(top_keywords[:3])}.")

    if not suggestions:
        suggestions.append("SEO baseline looks healthy; focus on stronger headings, internal linking, and clearer search intent matching.")

    return {
        "seo_suggestions": "\n".join(f"- {item}" for item in suggestions),
        "learning_context": analysis.get("learning_context")
        or build_learning_context(analysis, default_search_type="seo_analysis"),
    }


def _extract_leads_from_response(payload: Any, max_results: int = 3) -> list[dict[str, str]]:
    if isinstance(payload, dict):
        candidates = payload.get("results") or payload.get("data") or payload.get("items") or []
        return _extract_leads_from_response(candidates, max_results=max_results)
    if isinstance(payload, list):
        leads: list[dict[str, str]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            url = item.get("url") or item.get("link") or ""
            title = item.get("title") or item.get("name") or ""
            snippet = item.get("snippet") or item.get("summary") or item.get("description") or ""
            if not url:
                continue
            company = title or (urlparse(url).netloc or url).replace("www.", "").split(".")[0].replace("-", " ").title()
            leads.append({
                "company": company or "Unknown",
                "url": url,
                "context": snippet[:240],
            })
            if len(leads) >= max_results:
                break
        return leads
    return []


_URL = re.compile(r"https?://[^\s)]+")
_URL_LINE = re.compile(r"^\s*(https?://[^\s)]+)\s*$")
# A result title ends in its site: "AEO for Developer Tools - Infrasity", "… | Fast.io".
_SITE_SUFFIX = re.compile(r"\s(?:[-–—|])\s([^-–—|]{2,40})$")
LEAD_CONTEXT_CHARS = 240


def _domain_company(url: str) -> str:
    domain = urlparse(url).netloc or url
    return domain.replace("www.", "").split(".")[0].replace("-", " ").title() or "Unknown"


def _extract_leads_from_text(text: str, max_results: int = 3) -> list[dict[str, str]]:
    """Leads from the web search's text: one per distinct URL, each with ITS OWN context.

    The search text is a run of result blocks, a title line, then the URL line, then that result's
    text. Until 2026-09-28 every lead's context was the first 240 characters of the WHOLE text
    (so all three leads in run 8cdb97ef carried AMAX's snippet) and its company was the first
    word of the domain ("Linkedin" for a LinkedIn post, "Fast" for fast.io's article). Now a lead
    takes the title line above its URL, the text below it up to the next result, and a company
    from the title's site suffix before falling back to the domain. A URL inside a paragraph gets
    the text around it.
    """
    lines = (text or "").splitlines()
    url_lines = [i for i, line in enumerate(lines) if _URL_LINE.match(line)]
    seen: set[str] = set()
    leads: list[dict[str, str]] = []

    for n, i in enumerate(url_lines):
        url = _URL_LINE.match(lines[i]).group(1)
        if url in seen:
            continue
        seen.add(url)
        title = lines[i - 1].strip() if i > 0 else ""
        # The block ends where the next result's title line begins.
        end = url_lines[n + 1] - 1 if n + 1 < len(url_lines) else len(lines)
        body = " ".join(line.strip() for line in lines[i + 1:end] if line.strip() and line.strip() != "...")
        suffix = _SITE_SUFFIX.search(title)
        leads.append({
            "company": suffix.group(1).strip() if suffix else _domain_company(url),
            "title": title or _domain_company(url),
            "url": url,
            "context": (body or title)[:LEAD_CONTEXT_CHARS],
        })
        if len(leads) >= max_results:
            return leads

    # URLs inside prose, not on their own line: the text around each one.
    raw = text or ""
    for match in _URL.finditer(raw):
        url = match.group(0)
        if url in seen:
            continue
        seen.add(url)
        start = max(0, match.start() - LEAD_CONTEXT_CHARS // 2)
        window = raw[start:match.end() + LEAD_CONTEXT_CHARS // 2].replace("\n", " ").strip()
        leads.append({
            "company": _domain_company(url),
            "url": url,
            "context": window[:LEAD_CONTEXT_CHARS],
        })
        if len(leads) >= max_results:
            break
    return leads


def search_leads(query: str, db=None, user_id: str | None = None, max_results: int = 3) -> dict[str, Any]:
    def _build(memory: dict[str, Any]) -> dict[str, Any]:
        raw = ""
        leads: list[dict[str, str]] = []
        retrieval_error: str | None = None
        try:
            from apps.search.services.research_engine import web_search

            raw = web_search(query)
            parsed = None
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = None
            if parsed is not None:
                leads = _extract_leads_from_response(parsed, max_results=max_results)
            if not leads:
                leads = _extract_leads_from_text(raw, max_results=max_results)
        except Exception as exc:
            logger.warning("search_leads external retrieval failed: %s", exc)
            retrieval_error = str(exc) or type(exc).__name__

        if not leads:
            leads = [
                {
                    "company": "External Search",
                    "url": "",
                    "context": (raw or query)[:240],
                }
            ]

        # Additively expose the shared item fields (title/url/snippet/score) so
        # lead rows conform to SearchResultItem without dropping legacy keys.
        from apps.search.schemas.search_schema import enrich_lead_row

        enriched = [enrich_lead_row(dict(row)) for row in leads[:max_results]]

        return {
            "query": query,
            "results": enriched,
            "memory": memory,
            "raw_excerpt": (raw or "")[:1000],
            # The preview surface shows the url-less "External Search" row above; the scored
            # path (`run_ai_search`) must not save it as a lead, and reads this to tell a
            # failed retrieval from an empty one.
            "retrieval_error": retrieval_error,
        }

    return execute_durable_search(
        db=db,
        user_id=user_id,
        query=query,
        search_type="lead_preview",
        memory_tags=["leadgen", "search", "outcome"],
        builder=_build,
        memory_limit=2,
    )


def unified_query(
    query: str,
    db=None,
    user_id: str | None = None,
    *,
    web_search_fn: Callable[[str], str] | None = None,
    ai_analyze_fn: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    def _build(memory: dict[str, Any]) -> dict[str, Any]:
        raw = ""
        summary = ""
        source = None
        try:
            _web_search = web_search_fn
            _ai_analyze = ai_analyze_fn
            if _web_search is None or _ai_analyze is None:
                from apps.search.services.research_engine import web_search, ai_analyze

                _web_search = _web_search or web_search
                _ai_analyze = _ai_analyze or ai_analyze

            raw = _web_search(query)
            summary = _ai_analyze(raw)
            source = "external_search"
        except Exception as exc:
            logger.warning("unified_query external analysis failed: %s", exc)

        search_score = score_research_result(
            summary=summary or raw or query,
            memory_context_count=memory["count"],
        )
        payload = {
            "query": query,
            "summary": summary,
            "source": source,
            "raw_excerpt": (raw or "")[:2000],
            "memory": memory,
            "search_score": search_score,
        }
        # Attach the unified ranked structure so research returns the same
        # shape as the other search surfaces (Evolution Plan — Step 2).
        from apps.search.schemas.search_schema import research_to_search_response

        payload["results"] = [
            item.model_dump() for item in research_to_search_response(payload).results
        ]
        return payload

    return execute_durable_search(
        db=db,
        user_id=user_id,
        query=query,
        search_type="research",
        memory_tags=["research", "insight"],
        builder=_build,
        memory_limit=3,
    )


def generate_meta(text: str, limit: int = 160) -> dict[str, str]:
    meta = generate_meta_description(text, limit)
    return {
        "meta_description": meta,
        # ★ Characters, and reported rather than assumed. The writer is being handed something
        # measured against a budget they cannot see, and the budget is the whole point of the
        # feature — the previous version of this function trimmed to 160 WORDS while its
        # caller believed it was trimming to 160 characters.
        "characters": count_characters(meta),
        "budget": limit,
    }

