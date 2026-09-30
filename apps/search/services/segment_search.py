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
- **is it a buyer** — one model call per result reports facts (what kind of organisation, whether it
  fits the segment's buyer, whether it has the problem) and `classify` decides. Only an end user that
  fits is a buyer, saved as a lead tagged with the segment. A vendor is proposed as an alternative,
  an agency as an intermediary, a publisher as a voice, through masterplan. Anything else is dropped,
  and a lead an earlier judgement saved that no longer qualifies leaves the leads.

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


_NAME_NOISE = {"inc", "llc", "ltd", "co", "corp", "corporation", "the", "gmbh", "plc", "limited"}


def _words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split()


def _named_in(name: str, result: dict) -> bool:
    """Whether a name appears in the result itself: every word of it in the title, url or snippet,
    or the words run together in the address (a job board's `/robotsandpencils/` slug)."""
    words = [w for w in _words(name) if w not in _NAME_NOISE]
    if not words:
        return False
    haystack = " ".join(str(result.get(k) or "") for k in ("title", "url", "snippet"))
    present = set(_words(haystack))
    return all(w in present for w in words) or "".join(words) in "".join(_words(haystack))


#: A "name" ending in one of these is a description ("an AI security company", "a fintech startup").
_DESCRIPTORS = {"company", "startup", "firm", "organisation", "organization", "business", "employer",
                "client", "provider", "vendor", "agency", "team", "enterprise"}


def _is_description(name: str) -> bool:
    words = _words(name)
    return not words or words[0] in {"a", "an"} or words[-1] in _DESCRIPTORS


def _address_or_title_employer(result: dict) -> str | None:
    """The employer a job board's address or title gives, or a site name the title ends with.
    Never a bare host label: an anonymous careers site is not an organisation called "Careers"."""
    url, title = result.get("url") or "", result.get("title") or ""
    host = _host(url)
    if any(host == board or host.endswith("." + board) for board in JOB_BOARDS):
        return company_from_result(url, title)
    suffix = _SITE_SUFFIX.search(title)
    return suffix.group(1).strip() if suffix else None


def grounded_organisation(claimed: str, result: dict) -> str | None:
    """The organisation a result is about, only if the result names it. The model's name when the
    result contains it and it is a name, not a description; otherwise the employer the job board's
    address or the title gives; otherwise none.

    An anonymous posting became a market proposal named "AI security company" (owner's run,
    2026-09-30): a description the model wrote, not an organisation anyone can look up."""
    claimed = (claimed or "").strip()
    if claimed and not _is_description(claimed) and _named_in(claimed, result):
        return claimed
    fallback = _address_or_title_employer(result)
    if fallback and not _is_description(fallback) and _named_in(fallback, result):
        return fallback
    return None


_BUYER_ORGANISATION = re.compile(r"\b(?:in|at|for)\s+(?:a|an|the)?\s*(.+)$", re.I)


def buyer_organisation(buyer: str) -> str:
    """The kind of organisation in a segment's buyer description, as search words:
    *"MLOps lead in a regulated enterprise (finance, healthcare, gov)"* → *"regulated enterprise
    finance healthcare gov"*. Empty when the description names none."""
    match = _BUYER_ORGANISATION.search(buyer or "")
    if not match:
        return ""
    return " ".join(re.sub(r"[(),/]+", " ", match.group(1)).split()[:8])


def build_query(brief: dict, where: str) -> str:
    """The segment's own words. For job boards, what the buyer would hire for, and in what kind of
    organisation; elsewhere, the problem as the buyer says it.

    The organisation words were added 2026-09-30: built from the category terms alone, the two
    segments' job-board searches returned the same companies (Clariti Cloud, Firmus and Livefront
    turned up for either), and nothing in the query said *regulated*."""
    terms = [t for t in (brief.get("category_terms") or []) if t][:3]
    organisation = buyer_organisation(brief.get("buyer", ""))
    if where == "hiring":
        base = (" ".join(terms) + " engineer").strip() if terms else f"{brief['buyer']}"
        return f"{base} {organisation}".strip()
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


# The judge reports FACTS and the code decides (§5.3, reworked 2026-09-30). The first prompt asked
# for the verdict directly and called hiring for the problem "strong buyer evidence"; on job boards
# every result is hiring for the problem, so it passed all 13 of the owner's results at 80-90,
# including Vercel (building its own workflow product), OneTrust (a governance vendor) and two
# digital agencies, and placed a digital agency in "regulated enterprise".
ORG_TYPES = ("end_user", "vendor", "agency", "publisher", "other")

_JUDGE_PROMPT = """You check one web result against one market segment for a seller. Report facts; do not decide.
Use what you know about well-known organisations as well as the result text.

organisation: the organisation the result is about (the employer in a job posting, not the job board).
org_type, exactly one of:
  end_user  - an organisation that uses agents in its own business, or builds agent features INTO its
              own product in a different category, or builds an internal platform for its own use.
              It could buy the seller's work to do so.
  vendor    - an organisation whose product FOR SALE is itself in the seller's category: an agent runtime,
              agent or workflow orchestration platform, or AI agent infrastructure sold to others.
              A company adding agents to its CRM, banking or marketing product is NOT a vendor.
  agency    - a consultancy, agency or systems integrator that builds for clients
  publisher - a media site, analyst, blog, listicle or directory
  other     - anything else
matches_buyer: true only if the organisation fits the segment's BUYER description, including any
  organisation type, size or industry it names (e.g. "regulated enterprise" means finance, healthcare,
  government or similar; a software agency is not one). false if the result gives no reason to think so.
problem_evidence: true only if the result shows this organisation has the segment's problem.
fit_score, intent_score, data_quality_score, overall_score: 0-100, anchored:
  85-100 only when org_type is end_user AND matches_buyer AND problem_evidence all clearly hold;
  60-84 when those hold but one is uncertain; below 60 otherwise.
reasoning: one sentence naming the deciding fact.

Return ONLY a JSON object with those keys."""

#: What a non-buyer is proposed as. An end user that fails the segment is not evidence about it.
KIND_FOR_ORG_TYPE = {"vendor": "alternative", "agency": "intermediary", "publisher": "voice"}


def classify(verdict: dict) -> str:
    """"buyer", an entry kind, or "drop": the decision the judge's facts imply."""
    org_type = str(verdict.get("org_type") or "").strip().lower()
    if org_type == "end_user":
        if verdict.get("matches_buyer") is True and verdict.get("problem_evidence") is True:
            return "buyer"
        return "drop"
    return KIND_FOR_ORG_TYPE.get(org_type, "drop")


#: The judge's model, at temperature 0. gpt-4o-mini at its default temperature, on a title and a
#: snippet, flipped the same company between runs (Superserve: vendor on one, buyer at 80 on the
#: next) and did not know Robots and Pencils is an agency (owner's run, 2026-09-30). About $0.10 per
#: Find buyers press at ~28 calls, against ~$0.01 before. `AINDY_SEGMENT_JUDGE_MODEL` overrides.
JUDGE_MODEL = "gpt-4o"


def _judge_model() -> str:
    import os

    return (os.getenv("AINDY_SEGMENT_JUDGE_MODEL") or "").strip() or JUDGE_MODEL


def judge_result(result: dict, brief: dict) -> dict:
    """One model call: the facts about a result (§5.3). `classify` turns them into a decision."""
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
    model = _judge_model()
    completion = perform_external_call(
        service_name="openai",
        endpoint="chat.completions.create",
        model=model,
        method="openai.chat",
        extra={"purpose": "segment_lead_judgement", "segment": brief["name"]},
        operation=lambda: chat_completion(
            get_openai_client(),
            model=model,
            messages=[{"role": "system", "content": _JUDGE_PROMPT}, {"role": "user", "content": user}],
            timeout=settings.OPENAI_CHAT_TIMEOUT_SECONDS,
            temperature=0,
        ),
    )
    text = (completion.choices[0].message.content or "").strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(match.group(0) if match else text)


def _existing_lead_id(db: Session, user_id: Any, url: str) -> int | None:
    import uuid

    from apps.search.models.leadgen_model import LeadGenResult

    row = (
        db.query(LeadGenResult.id)
        .filter(LeadGenResult.user_id == uuid.UUID(str(user_id)), LeadGenResult.url == url)
        .first()
    )
    return row[0] if row else None


#: Saved leads re-judged per search, at most: one model call each.
REJUDGE_LIMIT = 20


def _unseen_segment_leads(db: Session, user_id: Any, segment_id: str, seen: set[str]) -> list[tuple]:
    """The segment's saved leads, not returned by this search, with no outreach begun."""
    import uuid

    from apps.search.models.lead_action import LeadAction
    from apps.search.models.leadgen_model import LeadGenResult

    acted = {row[0] for row in db.query(LeadAction.lead_id).filter(LeadAction.lead_id.isnot(None))}
    rows = (
        db.query(LeadGenResult.id, LeadGenResult.url, LeadGenResult.company, LeadGenResult.context)
        .filter(LeadGenResult.user_id == uuid.UUID(str(user_id)), LeadGenResult.segment_id == segment_id)
        .order_by(LeadGenResult.id)
        .all()
    )
    return [tuple(r) for r in rows if r[1] not in seen and r[0] not in acted][:REJUDGE_LIMIT]


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
    from apps.search.services.leadgen_service import retire_lead, save_lead

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
    leads, proposed, known, dropped, failed, retired = [], [], [], [], 0, 0
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
        context = " ".join(p for p in (row.get("title"), row.get("snippet")) if p)[:1000]
        decision = classify(verdict)
        organisation = grounded_organisation(str(verdict.get("organisation") or ""), row)
        if organisation is None:
            # Nothing in the result names an organisation: not a lead, and not a market entry.
            dropped.append({"name": str(verdict.get("organisation") or ""), "kind": "unnamed",
                            "org_type": str(verdict.get("org_type") or ""),
                            "reason": "the result does not name the organisation"})
            continue
        if decision == "buyer":
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
        # A lead saved by an earlier, laxer judgement and not a buyer now leaves the leads (unless
        # outreach has begun on it, which retire_lead refuses), so re-running a search re-files it.
        earlier = _existing_lead_id(db, user_id, url)
        if earlier is not None and retire_lead(user_id=str(user_id), lead_id=earlier, db=db):
            retired += 1
        if decision in ENTITY_KINDS and propose is not None:
            outcome = propose(user_id=str(user_id), db=db, args={
                "kind": decision, "name": organisation, "url": url, "segment": brief["name"],
                "note": str(verdict.get("reasoning") or "")[:500] or None,
                "evidence": [{"claim": context[:400], "source_url": url}],
            })
            if outcome.get("proposed"):
                proposed.append({"kind": decision, "name": organisation})
            else:
                known.append({"kind": decision, "name": organisation})
            continue
        dropped.append({"name": organisation, "kind": decision,
                        "org_type": str(verdict.get("org_type") or ""), "reason": str(verdict.get("reasoning") or "")[:200]})
    # The segment's saved leads this search did not return are judged again too, on what was stored
    # (title and snippet). Without this a lead saved by an earlier, laxer judgement would stay a lead
    # until its posting happened to come back: the owner's first run saved 13, and the reworked
    # query returns different postings.
    rejudged = 0
    for lead_id, url, company, context in _unseen_segment_leads(db, user_id, brief["id"], seen):
        try:
            verdict = judge({"title": company, "url": url, "snippet": context}, brief)
        except Exception as exc:
            failed += 1
            logger.warning("[segment_search] re-judgement failed for %s: %s", url, exc)
            continue
        rejudged += 1
        decision = classify(verdict)
        organisation = grounded_organisation(str(verdict.get("organisation") or ""),
                                             {"title": company, "url": url, "snippet": context}) or company
        if decision == "buyer":
            save_lead(db, user_id=user_id, url=url, fields={
                key: _score(verdict, key) for key in ("fit_score", "intent_score", "data_quality_score", "overall_score")
            } | {"reasoning": str(verdict.get("reasoning") or "")[:1000]})
            continue
        if not retire_lead(user_id=str(user_id), lead_id=lead_id, db=db):
            continue  # outreach has begun on it; a person decides, not a re-judgement
        retired += 1
        if decision in ENTITY_KINDS and propose is not None:
            outcome = propose(user_id=str(user_id), db=db, args={
                "kind": decision, "name": organisation, "url": url, "segment": brief["name"],
                "note": str(verdict.get("reasoning") or "")[:500] or None,
                "evidence": [{"claim": (context or "")[:400], "source_url": url}],
            })
            if outcome.get("proposed"):
                proposed.append({"kind": decision, "name": organisation})
            else:
                known.append({"kind": decision, "name": organisation})
            continue
        dropped.append({"name": organisation, "kind": decision,
                        "org_type": str(verdict.get("org_type") or ""), "reason": str(verdict.get("reasoning") or "")[:200]})
    db.commit()
    return {
        "rejudged": rejudged,
        "segment": brief["name"],
        "segment_status": brief["status"],
        "where": where,
        "query": query,
        "leads": sorted(leads, key=lambda lead: lead["overall_score"] or 0, reverse=True),
        "count": len(leads),
        "proposed": proposed,
        # Non-buyers already in the market (a proposal open, or an entry confirmed): not asked twice.
        "already_known": known,
        "dropped": len(dropped),
        "dropped_detail": dropped,
        "retired": retired,
        "failed": failed,
    }
