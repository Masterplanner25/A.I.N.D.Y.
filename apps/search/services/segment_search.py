"""Lead search inside a confirmed market segment — `MARKET_MODEL_SPEC.md` §5, phase B.

The owner's question, 2026-09-28: *"the problem is where are we looking."* Until this, every lead
search was the whole open web at any age, phrased as a topic, so it returned articles about the
topic: a competitor's listicle, an analyst's piece, a trade story, each scored as a lead against a
fixed "AI consulting services" brief.

Now a search starts from a segment the owner confirmed, and:

- **where** — job boards by default (`hiring`), the segment's confirmed `channel` entries on request,
  or the open web. Recent results only. Verified live 2026-09-30 with the platform-teams segment's
  words: the open web returned listicles; the job-board filter returned Similarweb, OpenTeams,
  EarnIn, AmTech Software and Firmus, each hiring for the problem.
- **what** — the query is built from the segment's own words, not the planner's paraphrase.
- **is it a buyer** — each result is judged against the segment's buyer and problem and the owner's
  works that serve it, in one model call. A buyer is saved as a lead tagged with the segment. A
  result that is not a buyer is proposed as what it is (an alternative, a voice, …) through
  masterplan, instead of being filed as a lead. An irrelevant one is dropped.

Masterplan owns segments; this reads them through `masterplan.segment_brief` and proposes through
`masterplan.market_propose`, so nothing here imports masterplan.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable
from urllib.parse import urlparse

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

WHERE_VALUES = ("hiring", "channels", "web")

#: Where a company hiring for the problem posts it. The company is in the address.
JOB_BOARDS = (
    "job-boards.greenhouse.io",
    "boards.greenhouse.io",
    "jobs.lever.co",
    "jobs.ashbyhq.com",
    "apply.workable.com",
)
RECENCY = "month"
DEFAULT_MAX_RESULTS = 8
ENTITY_KINDS = ("alternative", "channel", "intermediary", "voice", "exemplar")

_JOB_TITLE_COMPANY = re.compile(r"\bat\s+(.+?)(?:\s+[-–|]\s+(?:Greenhouse|Lever|Ashby|Workable).*)?$", re.I)
_SITE_SUFFIX = re.compile(r"\s(?:[-–—|])\s([^-–—|]{2,40})$")


class SegmentSearchRefused(ValueError):
    """The search cannot run as asked: no such confirmed segment, or no channels to search."""


def _host(url: str | None) -> str:
    host = (urlparse(url or "").netloc or "").lower()
    return host[4:] if host.startswith("www.") else host


def company_from_result(url: str, title: str) -> str:
    """The organisation a result is about. A job posting names its employer in the title
    ("Job Application for AI Engineer at Similarweb") or the address (`/openteams/jobs/…`)."""
    host = _host(url)
    if any(host == board or host.endswith("." + board) for board in JOB_BOARDS):
        match = _JOB_TITLE_COMPANY.search(title or "")
        if match:
            return match.group(1).strip()
        parts = [p for p in urlparse(url).path.split("/") if p]
        if parts:
            return parts[0].replace("-", " ").replace("_", " ").title()
    suffix = _SITE_SUFFIX.search(title or "")
    if suffix:
        return suffix.group(1).strip()
    return (host.split(".")[0] if host else "").replace("-", " ").title() or "Unknown"


def build_query(brief: dict, where: str) -> str:
    """The segment's own words. For job boards, what the buyer would hire for; elsewhere, the
    problem as the buyer says it."""
    terms = [t for t in (brief.get("category_terms") or []) if t][:3]
    if where == "hiring":
        return (" ".join(terms) + " engineer").strip() if terms else f"{brief['buyer']}"
    problem = (brief.get("problem") or "").strip()
    return " ".join(part for part in (problem[:200], " ".join(terms[:2])) if part) or brief["buyer"]


def _domains(brief: dict, where: str) -> list[str] | None:
    if where == "hiring":
        return list(JOB_BOARDS)
    if where == "channels":
        hosts = sorted({_host(c.get("url")) for c in brief.get("channels") or [] if _host(c.get("url"))})
        if not hosts:
            raise SegmentSearchRefused(
                f"segment {brief['name']!r} has no confirmed channels with a url; propose some with "
                "market.propose (kind channel) or search where='hiring'"
            )
        return hosts[:20]
    return None


_JUDGE_PROMPT = """You qualify B2B leads for one market segment. Decide whether this web result shows a
PROSPECTIVE BUYER in the segment: an organisation that has the problem and could buy the seller's work.
Hiring for the problem is strong buyer evidence. A listicle, a vendor of a competing product, an analyst,
a publication or a personal project is NOT a buyer.

Return ONLY a JSON object with these keys:
is_buyer (true/false),
kind (when not a buyer: alternative | channel | intermediary | voice | exemplar | irrelevant; when a buyer: "buyer"),
organisation (the organisation the result is about, not the website that published it),
fit_score, intent_score, data_quality_score, overall_score (numbers 0-100; 0 when not a buyer),
reasoning (one sentence)."""


def judge_result(result: dict, brief: dict) -> dict:
    """One gpt-4o-mini call: buyer or not, what it is, and the scores (§5.3)."""
    from AINDY.config import settings
    from AINDY.platform_layer.external_call_service import perform_external_call
    from AINDY.platform_layer.openai_client import chat_completion, get_openai_client

    works = "; ".join(f"{w['name']}: {w['summary']}" for w in brief.get("works") or []) or "(none stated)"
    user = (
        f"SEGMENT: {brief['name']}\nBUYER: {brief['buyer']}\nTHEIR PROBLEM: {brief.get('problem') or '(not stated)'}\n"
        f"WHAT THEY CALL IT: {', '.join(brief.get('category_terms') or []) or '(not stated)'}\n"
        f"THE SELLER'S WORK THAT SERVES THEM: {works}\n\n"
        f"RESULT\nTitle: {result.get('title')}\nURL: {result.get('url')}\nSnippet: {result.get('snippet')}"
    )
    completion = perform_external_call(
        service_name="openai",
        endpoint="chat.completions.create",
        model="gpt-4o-mini",
        method="openai.chat",
        extra={"purpose": "segment_lead_judgement", "segment": brief["name"]},
        operation=lambda: chat_completion(
            get_openai_client(),
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": _JUDGE_PROMPT}, {"role": "user", "content": user}],
            timeout=settings.OPENAI_CHAT_TIMEOUT_SECONDS,
        ),
    )
    text = (completion.choices[0].message.content or "").strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(match.group(0) if match else text)


def _score(verdict: dict, key: str) -> float:
    try:
        return max(0.0, min(100.0, float(verdict.get(key) or 0)))
    except (TypeError, ValueError):
        return 0.0


def segment_lead_search(
    db: Session,
    *,
    user_id: Any,
    segment: str,
    where: str = "hiring",
    max_results: int = DEFAULT_MAX_RESULTS,
    search: Callable[..., list[dict]] | None = None,
    judge: Callable[[dict, dict], dict] | None = None,
) -> dict:
    """Search inside a confirmed segment. Buyers are saved as leads tagged with the segment; the rest
    are proposed as market entries or dropped. Commits."""
    from AINDY.platform_layer.registry import get_job
    from apps.search.services.leadgen_service import save_lead

    where = str(where or "hiring").strip().lower()
    if where not in WHERE_VALUES:
        raise SegmentSearchRefused(f"where must be one of: {', '.join(WHERE_VALUES)}")
    brief_job = get_job("masterplan.segment_brief")
    brief = brief_job(user_id=str(user_id), segment=segment, db=db) if brief_job else None
    if not brief:
        raise SegmentSearchRefused(f"no confirmed segment {segment!r}; confirm one in Collaborator's Market mode")

    query = build_query(brief, where)
    domains = _domains(brief, where)
    if search is None:
        from apps.search.services.research_engine import web_search_results as search
    judge = judge or judge_result
    propose = get_job("masterplan.market_propose")

    rows = search(query, domains=domains, recency=RECENCY, max_results=max_results)
    leads, proposed, dropped, failed = [], [], [], 0
    seen: set[str] = set()
    for row in rows:
        url = (row.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        try:
            verdict = judge(row, brief)
        except Exception as exc:  # one bad judgement must not lose the rest of the search
            failed += 1
            logger.warning("[segment_search] judgement failed for %s: %s", url, exc)
            continue
        organisation = str(verdict.get("organisation") or "").strip() or company_from_result(url, row.get("title", ""))
        context = " ".join(p for p in (row.get("title"), row.get("snippet")) if p)[:1000]
        if verdict.get("is_buyer") is True:
            lead = save_lead(db, user_id=user_id, url=url, fields={
                "query": query,
                "company": organisation[:300],
                "context": context,
                "segment_id": brief["id"],
                "fit_score": _score(verdict, "fit_score"),
                "intent_score": _score(verdict, "intent_score"),
                "data_quality_score": _score(verdict, "data_quality_score"),
                "overall_score": _score(verdict, "overall_score"),
                "reasoning": str(verdict.get("reasoning") or "")[:1000],
            })
            leads.append({"id": lead.id, "company": lead.company, "url": url, "context": context[:300],
                          "overall_score": lead.overall_score, "reasoning": lead.reasoning})
            continue
        kind = str(verdict.get("kind") or "").strip().lower()
        if kind in ENTITY_KINDS and propose is not None:
            outcome = propose(user_id=str(user_id), db=db, args={
                "kind": kind, "name": organisation, "url": url, "segment": brief["name"],
                "note": str(verdict.get("reasoning") or "")[:500] or None,
                "evidence": [{"claim": context[:400], "source_url": url}],
            })
            if outcome.get("proposed"):
                proposed.append({"kind": kind, "name": organisation})
                continue
        dropped.append({"name": organisation, "kind": kind or "irrelevant"})
    db.commit()
    return {
        "segment": brief["name"],
        "segment_status": brief["status"],
        "where": where,
        "query": query,
        "leads": sorted(leads, key=lambda lead: lead["overall_score"] or 0, reverse=True),
        "count": len(leads),
        "proposed": proposed,
        "dropped": len(dropped),
        "failed": failed,
    }
