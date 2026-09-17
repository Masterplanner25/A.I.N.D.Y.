"""Record a citation the author found — and verify it before it counts.

`RIPPLE-PINGS-NOT-ECHOES-1`, decided 2026-09-16: the automated mention sweep is retired as a
product decision. The pipeline was proven (three measurements, 200 pages fetched and read on the
last, 0 verified of 620) and so was the economics: a phrase-indexing provider costs ~$65/month at
the sweep's cadence, and the owner's own experience is three citations in eighteen months of
publishing, every one found by accident. Discovery is the rare, expensive half. Recording is the
half this system can do honestly and for nothing — the same shape as #369's hand-entered contact.

So: the author pastes the URL of a page they found citing a drop point. The page is fetched and
checked with the SAME verifier detection used (`ping_verification.page_cites`: does the page
contain the drop point's URL or its distinctive title?). Three outcomes, and they are the
verifier's three, not new ones:

  verified    — it cites you; written as a `verified` ping, and it SCORES
  rejected    — we fetched it and it does not reference the drop point; NOT written, and the
                caller is told why. An author's say-so is not evidence; the page is.
  unverified  — the publisher refused a scripted fetch, or the page has no readable text (a
                JavaScript-rendered body). Written as `unverified` with the reason, so it is
                kept without inflating anything; it does not score.

The ping id is `ping_id_for(drop_point, url)`, the same identity detection uses, so a citation
recorded by hand and the same page found by a future sweep are one row. Recording a page that
already exists as `unverified` re-verifies it and may upgrade it.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from apps.rippletrace.models import DropPointDB, PingDB
from apps.rippletrace.services.content_fetch import (
    ContentFetchError,
    fetch_url,
    infer_platform,
    normalize_url,
    parse_page_metadata,
    strip_html,
)
from apps.rippletrace.services.ping_verification import (
    REJECTED,
    UNVERIFIED,
    VERIFIED,
    page_cites,
)
from apps.rippletrace.services.ripple_detection import naive_utc, ping_id_for
from apps.rippletrace.services.threadweaver import analyze_drop_point, classify_connection_type

logger = logging.getLogger(__name__)

#: Distinguishes a citation the author brought from one a sweep found (`mention`).
PING_TYPE_CITATION = "citation"

#: `verification_note` for a hand-recorded, verified citation — the provenance the row carries.
RECORDED_BY_AUTHOR = "recorded by the author; page fetched and confirmed to cite the drop point"


class NotACitation(ValueError):
    """The page was fetched and read, and it does not reference the drop point."""


def _same_page(a: str, b: str) -> bool:
    """Host + path, ignoring scheme, `www.`, query and fragment — a page cannot cite itself,
    however it is spelled. `normalize_url` keeps non-tracker queries on purpose (for many sites
    the query IS the document), which is the wrong tool for "is this the same piece"."""
    from urllib.parse import urlparse

    def key(url: str) -> tuple[str, str]:
        parsed = urlparse((url or "").strip())
        host = (parsed.hostname or "").lower()
        host = host[4:] if host.startswith("www.") else host
        return host, (parsed.path or "/").rstrip("/") or "/"

    return key(a) == key(b)


def _check(url: str, *, drop_point: DropPointDB, db: Session, user_id: str | None):
    """Fetch once, decide once. Returns ``(state, note, page_title)``."""
    try:
        result = fetch_url(url, db=db, user_id=user_id, purpose="rippletrace_citation_record")
    except ContentFetchError as exc:
        return UNVERIFIED, str(exc)[:200], ""
    except Exception as exc:  # pragma: no cover - defensive, mirrors verify_hit
        logger.warning("[rippletrace] citation fetch failed for %s: %s", url, exc)
        return UNVERIFIED, "fetch failed", ""

    html = result.text or ""
    text = strip_html(html)
    if not text.strip():
        return UNVERIFIED, "no readable text", ""

    title = ""
    try:
        title = parse_page_metadata(html, url).title or ""
    except Exception:  # pragma: no cover - metadata is a nicety, never a reason to fail
        title = ""

    if page_cites(text, drop_url=drop_point.url or "", drop_title=drop_point.title):
        return VERIFIED, RECORDED_BY_AUTHOR, title
    return REJECTED, "page does not reference the drop point", title


def record_citation(
    db: Session, *, drop_point: DropPointDB, url: str, user_id: str | None
) -> dict:
    """Verify and record a page the author says cites ``drop_point``.

    Raises ``NotACitation`` when the page was read and does not reference the drop point —
    nothing is written in that case. Never writes a `verified` row without a fetch that saw
    the reference.
    """
    cleaned = (url or "").strip()
    if not cleaned:
        raise ValueError("url is required")
    if drop_point.url and _same_page(cleaned, drop_point.url):
        raise NotACitation("that is the drop point itself, not a page citing it")

    state, note, page_title = _check(cleaned, drop_point=drop_point, db=db, user_id=user_id)
    if state == REJECTED:
        raise NotACitation(note or "page does not reference the drop point")

    identifier = ping_id_for(drop_point.id, cleaned)
    existing = db.query(PingDB).filter(PingDB.id == identifier).first()
    created = existing is None
    upgraded = False

    if existing is not None:
        # The same page, already known (a sweep found it, or it was recorded before). A hand
        # recording never downgrades: a verified row stays verified.
        if existing.verification != VERIFIED and state == VERIFIED:
            existing.verification = VERIFIED
            existing.verification_note = note
            upgraded = True
        elif existing.verification != VERIFIED:
            existing.verification_note = note
        ping = existing
    else:
        summary = (page_title or cleaned)[:1000]
        ping = PingDB(
            id=identifier,
            drop_point_id=drop_point.id,
            ping_type=PING_TYPE_CITATION,
            source_platform=infer_platform(cleaned),
            date_detected=naive_utc(datetime.now(timezone.utc)),
            connection_summary=summary,
            external_url=normalize_url(cleaned),
            reaction_notes=None,
            user_id=drop_point.user_id,
            strength=1.0,
            connection_type=classify_connection_type(summary),
            verification=state,
            verification_note=note,
        )
        db.add(ping)

    db.commit()

    if state == VERIFIED and (created or upgraded):
        # Same best-effort recompute detection does: the ping is durable either way.
        try:
            analyze_drop_point(drop_point.id, db)
        except Exception as exc:
            logger.warning(
                "[rippletrace] scoring failed after citation record for %s: %s",
                drop_point.id, exc,
            )
        db.refresh(drop_point)

    return {
        "drop_point_id": drop_point.id,
        "ping_id": ping.id,
        "url": normalize_url(cleaned),
        "verification": ping.verification,
        "note": ping.verification_note,
        "created": created,
        "upgraded": upgraded,
        "scores": {
            "narrative_score": drop_point.narrative_score or 0.0,
            "velocity_score": drop_point.velocity_score or 0.0,
            "spread_score": drop_point.spread_score or 0.0,
        },
    }
