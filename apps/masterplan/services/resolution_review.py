"""The Resolution Check, phase B — `RESOLUTION_CHECK_SPEC.md` §3, §5, §6.

Three things the first live check (2026-09-30) asked for:

1. **Claims to settle.** Most of what the engines said could be neither confirmed nor contradicted by
   the owner's facts (Claude made 12 such claims about Masterplan Infinite Weave alone). They go to the
   owner, grouped so a claim three engines made is asked once: *true* becomes a confirmed fact, *false* a
   denied one the judge then marks incorrect, *skip* is not asked again. The ground truth grows from the
   owner's answers, never from the engines'.
2. **A weekly check under a ceiling.** RippleTrace's paid sweep was retired for cost, so the check
   refuses to start when the month's estimated spend plus the run's estimate would pass the ceiling
   ($10 by default, decision 3). Costs are estimates per call, not the provider's bill.
3. **A trend.** Per entity and engine, across runs: is it resolving, how much does it cover, does it connect.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from AINDY.platform_layer.user_ids import parse_user_id
from apps.masterplan.work_model import ResolutionAnswer, ResolutionClaim, ResolutionRun, Work

logger = logging.getLogger(__name__)

DECISIONS = ("true", "false", "skip")
CLAIM_RUNS = 3
CLAIMS_SHOWN = 40
SIMILAR = 0.5
CONTAINED = 0.75
WEEKLY_AFTER_DAYS = 6
TREND_RUNS = 8

#: Estimated cost of one call, in US dollars (published per-call prices, 2026-09-30; not the bill).
UNIT_COST_USD = {"perplexity": 0.008, "openai": 0.03, "claude": 0.02, "judge": 0.008}
DEFAULT_CEILING_USD = 10.0

_STOP = {"the", "and", "for", "with", "that", "this", "from", "are", "was", "its", "his", "her", "has", "have",
         "into", "onto", "about", "also", "which", "who", "what", "their", "they", "them", "been", "being"}


def _uid(user_id: Any):
    uid = parse_user_id(user_id)
    if uid is None:
        raise HTTPException(status_code=401, detail="user_id is required")
    return uid


def _refuse(status: int, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": "resolution_refused", "message": message})


# ── Claims ────────────────────────────────────────────────────────────────────────────────


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2 and w not in _STOP}


def claim_key(text: str) -> str:
    return " ".join(sorted(_tokens(text)))[:400]


def _similar(a: set[str], b: set[str]) -> bool:
    """Same claim, reworded: enough shared words overall, or the shorter almost wholly inside the longer.
    Overlap alone (0.6) grouped almost nothing on the first live check: 98 claims, each from one engine."""
    if not (a and b):
        return False
    shared = len(a & b)
    return shared / len(a | b) >= SIMILAR or shared / min(len(a), len(b)) >= CONTAINED


#: An engine saying it found nothing is not a claim about the entity.
_NOT_A_CLAIM = re.compile(
    r"\b(?:was(?:n'?t| not) able to find|unable to (?:find|locate|confirm)|could(?:n'?t| not) (?:find|confirm)"
    r"|no (?:widely |commonly )?(?:recogni[sz]ed|documented|known)|does(?:n'?t| not) appear to (?:correspond|be|refer)"
    r"|not (?:widely|commonly) (?:documented|known|recogni[sz]ed)|(?:can'?t|cannot) (?:find|confirm))",
    re.I,
)
_DASHES = re.compile(r"[‐‑‒–—]")


def _about(text: str, subject: str, names: dict[str, str]) -> str:
    """The entity a claim is about: the one it names first, else the question's subject. An answer to
    "How are A.I.N.D.Y. and Aindy-runtime related?" makes claims about both."""
    lowered = _DASHES.sub("-", text).lower()
    found = [(lowered.find(name.lower()), -len(name), work_id) for work_id, name in names.items()
             if name and lowered.find(name.lower()) >= 0]
    return min(found)[2] if found else subject


def decided_claims(db: Session, uid) -> dict[str, dict[str, list[str]]]:
    """The owner's answers, per Work: {"true": [...], "false": [...], "skip": [...]}."""
    out: dict[str, dict[str, list[str]]] = {}
    for row in db.query(ResolutionClaim).filter(ResolutionClaim.user_id == uid).all():
        out.setdefault(row.work_id, {"true": [], "false": [], "skip": []})[row.decision].append(row.claim)
    return out


def pending_claims(db: Session, user_id: Any, *, limit: int = CLAIMS_SHOWN) -> dict:
    """Unverifiable claims from the last few checks, grouped, most-repeated first, minus any the owner
    has already answered."""
    uid = _uid(user_id)
    runs = (db.query(ResolutionRun).filter(ResolutionRun.user_id == uid, ResolutionRun.status == "done")
            .order_by(ResolutionRun.created_at.desc()).limit(CLAIM_RUNS).all())
    names = {w.id: w.name for w in db.query(Work).filter(Work.user_id == uid).all()}
    answered: dict[str, list[set[str]]] = {}
    for work_id, by_decision in decided_claims(db, uid).items():
        answered[work_id] = [_tokens(c) for claims in by_decision.values() for c in claims]

    groups: list[dict] = []
    for run in runs:
        subjects = {q["key"]: q.get("subject") for q in run.questions or []}
        for answer in db.query(ResolutionAnswer).filter(ResolutionAnswer.run_id == run.id).all():
            subject = subjects.get(answer.question_key)
            if subject not in names:
                continue
            for claim in (answer.judgement or {}).get("claims") or []:
                if not isinstance(claim, dict) or claim.get("status") != "unverifiable":
                    continue
                text = str(claim.get("text") or "").strip()
                if _NOT_A_CLAIM.search(text):
                    continue
                work_id = _about(text, subject, names)
                tokens = _tokens(text)
                if not tokens or any(_similar(tokens, t) for t in answered.get(work_id, [])):
                    continue
                group = next((g for g in groups if g["work_id"] == work_id and _similar(tokens, g["_tokens"])), None)
                if group is None:
                    groups.append({"work_id": work_id, "work": names[work_id], "claim": text, "_tokens": tokens,
                                   "engines": {answer.engine}, "count": 1})
                else:
                    group["count"] += 1
                    group["engines"].add(answer.engine)
                    if len(text) < len(group["claim"]):
                        group["claim"] = text  # the plainest wording
    groups.sort(key=lambda g: (-len(g["engines"]), -g["count"], g["work"]))
    shown = [{"work_id": g["work_id"], "work": g["work"], "claim": g["claim"], "engines": sorted(g["engines"]),
              "count": g["count"]} for g in groups[:limit]]
    return {"claims": shown, "pending": len(groups)}


def decide_claim(db: Session, user_id: Any, *, work_id: str, claim: str, decision: str) -> dict:
    uid = _uid(user_id)
    decision = str(decision or "").strip().lower()
    if decision not in DECISIONS:
        raise _refuse(422, f"decision must be one of: {', '.join(DECISIONS)}")
    claim = str(claim or "").strip()
    if not claim:
        raise _refuse(422, "which claim?")
    if db.query(Work).filter(Work.id == work_id, Work.user_id == uid).first() is None:
        raise _refuse(404, "work not found")
    row = ResolutionClaim(user_id=uid, work_id=work_id, claim=claim[:2000], claim_key=claim_key(claim),
                          decision=decision)
    db.add(row)
    db.commit()
    return {"work_id": work_id, "claim": row.claim, "decision": decision}


# ── Cost and the ceiling ──────────────────────────────────────────────────────────────────


def ceiling_usd() -> float:
    try:
        return float(os.getenv("AINDY_RESOLUTION_MONTHLY_CEILING_USD") or DEFAULT_CEILING_USD)
    except ValueError:
        return DEFAULT_CEILING_USD


def run_cost(calls: dict | None) -> float:
    return round(sum(UNIT_COST_USD.get(k, 0.0) * int(v or 0) for k, v in (calls or {}).items()), 4)


def estimate_cost(questions: list, engines: list) -> float:
    per_question = sum(UNIT_COST_USD.get(e, 0.0) for e in engines) + UNIT_COST_USD["judge"] * len(engines)
    return round(per_question * len(questions), 4)


def month_spend(db: Session, uid, *, now: datetime | None = None) -> float:
    """This calendar month's estimated spend; an open run counts at its full estimate."""
    now = now or datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = 0.0
    for run in db.query(ResolutionRun).filter(ResolutionRun.user_id == uid, ResolutionRun.created_at >= start).all():
        if run.status in ("pending", "running"):
            total += max(run_cost(run.calls), estimate_cost(run.questions or [], run.engines or []))
        else:
            total += run_cost(run.calls)
    return round(total, 4)


def check_ceiling(db: Session, uid, questions: list, engines: list) -> None:
    estimate = estimate_cost(questions, engines)
    spent = month_spend(db, uid)
    ceiling = ceiling_usd()
    if spent + estimate > ceiling:
        raise _refuse(422, f"this check (about ${estimate:.2f}) would take the month past its ${ceiling:.2f} "
                           f"ceiling (about ${spent:.2f} spent); it resets on the 1st")


# ── Weekly ────────────────────────────────────────────────────────────────────────────────


def weekly_resolution_checks() -> dict:
    """Scheduled job body: a core check for each owner who has run one, once a week, within the ceiling.
    Having run a check is the opt-in; nobody is checked who never asked for it."""
    from AINDY.db.database import SessionLocal
    from apps.masterplan.services.resolution_service import start_run

    db = SessionLocal()
    summary: dict[str, Any] = {"started": 0, "skipped": 0, "refused": 0}
    try:
        owners = {row[0] for row in db.query(ResolutionRun.user_id).distinct()}
        cutoff = datetime.now(timezone.utc) - timedelta(days=WEEKLY_AFTER_DAYS)
        for owner in owners:
            last = (db.query(ResolutionRun).filter(ResolutionRun.user_id == owner)
                    .order_by(ResolutionRun.created_at.desc()).first())
            created = last.created_at if last else None
            if created is not None and created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if last is not None and (last.status in ("pending", "running") or (created and created > cutoff)):
                summary["skipped"] += 1
                continue
            try:
                start_run(db, owner, "core")
                summary["started"] += 1
            except HTTPException as exc:
                summary["refused"] += 1
                logger.info("[resolution] weekly check not started for %s: %s", owner, exc.detail)
    except Exception as exc:
        logger.warning("[resolution] weekly run failed: %s", exc)
        summary["error"] = str(exc)
    finally:
        db.close()
    return summary


# ── Trend ─────────────────────────────────────────────────────────────────────────────────

_RESOLUTION_VALUE = {"resolved": 1.0, "mixed": 0.5, "wrong": 0.0, "unknown": 0.0}


def trend(db: Session, user_id: Any, *, limit: int = TREND_RUNS) -> dict:
    """Per question and engine, across the last few finished checks, oldest first."""
    uid = _uid(user_id)
    runs = list(reversed(db.query(ResolutionRun).filter(ResolutionRun.user_id == uid, ResolutionRun.status == "done")
                         .order_by(ResolutionRun.created_at.desc()).limit(limit).all()))
    rows: dict[str, dict] = {}
    for run in runs:
        texts = {q["key"]: q["text"] for q in run.questions or []}
        for answer in db.query(ResolutionAnswer).filter(ResolutionAnswer.run_id == run.id).all():
            s = answer.scores
            if not s or answer.question_key not in texts:
                continue
            row = rows.setdefault(texts[answer.question_key], {"question": texts[answer.question_key], "points": {}})
            row["points"].setdefault(answer.engine, []).append({
                "run_id": run.id,
                "resolution": s.get("resolution"),
                "value": _RESOLUTION_VALUE.get(s.get("resolution"), 0.0),
                "coverage": round(s["facts_covered"] / s["facts_total"], 2) if s.get("facts_total") else None,
                "connections": round(s["links_stated"] / s["links_total"], 2) if s.get("links_total") else None,
            })
    return {
        "runs": [{"id": r.id, "scope": r.scope, "date": r.created_at.isoformat() if r.created_at else None,
                  "cost_usd": run_cost(r.calls)} for r in runs],
        "questions": list(rows.values()),
    }
