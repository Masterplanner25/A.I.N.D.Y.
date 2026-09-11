"""Detect echoes of published content and record them as pings.

This is the half of rippletrace that ``content_ingest`` does not cover. Ingestion says
*what you published*; detection asks *who picked it up*. A ping means an echo somewhere
else — ``spread_score`` counts distinct platforms — so the only thing that legitimately
creates one is evidence of a reference on another site.

Method: search the web for the drop point's URL, plus its title as an exact phrase when
the title is distinctive enough to be worth searching. Each surviving result becomes one
ping. Three filters decide what survives, and each exists because without it the domain
would score fiction:

* **Same host is not an echo.** Your own site linking its own article, your feed page,
  your tag index — all match a URL search and none are ripples.
* **The drop point's own URL is not an echo of itself.**
* **A page published before you were is not a reaction to you.** When a result carries a
  date earlier than ``date_dropped``, it is prior art, not a ripple.

Pings are idempotent on ``sha256(drop_point_id | normalized_url)``, so re-running
detection re-finds the same references without inflating anything. That matters more
here than in ingestion: search results are stable, so an id-less implementation would
manufacture new spread on every single run.

Cost: one Perplexity call per drop point. The per-drop-point and batch routes are
user-initiated and always available; the *scheduled* sweep is opt-in behind
``AINDY_RIPPLE_MENTION_DETECTION`` so a background job cannot quietly spend money.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from apps.rippletrace.models import DropPointDB, PingDB
from apps.rippletrace.services.content_fetch import infer_platform, normalize_url
from apps.rippletrace.services.ping_verification import (
    BUDGET_EXHAUSTED_NOTE,
    DEBT_SETTLEMENT_SHARE,
    MAX_VERIFICATIONS_PER_RUN,
    REJECTED,
    UNVERIFIED,
    VERIFIED,
    verify_hit,
)
from apps.rippletrace.services.mention_search import (
    MentionSearchUnavailable,
    SearchHit,
    is_configured,
    search,
)
from apps.rippletrace.services.threadweaver import analyze_drop_point, classify_connection_type

logger = logging.getLogger(__name__)

DETECTION_FLAG = "AINDY_RIPPLE_MENTION_DETECTION"
_TRUTHY = {"1", "true", "yes", "on"}

DETECTION_JOB_INTERVAL_MINUTES = 360
# A drop point is not re-searched more often than this. Echoes accumulate over days,
# not minutes, and every check costs a call.
MIN_DETECTION_INTERVAL = timedelta(hours=24)
MAX_DROP_POINTS_PER_RUN = 10
# The provider's per-request maximum. Cost is per request, not per result, so asking
# for fewer buys nothing — and it actively distorts the domain: narrative score is
# `pings * ln(pings+1)`, so a 10-result cap puts a typical drop point at 11-14 after
# filtering, just under the 15 that `build_strategies` requires. The ceiling would have
# been mistaken for "not enough reach".
MAX_RESULTS_PER_DROP_POINT = 20
# Below this, a title is too generic to search as a phrase ("Second post" would match
# half the web). Such drop points are searched by URL only.
MIN_DISTINCTIVE_TITLE_CHARS = 25
MIN_DISTINCTIVE_TITLE_WORDS = 4

PING_TYPE = "mention"


def detection_job_enabled() -> bool:
    return (os.environ.get(DETECTION_FLAG) or "").strip().lower() in _TRUTHY


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def naive_utc(value: datetime | None) -> datetime | None:
    """Convert to UTC and drop tzinfo, for the legacy naive DateTime columns.

    ``drop_points.date_dropped`` and ``pings.date_detected`` are timezone-naive. Writing
    an aware value leaves the in-session object aware while anything re-read from the
    database comes back naive, and threadweaver then compares the two and raises
    ``can't compare offset-naive and offset-aware datetimes`` — which it swallows as a
    scoring failure, so the pings persist and every score silently stays 0. Normalizing
    at the write boundary keeps both sides of that comparison in the same world.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def ping_id_for(drop_point_id: str, url: str) -> str:
    digest = hashlib.sha256(f"{drop_point_id}|{normalize_url(url)}".encode("utf-8")).hexdigest()
    return f"ping-{digest[:32]}"


def _host(url: str) -> str:
    host = (urlparse(url or "").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _is_distinctive(title: str) -> bool:
    cleaned = (title or "").strip()
    return (
        len(cleaned) >= MIN_DISTINCTIVE_TITLE_CHARS
        and len(cleaned.split()) >= MIN_DISTINCTIVE_TITLE_WORDS
    )


def build_queries(drop_point: DropPointDB) -> list[str]:
    """URL first — it is the precise question ("who links to this?").

    The quoted title is added only when it is distinctive, because a generic phrase
    query returns unrelated pages that would each be recorded as spread.
    """
    queries: list[str] = []
    if drop_point.url:
        queries.append(drop_point.url)
    if _is_distinctive(drop_point.title or ""):
        queries.append(f'"{drop_point.title.strip()}"')
    return queries


def _as_aware(value: datetime | None) -> datetime | None:
    """drop_points timestamps are legacy naive columns; compare in UTC or not at all."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _hit_predates(hit: SearchHit, dropped_at: datetime | None) -> bool:
    from apps.rippletrace.services.content_fetch import _parse_timestamp

    if dropped_at is None or not hit.published:
        return False
    published = _parse_timestamp(hit.published)
    if published is None:
        return False
    return published < dropped_at


def filter_hits(
    hits: list[SearchHit], *, drop_point: DropPointDB
) -> tuple[list[SearchHit], dict[str, int]]:
    """Keep only plausible echoes. Returns ``(kept, rejection_counts)``.

    The counts are returned rather than logged away so the routes can report *why* a
    search that found ten results produced no pings — otherwise detection looks broken
    when it is in fact working correctly.
    """
    own_host = _host(drop_point.url or "")
    own_url = normalize_url(drop_point.url or "") if drop_point.url else ""
    dropped_at = _as_aware(drop_point.date_dropped)

    kept: list[SearchHit] = []
    rejected = {"same_host": 0, "self": 0, "predates": 0}
    for hit in hits:
        normalized = normalize_url(hit.url)
        if own_url and normalized == own_url:
            rejected["self"] += 1
            continue
        if own_host and _host(hit.url) == own_host:
            rejected["same_host"] += 1
            continue
        if _hit_predates(hit, dropped_at):
            rejected["predates"] += 1
            continue
        kept.append(hit)
    return kept, rejected


def _summary_for(hit: SearchHit) -> str:
    parts = [part for part in (hit.title, hit.snippet) if part]
    return " — ".join(parts)[:1000]


def _existing_ping(db: Session, *, drop_point: DropPointDB, hit: SearchHit) -> PingDB | None:
    identifier = ping_id_for(drop_point.id, hit.url)
    return db.query(PingDB).filter(PingDB.id == identifier).first()


def _record_ping(
    db: Session, *, drop_point: DropPointDB, hit: SearchHit,
    verification: str = "unverified", verification_note: str | None = None,
) -> tuple[PingDB, bool]:
    from apps.rippletrace.services.content_fetch import _parse_timestamp

    identifier = ping_id_for(drop_point.id, hit.url)
    existing = db.query(PingDB).filter(PingDB.id == identifier).first()
    if existing is not None:
        return existing, False

    summary = _summary_for(hit)
    detected_at = _parse_timestamp(hit.published or "") or _utcnow()
    ping = PingDB(
        id=identifier,
        drop_point_id=drop_point.id,
        ping_type=PING_TYPE,
        source_platform=infer_platform(hit.url),
        # pings.date_detected is a legacy naive column — see naive_utc().
        date_detected=naive_utc(detected_at),
        connection_summary=summary,
        external_url=normalize_url(hit.url),
        reaction_notes=None,
        user_id=drop_point.user_id,
        strength=1.0,
        connection_type=classify_connection_type(summary),
        verification=verification,
        verification_note=verification_note,
    )
    db.add(ping)
    return ping, True


def detect_for_drop_point(
    db: Session, drop_point: DropPointDB, *, user_id: str | None = None,
    verification_budget: int | None = None,
) -> dict[str, Any]:
    """Search for echoes of one drop point and record any new ones.

    Raises ``MentionSearchUnavailable`` when the search could not run — the caller must
    be able to tell that apart from a clean "no mentions found", which is why this does
    not swallow it into an empty result.
    """
    queries = build_queries(drop_point)
    if not queries:
        return {
            "drop_point_id": drop_point.id,
            "searched": False,
            "reason": "no_url_or_title",
            "created": 0,
            "found": 0,
        }

    hits = search(
        queries,
        max_results=MAX_RESULTS_PER_DROP_POINT,
        db=db,
        user_id=user_id or (str(drop_point.user_id) if drop_point.user_id else None),
    )
    kept, rejected = filter_hits(hits, drop_point=drop_point)

    # ★ Verify before writing (RIPPLE-PINGS-NOT-ECHOES-1). The search provider is an answer
    # engine: it returns the sources it used, which are topically related by construction and
    # almost never the piece searched for — 1 of 256 live pings pointed at the author. So the
    # page is fetched and checked for the drop point's URL or title.
    #
    # A candidate that demonstrably fails is NOT written: a page that does not cite you is not
    # a ripple. One that cannot be fetched is written as `unverified`, because "we looked and
    # it does not cite you" and "we could not look" are different answers and publishers who
    # refuse scripted requests produce the second constantly.
    created = 0
    verified = 0
    unverified = 0
    fetched = 0
    # ★ A ping written past the budget is a debt, not a decision. It carries
    # `BUDGET_EXHAUSTED_NOTE` and the next run with budget left pays it: fetch, then upgrade
    # to verified, leave it unverified with the real reason, or delete it because the page
    # turned out not to cite you. Every other existing ping is already decided and costs
    # nothing — a 403 re-fetched every run is the same refusal at the price of a fetch.
    revisited = {"verified": 0, "unverified": 0, "removed": 0}
    budget = verification_budget if verification_budget is not None else MAX_VERIFICATIONS_PER_RUN
    for hit in kept:
        existing = _existing_ping(db, drop_point=drop_point, hit=hit)
        if existing is not None and existing.verification_note != BUDGET_EXHAUSTED_NOTE:
            continue

        if budget <= 0:
            # Out of budget for this run rather than unverifiable in principle. Recorded as
            # unverified so the ping exists and simply does not score; a later run revisits
            # it — the branch above is what makes that sentence true.
            if existing is None:
                _record_ping(
                    db, drop_point=drop_point, hit=hit,
                    verification=UNVERIFIED, verification_note=BUDGET_EXHAUSTED_NOTE,
                )
                created += 1
                unverified += 1
            continue

        state, note = verify_hit(
            hit_url=hit.url,
            drop_url=drop_point.url or "",
            drop_title=drop_point.title,
            db=db,
            user_id=user_id or (str(drop_point.user_id) if drop_point.user_id else None),
        )
        budget -= 1
        fetched += 1

        if existing is not None:
            if state == REJECTED:
                # It never scored, so nothing the engines computed depended on it.
                db.delete(existing)
                revisited["removed"] += 1
                rejected["not_a_citation"] = rejected.get("not_a_citation", 0) + 1
            else:
                existing.verification = state
                existing.verification_note = note
                revisited[state] += 1
            continue

        if state == REJECTED:
            rejected["not_a_citation"] = rejected.get("not_a_citation", 0) + 1
            continue

        _record_ping(
            db, drop_point=drop_point, hit=hit, verification=state, verification_note=note
        )
        created += 1
        if state == VERIFIED:
            verified += 1
        else:
            unverified += 1

    drop_point.mentions_checked_at = _utcnow()
    db.commit()

    if created or revisited["verified"]:
        # Recompute narrative/velocity/spread once for the batch rather than per ping.
        # Best-effort: the pings are already durable, and a scoring failure must not
        # undo the detection that produced them.
        try:
            analyze_drop_point(drop_point.id, db)
        except Exception as exc:
            logger.warning(
                "[rippletrace] scoring failed after detection for %s: %s", drop_point.id, exc
            )

    db.refresh(drop_point)
    return {
        "drop_point_id": drop_point.id,
        "searched": True,
        "found": len(hits),
        "kept": len(kept),
        "created": created,
        # Reported separately because they mean different things, and a caller that sees
        # "created 6" has no way to tell whether any of them are evidence.
        "verified": verified,
        "unverified": unverified,
        "rejected": rejected,
        # Debts from earlier runs settled this run, and what it cost to settle them. The
        # batch decrements its budget by `fetched`, not by `kept` — a candidate that was
        # already decided was skipped for free.
        "revisited": revisited,
        "fetched": fetched,
        "narrative_score": drop_point.narrative_score or 0.0,
        "velocity_score": drop_point.velocity_score or 0.0,
        "spread_score": drop_point.spread_score or 0.0,
    }


def settle_verification_debts(
    db: Session, *, user_id: str | None, budget: int
) -> dict[str, Any]:
    """Pay budget debts directly: fetch the stranded pings, oldest first, up to `budget`.

    ★ #327 made a debt payable — but only when a later search returned the same URL for the
    same drop point, which an answer engine mostly does not. Measured 2026-09-11: the debt
    grew from 158 to 233 with detection running. This reads the debts off the table instead,
    so paying one never depends on the search. Each is fetched and then upgraded, left
    unverified with the real reason, or deleted — the same three outcomes as at detection.

    Returns the settlement counts and, as `remaining`, what is left of the budget for new
    candidates.
    """
    result = {"settled": 0, "verified": 0, "unverified": 0, "removed": 0, "remaining": budget}
    if budget <= 0:
        return result

    query = (
        db.query(PingDB, DropPointDB)
        .join(DropPointDB, DropPointDB.id == PingDB.drop_point_id)
        .filter(PingDB.verification_note == BUDGET_EXHAUSTED_NOTE)
    )
    if user_id:
        import uuid as _uuid

        try:
            query = query.filter(DropPointDB.user_id == _uuid.UUID(str(user_id)))
        except (TypeError, ValueError):
            return result
    rows = query.order_by(PingDB.date_detected.asc()).limit(budget).all()

    touched: set[str] = set()
    for ping, drop_point in rows:
        state, note = verify_hit(
            hit_url=ping.external_url or "",
            drop_url=drop_point.url or "",
            drop_title=drop_point.title,
            db=db,
            user_id=user_id or (str(drop_point.user_id) if drop_point.user_id else None),
        )
        result["settled"] += 1
        if state == REJECTED:
            db.delete(ping)
            result["removed"] += 1
        else:
            ping.verification = state
            ping.verification_note = note
            result[state] += 1
            if state == VERIFIED:
                touched.add(drop_point.id)
    db.commit()

    # A newly verified ping changes a score; nothing else here does.
    for drop_point_id in touched:
        try:
            analyze_drop_point(drop_point_id, db)
        except Exception as exc:
            logger.warning(
                "[rippletrace] scoring failed after settlement for %s: %s", drop_point_id, exc
            )
    result["remaining"] = max(0, budget - result["settled"])
    return result


def _due_drop_points(db: Session, *, user_id: str | None, limit: int) -> list[DropPointDB]:
    cutoff = _utcnow() - MIN_DETECTION_INTERVAL
    query = db.query(DropPointDB).filter(DropPointDB.url.isnot(None))
    if user_id:
        import uuid as _uuid

        try:
            query = query.filter(DropPointDB.user_id == _uuid.UUID(str(user_id)))
        except (TypeError, ValueError):
            return []
    query = query.filter(
        (DropPointDB.mentions_checked_at.is_(None))
        | (DropPointDB.mentions_checked_at < cutoff)
    )
    return (
        query.order_by(DropPointDB.mentions_checked_at.asc().nullsfirst())
        .limit(limit)
        .all()
    )


def detect_batch(
    db: Session, *, user_id: str | None, limit: int = MAX_DROP_POINTS_PER_RUN
) -> dict[str, Any]:
    """Run detection across this user's drop points that are due for a check."""
    if not is_configured():
        raise MentionSearchUnavailable(
            "PERPLEXITY_API_KEY is not set; ripple detection needs a Perplexity key."
        )

    due = _due_drop_points(db, user_id=user_id, limit=limit)
    summary = {
        "checked": 0, "created": 0, "verified": 0, "revisited": {}, "errors": 0, "results": [],
    }
    # ★ One verification budget for the whole batch, not one per drop point. Detection can
    # produce 200 candidates in a run (10 drop points x 20 results), and a per-drop budget
    # would multiply into an outbound crawl. Candidates past the budget are recorded
    # `unverified` rather than skipped, so nothing is lost — the next run revisits them,
    # which is why the budget is charged for fetches actually made and not for `kept`:
    # a candidate already decided on an earlier run is skipped for free.
    #
    # Debts first, up to their share; the search-path revisit below still applies to any
    # that remain and happen to be returned again.
    settlement = settle_verification_debts(
        db, user_id=user_id, budget=int(MAX_VERIFICATIONS_PER_RUN * DEBT_SETTLEMENT_SHARE)
    )
    summary["settled"] = {k: v for k, v in settlement.items() if k != "remaining"}
    summary["verified"] += settlement["verified"]
    budget = MAX_VERIFICATIONS_PER_RUN - settlement["settled"]
    for drop_point in due:
        try:
            outcome = detect_for_drop_point(
                db, drop_point, user_id=user_id, verification_budget=budget
            )
            budget = max(0, budget - int(outcome.get("fetched") or 0))
        except MentionSearchUnavailable as exc:
            # Provider-level failure (rate limit, bad key) will hit every remaining
            # drop point too — stop rather than burn the rest of the batch on it.
            summary["errors"] += 1
            summary["error"] = str(exc)
            break
        except Exception as exc:
            logger.warning("[rippletrace] detection failed for %s: %s", drop_point.id, exc)
            db.rollback()
            summary["errors"] += 1
            continue
        summary["checked"] += 1
        summary["created"] += int(outcome.get("created") or 0)
        # Reported separately: "created 12" says nothing about how much of it is evidence.
        summary["verified"] += int(outcome.get("verified") or 0)
        for key, value in (outcome.get("revisited") or {}).items():
            summary["revisited"][key] = summary["revisited"].get(key, 0) + int(value)
        summary["results"].append(outcome)
    return summary


# ── Scheduled sweep ───────────────────────────────────────────────────────────

_detect_lock = threading.Lock()


def detect_due_mentions() -> dict[str, Any]:
    """Scheduled job body. Opt-in: does nothing unless the flag is set.

    Takes no arguments to satisfy the runtime's job-handler contract and owns its own
    session, and carries a re-entrancy guard because the runtime registers app jobs
    without APScheduler's coalesce/max_instances.
    """
    if not detection_job_enabled():
        return {"skipped": True, "reason": "flag_disabled"}
    if not is_configured():
        return {"skipped": True, "reason": "no_api_key"}
    if not _detect_lock.acquire(blocking=False):
        logger.info("[rippletrace] mention detection already running; skipping this tick")
        return {"skipped": True, "reason": "already_running"}

    from AINDY.db.database import SessionLocal

    db = SessionLocal()
    try:
        # No user scope: the sweep covers every owner, oldest-checked first.
        return detect_batch(db, user_id=None, limit=MAX_DROP_POINTS_PER_RUN)
    except MentionSearchUnavailable as exc:
        logger.info("[rippletrace] mention detection unavailable: %s", exc)
        return {"skipped": True, "reason": str(exc)}
    except Exception as exc:
        logger.warning("[rippletrace] mention detection run failed: %s", exc)
        return {"skipped": True, "reason": str(exc)}
    finally:
        db.close()
        _detect_lock.release()
