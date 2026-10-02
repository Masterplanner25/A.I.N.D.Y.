"""
LEAD GENERATION SERVICE
------------------------------------
Module: B2B Lead Generation via AI Search Optimization
Purpose: Executes AI Search queries, evaluates leads with Infinity Algorithm logic,
and logs symbolic results into the A.I.N.D.Y. Memory Bridge.
"""

import os
import uuid
import logging
import json
import re

from AINDY.kernel.circuit_breaker import CircuitOpenError
from apps.search.services.search_scoring import score_lead_result
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from AINDY.memory.bridge import create_memory_node
from AINDY.platform_layer.app_runtime import queue_memory_capture
from apps.search.models.leadgen_model import LeadGenResult
from AINDY.platform_layer.external_call_service import perform_external_call
from apps.search.services.search_service import search_leads
from AINDY.platform_layer.trace_context import is_pipeline_active
from AINDY.platform_layer.openai_client import get_openai_client, chat_completion
from AINDY.config import settings

logger = logging.getLogger(__name__)

_FIXTURES_ENABLED_VALUES = {"1", "true", "yes", "on"}


class LeadSearchUnavailable(RuntimeError):
    """External lead retrieval failed. Distinct from 'retrieval found nothing'."""


def _fixtures_enabled() -> bool:
    """Whether the hardcoded demo leads may substitute for real retrieval.

    Default **off**, matching ``AINDY_SEARCH_OUTREACH_SEND`` — the other flag on this
    path that guards a real-world consequence.
    """
    return os.getenv("AINDY_LEADGEN_ALLOW_FIXTURES", "").strip().lower() in _FIXTURES_ENABLED_VALUES


# Three hardcoded companies that do not exist. Kept for local development only, and
# reachable exclusively via AINDY_LEADGEN_ALLOW_FIXTURES.
#
# These previously substituted for real results on ANY empty retrieval, and everything
# downstream then ran for real: a genuine GPT scoring call, a persisted `leadgen_results`
# row, and a memory node recalled as prior context on later runs. The action gate
# (`evaluate_lead_action_gate`) is correct and would have drafted outreach naming a
# company that does not exist — a correct gate over fabricated input still produces a
# confident wrong decision.
#
# Worth recording how this surfaced: a preserved run log reading
# "[LeadGen] Found 3 potential leads / 200 OK / Logged Acme AI Solutions (85)" was read
# during an archive audit as evidence the system had run in production. It had not —
# that is the fixture path, and "3 leads" is the fixture count. The failure mode
# produces artifacts indistinguishable from success, including a real upstream 200.
_DEV_FIXTURE_LEADS = [
    {
        "company": "Acme AI Solutions",
        "url": "https://acmeai.com",
        "context": "Acme AI is hiring ML engineers and seeking automation partners."
    },
    {
        "company": "Finovate Labs",
        "url": "https://finovatelabs.io",
        "context": "Finovate is implementing AI-driven fintech automation tools."
    },
    {
        "company": "HealthEdge Analytics",
        "url": "https://healthedge.ai",
        "context": "HealthEdge announced plans to adopt AI workflow automation."
    },
]


# --------------------------------------------------------
# 🧩 CORE FUNCTIONS
# --------------------------------------------------------

def run_ai_search(query: str, user_id: str = None, db=None):
    """
    Execute an AI-optimised lead search.

    Real retrieval runs through ``search_leads``; the hardcoded demo companies are
    development-only and reachable solely via ``AINDY_LEADGEN_ALLOW_FIXTURES``.

    Recalls past leadgen searches before querying and writes an outcome memory node
    after results are returned.

    Raises:
        LeadSearchUnavailable: retrieval failed and fixtures are disabled. Callers must
            not treat this as "no leads" — nothing should be scored, persisted or
            remembered from a failed search.

    Returns an empty list when retrieval succeeded and matched nothing, which is a
    genuine result and safe to persist as such.
    """
    import logging
    logger.info("[LeadGen] Running AI search for query: %s", query)

    # Step 1: Recall relevant past leadgen searches
    if user_id and db and not is_pipeline_active():
        try:
            from AINDY.db.dao.memory_node_dao import MemoryNodeDAO
            from AINDY.runtime.memory import MemoryOrchestrator

            orchestrator = MemoryOrchestrator(MemoryNodeDAO)
            context = orchestrator.get_context(
                site="app.search.leadgen",  # FR-49 (2.25.0): names this recall in aindy_memory_recall_failures_total
                user_id=user_id,
                query=query,
                task_type="strategy",
                db=db,
                max_tokens=500,
                metadata={
                    "tags": ["leadgen", "search", "outcome"],
                    "node_type": "outcome",
                    "limit": 2,
                },
            )
            if context.items:
                logger.info(
                    "[LeadGen] Recalled %s past searches for context.",
                    len(context.items),
                )
        except Exception as e:
            logger.warning("LeadGen memory recall failed: %s", e)

    # Step 2: External retrieval.
    #
    # Three outcomes, deliberately kept distinct — collapsing them is what made the old
    # behaviour dangerous:
    #
    #   retrieval raised      -> LeadSearchUnavailable. A failure is not a result.
    #   retrieval returned []  -> return []. Genuinely no leads is a true answer.
    #   fixtures enabled       -> the demo leads, and only then.
    #
    # The old code mapped both of the first two onto the fixtures, so "the search backend
    # is down" and "no companies matched" both produced three fabricated leads that were
    # then scored, persisted and remembered. Reporting a failure as an empty result would
    # be the same category error one step smaller — the null-vs-zero problem this
    # codebase has already met in `realized_revenue = 0.00`.
    retrieval_failed = None
    example_results = []
    try:
        payload = search_leads(query, db=db, user_id=user_id, max_results=3)
        # Only rows that point somewhere are leads. `search_leads` answers a failed or empty
        # retrieval with a url-less "External Search" row for its preview surface; scored and
        # saved, that row became a lead named "External Search" (reachable from the agent's
        # `leadgen.search` since 2026-09-28).
        example_results = [row for row in (payload.get("results") or []) if row.get("url")]
        if payload.get("retrieval_error") and not example_results:
            raise RuntimeError(payload["retrieval_error"])
    except Exception as e:
        retrieval_failed = e
        logger.warning("[LeadGen] External search failed: %s", e)

    if not example_results:
        if _fixtures_enabled():
            logger.warning(
                "[LeadGen] Using DEV FIXTURES — AINDY_LEADGEN_ALLOW_FIXTURES is set. "
                "These %s leads are fabricated and must not be treated as real "
                "(reason: %s).",
                len(_DEV_FIXTURE_LEADS),
                "retrieval raised" if retrieval_failed else "retrieval returned no results",
            )
            example_results = list(_DEV_FIXTURE_LEADS)
        elif retrieval_failed is not None:
            raise LeadSearchUnavailable(
                f"Lead retrieval failed and fixtures are disabled: {retrieval_failed}"
            ) from retrieval_failed
        else:
            # The previously silent branch: retrieval succeeded and matched nothing. Only
            # the exception path used to log at all, so an empty result set reached the
            # fixtures with no signal whatsoever.
            logger.info("[LeadGen] Retrieval returned no leads for query: %s", query)

    # Step 3: Write outcome memory node after results are gathered.
    # MemoryCaptureEngine-backed queue_memory_capture persists the search outcome.
    if user_id and db and not is_pipeline_active():
        try:
            result_count = len(example_results)
            top = example_results[0]["company"] if example_results else "none"
            memory_content = (
                f"LeadGen search: ‘{query[:100]}’. "
                f"Found {result_count} leads. "
                f"Top result: {top}"
            )
            queue_memory_capture(
                db=db,
                user_id=user_id,
                agent_namespace="leadgen",
                event_type="leadgen_search",
                content=memory_content,
                source="leadgen_search",
                tags=["leadgen", "search", "outcome", f"leads_{result_count}"],
                node_type="outcome",
            )
        except Exception as e:
            logging.warning(f"LeadGen memory write failed: {e}")

    return example_results


def score_lead(lead_data: dict):
    """
    Uses GPT-4o to generate structured lead quality scores with fallback parsing.
    """
    system_prompt = """
You are LeadQualificationAnalyst, an expert B2B analyst who scores potential leads for AI consulting services.
Return ONLY a valid JSON object with these exact keys:
fit_score, intent_score, data_quality_score, overall_score, reasoning.
Each score must be a number between 0 and 100.
"""

    lead_summary = f"Company: {lead_data['company']}\nURL: {lead_data['url']}\nContext: {lead_data['context']}"
    logger.info("[LeadGen] Scoring lead: %s", lead_data["company"])

    try:
        completion = perform_external_call(
            service_name="openai",
            endpoint="chat.completions.create",
            model="gpt-4o-mini",
            method="openai.chat",
            extra={"purpose": "lead_scoring", "company": lead_data["company"]},
            operation=lambda: chat_completion(
                get_openai_client(),
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt.strip()},
                    {"role": "user", "content": lead_summary},
                ],
                timeout=settings.OPENAI_CHAT_TIMEOUT_SECONDS,
            ),
        )

        text_output = (completion.choices[0].message.content or "").strip()

        # Extract JSON from messy output if needed
        if not text_output.startswith("{"):
            import re
            json_match = re.search(r"\{.*\}", text_output, re.DOTALL)
            if json_match:
                text_output = json_match.group(0)

        result = json.loads(text_output)
        return result

    except CircuitOpenError:
        raise
    except Exception as e:
        logger.warning("[LeadGen] Scoring failed for %s: %s", lead_data["company"], e)
        return {
            "fit_score": 0,
            "intent_score": 0,
            "data_quality_score": 0,
            "overall_score": 0,
            "reasoning": f"Parsing or API error: {e}"
        }



def save_lead(db: Session, *, user_id, url: str, fields: dict) -> LeadGenResult:
    """Save a scored lead, once per url per user. Flushes; the caller commits.

    A retried step or a repeated search used to save the same page again (run 195777b0 left three
    Onereach rows), and `leadgen.act` dedups by lead id, so each copy would have been drafted to.
    A lead already saved is re-scored in place; its hand-entered contact and its outreach history
    stay attached to the one row.
    """
    user_uuid = uuid.UUID(str(user_id))
    db_entry = (
        db.query(LeadGenResult)
        .filter(LeadGenResult.user_id == user_uuid, LeadGenResult.url == url)
        .order_by(LeadGenResult.id)
        .first()
    )
    if db_entry is not None:
        for key, value in fields.items():
            setattr(db_entry, key, value)
    else:
        db_entry = LeadGenResult(
            user_id=user_uuid,
            url=url,
            # LeadGenResult.created_at is a legacy naive DateTime column; SQLAlchemy may strip tzinfo here.
            created_at=datetime.now(timezone.utc),
            **fields,
        )
        db.add(db_entry)
    db.flush()
    return db_entry


def create_lead_results(db: Session, query: str, user_id: str = None):
    """
    Runs the full pipeline:
    1. Perform AI Search (with memory recall + write)
    2. Score each lead
    3. Store results in database
    4. Log symbolic traces into Memory Bridge
    """
    if not user_id:
        raise ValueError("user_id is required to create lead results")
    results = []
    leads = run_ai_search(query, user_id=user_id, db=db)
    logger.info("[LeadGen] Found %s potential leads", len(leads))

    for lead in leads:
        score = score_lead(lead)
        search_score = score_lead_result(
            overall_score=score.get("overall_score"),
            fit_score=score.get("fit_score"),
            intent_score=score.get("intent_score"),
            data_quality_score=score.get("data_quality_score"),
        )

        fields = {
            "query": query,
            "company": lead["company"],
            "context": lead["context"],
            "fit_score": score["fit_score"],
            "intent_score": score["intent_score"],
            "data_quality_score": score["data_quality_score"],
            "overall_score": score["overall_score"],
            "reasoning": score["reasoning"],
        }
        db_entry = save_lead(db, user_id=user_id, url=lead["url"], fields=fields)
        db.commit()
        db.refresh(db_entry)

        # 🧠 Log symbolic memory node. Reached only outside a pipeline, which until 2026-09-28 meant
        # never: the Search page runs inside one. The agent's `leadgen.search` runs in the Nodus
        # worker, outside one, and its first call (run 195777b0) failed here because `node_type` was
        # not passed and `memory_nodes.node_type` is NOT NULL. The step was retried, and each retry
        # saved the first lead again before failing. A note is a side effect, so it may not undo a
        # lead that is already scored and saved.
        if not is_pipeline_active():
            try:
                create_memory_node(
                    content=f"Lead Discovered: {lead['company']} | {lead['context']} | Score: {score['overall_score']}",
                    source="leadgen",
                    tags=["leadgen", "aindy", "infinity", "ai-search"],
                    db=db,
                    user_id=user_id,
                    node_type="outcome",
                )
            except Exception as exc:
                db.rollback()
                logger.warning("[LeadGen] memory note for %s failed (non-fatal): %s", lead["company"], exc)

        logger.info("[LeadGen] Logged %s (%s)", lead["company"], score["overall_score"])
        results.append((db_entry, search_score))

    results.sort(key=lambda item: item[1], reverse=True)
    return results


def unactioned_leads(*, user_id: str, db: Session) -> list[dict]:
    """Saved leads no outreach was ever made for. Masterplan proposes them as market entities
    (`MARKET_MODEL_SPEC.md` §4.1): the first three the agent saved were a competitor's listicle, an
    analyst's article and a trade-press story, market research filed as leads (run 8b75d75d)."""
    from apps.search.models.lead_action import LeadAction

    uid = uuid.UUID(str(user_id))
    acted = {row.lead_id for row in db.query(LeadAction.lead_id).filter(LeadAction.lead_id.isnot(None))}
    rows = (
        db.query(LeadGenResult)
        .filter(LeadGenResult.user_id == uid)
        .order_by(LeadGenResult.id.asc())
        .all()
    )
    return [
        {"id": row.id, "company": row.company, "url": row.url, "context": row.context,
         "query": row.query, "overall_score": row.overall_score}
        for row in rows
        if row.id not in acted
    ]


def retire_lead(*, user_id: str, lead_id: int, db: Session) -> bool:
    """Remove a saved lead the owner has re-filed as market research. Never one with outreach."""
    from apps.search.models.lead_action import LeadAction

    uid = uuid.UUID(str(user_id))
    row = db.query(LeadGenResult).filter(LeadGenResult.id == lead_id, LeadGenResult.user_id == uid).first()
    if row is None:
        return False
    if db.query(LeadAction.id).filter(LeadAction.lead_id == row.id).first() is not None:
        return False
    db.delete(row)
    db.flush()
    return True


def list_leads(db: Session, user_id: str) -> list[dict]:
    """Return all persisted LeadGenResult rows for a user, newest first."""
    from apps.search.models.leadgen_model import LeadGenResult

    rows = (
        db.query(LeadGenResult)
        .filter(LeadGenResult.user_id == uuid.UUID(str(user_id)))
        .order_by(LeadGenResult.created_at.desc(), LeadGenResult.id.desc())
        .all()
    )
    return [
        {
            "id": row.id,
            "query": row.query,
            "company": row.company,
            "url": row.url,
            "context": row.context,
            "contact_email": row.contact_email,
            "fit_score": row.fit_score,
            "intent_score": row.intent_score,
            "search_score": row.overall_score,
            "reasoning": row.reasoning,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


_EMAIL_SHAPE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def set_lead_contact(db: Session, *, user_id: str, lead_id: int, contact_email: str | None) -> dict | None:
    """Record (or clear, with None/"") the hand-entered recipient for one of the user's leads.

    The only way an address gets onto a lead. Returns the lead dict, or None if the lead is not
    the user's. Raises ValueError on a malformed address — the route maps that to 422.
    """
    from apps.search.models.leadgen_model import LeadGenResult

    cleaned = (contact_email or "").strip() or None
    if cleaned is not None and not _EMAIL_SHAPE.match(cleaned):
        raise ValueError("contact_email is not an email address")
    row = (
        db.query(LeadGenResult)
        .filter(LeadGenResult.id == int(lead_id), LeadGenResult.user_id == uuid.UUID(str(user_id)))
        .first()
    )
    if row is None:
        return None
    row.contact_email = cleaned
    db.commit()
    db.refresh(row)
    return {"id": row.id, "company": row.company, "url": row.url, "contact_email": row.contact_email}

