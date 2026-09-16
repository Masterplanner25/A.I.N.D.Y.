"""
Search Execution Layer — act on discovered leads.

Leadgen discovered and scored leads but nothing consumed them: the pipeline stopped
at retrieve -> score -> store -> list. This service is the missing act-on-insight
half. It takes the scored ``LeadGenResult`` rows, selects the ones worth pursuing
behind a safety gate, drafts outreach for each, and records a tracked, revertible
``LeadAction`` — the same guarded-consumer template ARM's auto-tune uses.

Safe by construction:
  * ``draft`` channel (default) never contacts the lead — it produces a draft for
    review and, via the search public surface, for freelance to convert.
  * ``email`` channel is gated default-off (``AINDY_SEARCH_OUTREACH_SEND``). With the gate
    on it SENDS — through the runtime's ``email_channel.send_email`` (a registered ``email``
    connector, else ``AINDY_SMTP_*``), capability-gated by ``authorized_external_call`` — but
    only to a lead whose ``contact_email`` was entered by hand; a lead without a recipient
    stays ``queued``. A ``sent`` action cannot be reverted: outreach can't be un-sent.

The gate (``evaluate_lead_action_gate``) is a pure function, unit-tested without a DB.

Gate rules (all must pass for a lead to be actioned):
  * dedup        — a lead already actioned (non-reverted) is left alone
  * auto-suppress — a leadgen query the learning close judged non-converting is gated out
  * score        — overall_score must clear MIN_OVERALL_SCORE
  * data quality — data_quality_score must clear MIN_DATA_QUALITY
  * max per run  — at most MAX_ACTIONS_PER_RUN, highest-scoring first

Learning close: the static gate never checked whether actioned leads convert. ``execute``
first runs ``evaluate_outcomes`` — after an observation window each matured, non-reverted
action is judged on its in-domain conversion signal (a ``convert``/thumbs_up on the lead's
url in ``SearchResultFeedback``). Since outreach can't be un-sent, a segment (the leadgen
query) whose actioned leads consistently fail to convert is AUTO-SUPPRESSED forward — its
future leads are gated out — rather than reverted.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from AINDY.platform_layer.user_ids import require_user_id
from apps.search.models.lead_action import LeadAction
from apps.search.models.leadgen_model import LeadGenResult
from apps.search.models.result_feedback import SearchResultFeedback

logger = logging.getLogger(__name__)


# ── Gate policy ───────────────────────────────────────────────────────────────

MIN_OVERALL_SCORE = 60.0
MIN_DATA_QUALITY = 50.0
MAX_ACTIONS_PER_RUN = 5

# ── Learning close ────────────────────────────────────────────────────────────
# The static gate only trusts overall_score + data_quality — it never checked whether
# actioned leads actually convert. After OBSERVATION_HOURS each non-reverted action is
# judged on its in-domain conversion signal (a `convert`/thumbs_up on the lead's url in
# SearchResultFeedback). Outreach can't be un-sent, so a segment (the leadgen query) whose
# matured actions consistently fail to convert is AUTO-SUPPRESSED forward — future leads
# from it are gated out — rather than reverted.
OBSERVATION_HOURS = 72          # give an actioned lead time to convert before judging
SUPPRESS_MIN_OUTCOMES = 3       # need this many judged actions in a segment before suppressing
SUPPRESS_MAX_CONVERSION_RATE = 0.15  # suppress a segment whose judged conversion rate is <= this

_SEND_ENABLED_VALUES = {"1", "true", "yes", "on"}


def _outreach_send_enabled() -> bool:
    return os.getenv("AINDY_SEARCH_OUTREACH_SEND", "").strip().lower() in _SEND_ENABLED_VALUES


def evaluate_lead_action_gate(
    leads: list[dict],
    actioned_lead_ids: set,
    *,
    min_overall_score: float = MIN_OVERALL_SCORE,
    min_data_quality: float = MIN_DATA_QUALITY,
    max_actions: int = MAX_ACTIONS_PER_RUN,
    suppressed_segments: set | None = None,
) -> tuple[list[dict], list[dict]]:
    """
    Decide which scored leads warrant an outreach action. Pure: no I/O.
    Returns ``(selected, skipped)``.

    ``selected`` items: {lead_id, company, url, context, contact_email, query, score, data_quality, reason}
    ``skipped`` items:  {lead_id, company, reason}

    ``suppressed_segments`` — leadgen queries the learning close judged as consistently
    non-converting; their leads are gated out (auto-suppress) regardless of score.
    """
    selected: list[dict] = []
    skipped: list[dict] = []
    suppressed = suppressed_segments or set()

    # Highest-scoring first, so the per-run cap keeps the best leads.
    ranked = sorted(leads, key=lambda lead: (lead.get("overall_score") or 0), reverse=True)

    for lead in ranked:
        lead_id = lead.get("id")
        company = lead.get("company")
        overall = lead.get("overall_score") or 0
        data_quality = lead.get("data_quality_score")
        query = lead.get("query")

        if lead_id in actioned_lead_ids:
            skipped.append({"lead_id": lead_id, "company": company, "reason": "already actioned"})
            continue
        if query is not None and query in suppressed:
            skipped.append(
                {"lead_id": lead_id, "company": company,
                 "reason": "segment auto-suppressed (low conversion)"}
            )
            continue
        if overall < min_overall_score:
            skipped.append(
                {"lead_id": lead_id, "company": company,
                 "reason": f"below score threshold ({overall} < {min_overall_score})"}
            )
            continue
        if data_quality is not None and data_quality < min_data_quality:
            skipped.append(
                {"lead_id": lead_id, "company": company,
                 "reason": f"insufficient data quality ({data_quality} < {min_data_quality})"}
            )
            continue
        if len(selected) >= max_actions:
            skipped.append(
                {"lead_id": lead_id, "company": company,
                 "reason": f"exceeds max {max_actions} actions/run"}
            )
            continue

        selected.append(
            {
                "lead_id": lead_id,
                "company": company,
                "url": lead.get("url"),
                "context": lead.get("context"),
                "contact_email": lead.get("contact_email"),
                "query": query,
                "score": overall,
                "data_quality": data_quality,
                "reason": f"qualified (score {overall})",
            }
        )

    return selected, skipped


# ── Service ───────────────────────────────────────────────────────────────────

class LeadExecutionService:
    """Per-user consumer that turns scored leads into tracked outreach actions."""

    def __init__(self, db: Session, user_id: str):
        self.db = db
        self.user_id = require_user_id(user_id)
        self.user_uuid = uuid.UUID(str(self.user_id))

    # ── reads ─────────────────────────────────────────────────────────────────

    def _leads(self) -> list[dict]:
        rows = (
            self.db.query(LeadGenResult)
            .filter(LeadGenResult.user_id == self.user_uuid)
            .order_by(LeadGenResult.overall_score.desc(), LeadGenResult.id.desc())
            .all()
        )
        return [
            {
                "id": row.id,
                "company": row.company,
                "url": row.url,
                "context": row.context,
                "query": row.query,
                "overall_score": row.overall_score,
                "data_quality_score": row.data_quality_score,
                "contact_email": row.contact_email,
            }
            for row in rows
        ]

    def _actioned_lead_ids(self) -> set:
        rows = (
            self.db.query(LeadAction.lead_id)
            .filter(LeadAction.user_id == self.user_uuid, LeadAction.status != "reverted")
            .all()
        )
        return {row[0] for row in rows if row[0] is not None}

    def _conversion_signal(self, url: str | None, company: str | None) -> float:
        """In-domain conversion signal for an actioned lead: net feedback weight on its
        result_ref (url/company). A `convert` (+1.0) or `thumbs_up` reads as converted."""
        refs = [r for r in (url, company) if r]
        if not refs:
            return 0.0
        rows = (
            self.db.query(SearchResultFeedback.weight)
            .filter(
                SearchResultFeedback.user_id == self.user_uuid,
                SearchResultFeedback.result_ref.in_(refs),
            )
            .all()
        )
        return round(sum(float(w or 0.0) for (w,) in rows), 3)

    def _suppressed_segments(self) -> set:
        """Leadgen queries whose judged actions consistently fail to convert.

        Recomputed from recorded outcomes each run (no separate state) — a segment is
        suppressed once it has >= SUPPRESS_MIN_OUTCOMES judged actions and a conversion
        rate <= SUPPRESS_MAX_CONVERSION_RATE.
        """
        rows = (
            self.db.query(LeadAction.lead_query, LeadAction.outcome)
            .filter(
                LeadAction.user_id == self.user_uuid,
                LeadAction.outcome.isnot(None),
                LeadAction.lead_query.isnot(None),
            )
            .all()
        )
        totals: dict[str, list[int]] = {}  # segment -> [converted, total]
        for segment, outcome in rows:
            counts = totals.setdefault(segment, [0, 0])
            counts[1] += 1
            if outcome == "converted":
                counts[0] += 1
        suppressed = set()
        for segment, (converted, total) in totals.items():
            if total >= SUPPRESS_MIN_OUTCOMES and (converted / total) <= SUPPRESS_MAX_CONVERSION_RATE:
                suppressed.add(segment)
        return suppressed

    def plan(self) -> dict:
        """Dry run: which leads *would* be actioned, and what's gated."""
        suppressed = self._suppressed_segments()
        selected, skipped = evaluate_lead_action_gate(
            self._leads(), self._actioned_lead_ids(), suppressed_segments=suppressed
        )
        return {
            "selected": selected,
            "skipped": skipped,
            "would_act": bool(selected),
            "suppressed_segments": sorted(suppressed),
        }

    # ── writes ────────────────────────────────────────────────────────────────

    def execute(self, channel: str = "draft", trigger: str = "manual") -> dict:
        """Draft + record an action for each gated lead; on the `email` channel with the send
        gate on, deliver it to leads that carry a hand-entered `contact_email`.

        LEARN first: judge matured actions and refresh the auto-suppress set, so this run's
        gate already excludes segments that have proven non-converting.
        """
        learning = self.evaluate_outcomes()
        proposal = self.plan()
        selected = proposal["selected"]

        if not selected:
            return {
                "status": "no_action",
                "dry_run": False,
                "actions": [],
                "skipped": proposal["skipped"],
                "suppressed_segments": proposal["suppressed_segments"],
                "learning": learning,
                "count": 0,
            }

        status, note = self._resolve_channel(channel)
        sending = channel == "email" and _outreach_send_enabled()
        actions = []
        for item in selected:
            draft = self._draft_outreach(item)
            row = LeadAction(
                user_id=self.user_uuid,
                lead_id=item["lead_id"],
                company=item["company"],
                url=item.get("url"),
                lead_query=item.get("query"),
                channel=channel,
                status=status,
                draft_subject=draft["subject"],
                draft_body=draft["body"],
                decision_score=item["score"],
                decision_reason=item["reason"],
                trigger=trigger,
                note=note,
            )
            if sending:
                self._send(row, item.get("contact_email"))
            self.db.add(row)
            self.db.commit()
            self.db.refresh(row)
            actions.append(
                {
                    "action_id": row.id,
                    "lead_id": row.lead_id,
                    "company": row.company,
                    "status": row.status,
                    "channel": row.channel,
                }
            )

        return {
            "status": "executed",
            "dry_run": False,
            "actions": actions,
            "skipped": proposal["skipped"],
            "suppressed_segments": proposal["suppressed_segments"],
            "learning": learning,
            "count": len(actions),
        }

    def evaluate_outcomes(self, observation_hours: int = OBSERVATION_HOURS) -> dict:
        """LEARN step: judge each matured, non-reverted action on whether its lead converted
        (in-domain feedback signal), record the verdict, and report the segments the refreshed
        outcomes now auto-suppress. Idempotent — only actions past the window with no verdict yet.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=observation_hours)
        matured = (
            self.db.query(LeadAction)
            .filter(
                LeadAction.user_id == self.user_uuid,
                LeadAction.status != "reverted",
                LeadAction.outcome.is_(None),
                LeadAction.created_at <= cutoff,
            )
            .all()
        )
        summary = {"evaluated": 0, "converted": 0, "no_response": 0, "suppressed_segments": []}
        if not matured:
            summary["suppressed_segments"] = sorted(self._suppressed_segments())
            return summary

        now = datetime.now(timezone.utc)
        converted = 0
        for row in matured:
            signal = self._conversion_signal(row.url, row.company)
            outcome = "converted" if signal > 0 else "no_response"
            row.outcome = outcome
            row.outcome_signal = signal
            row.evaluated_at = now
            if outcome == "converted":
                converted += 1
        self.db.commit()

        summary["evaluated"] = len(matured)
        summary["converted"] = converted
        summary["no_response"] = len(matured) - converted
        summary["suppressed_segments"] = sorted(self._suppressed_segments())
        return summary

    def revert(self, action_id) -> dict:
        """Mark an action reverted so its lead is eligible again."""
        try:
            action_pk = int(action_id)
        except (TypeError, ValueError):
            return {"status": "not_found", "action_id": str(action_id)}

        row = (
            self.db.query(LeadAction)
            .filter(LeadAction.id == action_pk, LeadAction.user_id == self.user_uuid)
            .first()
        )
        if row is None:
            return {"status": "not_found", "action_id": action_pk}
        if row.status == "reverted":
            return {"status": "already_reverted", "action_id": row.id}
        if row.status == "sent":
            # Outreach can't be un-sent. Reverting would make the lead eligible again and the
            # next run would email the same person twice; the action stays as the record.
            return {"status": "sent_cannot_revert", "action_id": row.id, "lead_id": row.lead_id}

        from datetime import datetime, timezone

        row.status = "reverted"
        row.reverted_at = datetime.now(timezone.utc)
        self.db.commit()
        return {"status": "reverted", "action_id": row.id, "lead_id": row.lead_id}

    def history(self, limit: int = 20) -> list[dict]:
        rows = (
            self.db.query(LeadAction)
            .filter(LeadAction.user_id == self.user_uuid)
            .order_by(LeadAction.created_at.desc(), LeadAction.id.desc())
            .limit(limit)
            .all()
        )
        return [self._to_dict(row) for row in rows]

    # ── channels + drafting ─────────────────────────────────────────────────────

    @staticmethod
    def _resolve_channel(channel: str) -> tuple[str, str | None]:
        """Map a channel to its pre-send status. `email` with the gate on is then resolved per
        lead by `_send` (sent / failed / queued-no-recipient)."""
        if channel == "draft":
            return "drafted", None
        if channel == "email":
            if _outreach_send_enabled():
                return "queued", "send enabled; awaiting delivery"
            return "queued", "email send disabled (AINDY_SEARCH_OUTREACH_SEND off) — queued, not sent"
        if channel == "handoff":
            return "queued", "handed off for freelance conversion"
        return "drafted", f"unknown channel '{channel}', defaulted to draft"

    def _send(self, row: LeadAction, contact_email: str | None) -> None:
        """Deliver one drafted action through the runtime's email channel. Mutates `row` in place.

        The recipient is the lead's hand-entered `contact_email` and nothing else — no
        discovery, no guessing. `send_email` never raises: it returns `{success, route, error}`,
        and route is `connector` (a registered `email` connector) or `smtp` (`AINDY_SMTP_*`).
        """
        recipient = (contact_email or "").strip()
        if not recipient:
            row.status = "queued"
            row.note = "no recipient on lead — add a contact_email to send"
            return
        from AINDY.platform_layer.email_channel import send_email

        result = send_email(
            to=recipient,
            subject=row.draft_subject or f"Hello from {row.company or 'us'}",
            body=row.draft_body or "",
            db=self.db,
            user_id=str(self.user_uuid),
        )
        if result.get("success"):
            row.status = "sent"
            row.recipient = recipient
            row.sent_at = datetime.now(timezone.utc)
            row.note = f"sent via {result.get('route')}"
        else:
            row.status = "failed"
            row.note = f"send failed: {result.get('error')}"
            logger.warning("[lead_exec] send to %s failed: %s", recipient, result.get("error"))

    def _draft_outreach(self, item: dict) -> dict:
        """LLM-drafted outreach with a deterministic offline fallback."""
        try:
            return self._llm_draft(item)
        except Exception as exc:  # no key / circuit open / parse error -> template
            logger.info("[lead_exec] LLM draft unavailable, using template: %s", exc)
            return self._template_draft(item)

    @staticmethod
    def _llm_draft(item: dict) -> dict:
        from AINDY.config import settings
        from AINDY.platform_layer.external_call_service import perform_external_call
        from AINDY.platform_layer.openai_client import chat_completion, get_openai_client

        company = item.get("company") or "the team"
        context = (item.get("context") or "").strip()
        system_prompt = (
            "You are an outreach copywriter for an AI consulting studio. Write a short, "
            "specific, non-spammy first-touch email. Return ONLY JSON with keys "
            "'subject' and 'body'. No greeting placeholders like [Name]."
        )
        user_prompt = f"Company: {company}\nWhy they're a fit: {context}\nKeep the body under 120 words."

        completion = perform_external_call(
            service_name="openai",
            endpoint="chat.completions.create",
            model="gpt-4o-mini",
            method="openai.chat",
            extra={"purpose": "lead_outreach_draft", "company": company},
            operation=lambda: chat_completion(
                get_openai_client(),
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                timeout=settings.OPENAI_CHAT_TIMEOUT_SECONDS,
            ),
        )
        import json
        import re

        text = (completion.choices[0].message.content or "").strip()
        if not text.startswith("{"):
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                text = match.group(0)
        parsed = json.loads(text)
        subject = str(parsed.get("subject") or "").strip()
        body = str(parsed.get("body") or "").strip()
        if not subject or not body:
            raise ValueError("draft missing subject/body")
        return {"subject": subject, "body": body}

    @staticmethod
    def _template_draft(item: dict) -> dict:
        company = item.get("company") or "there"
        context = (item.get("context") or "").strip()
        hook = f" We noticed {context[:140]}" if context else ""
        subject = f"Quick idea for {company}"
        body = (
            f"Hi {company} team,\n\n"
            f"We help teams put AI to work on concrete outcomes.{hook}\n\n"
            "If it's useful, I'd be glad to share a couple of specific ideas tailored to "
            "what you're building. Open to a short conversation?\n\n"
            "Best,\nA.I.N.D.Y."
        )
        return {"subject": subject, "body": body}

    @staticmethod
    def _to_dict(row: LeadAction) -> dict:
        return {
            "id": row.id,
            "lead_id": row.lead_id,
            "company": row.company,
            "url": row.url,
            "channel": row.channel,
            "status": row.status,
            "lead_query": row.lead_query,
            "draft_subject": row.draft_subject,
            "draft_body": row.draft_body,
            "decision_score": row.decision_score,
            "decision_reason": row.decision_reason,
            "trigger": row.trigger,
            "note": row.note,
            "recipient": row.recipient,
            "sent_at": row.sent_at.isoformat() if row.sent_at else None,
            "outcome": row.outcome,
            "outcome_signal": row.outcome_signal,
            "evaluated_at": row.evaluated_at.isoformat() if row.evaluated_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "reverted_at": row.reverted_at.isoformat() if row.reverted_at else None,
        }
