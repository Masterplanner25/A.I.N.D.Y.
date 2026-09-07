"""Turn published content into drop points.

RippleTrace measures what happened *after* you published something. That only works
if the system knows what you published, and the sole route in was a hand-filled form —
which is why ``drop_points`` sat empty. Two supplies replace it:

* **A page URL** — one article, one drop point. The only option on platforms with no
  feed (LinkedIn, X), and the reason page ingestion never creates a source row.
* **A feed URL** — Substack, Medium, Ghost, WordPress, a YouTube channel. Registered
  once, polled on a schedule, so every future post ingests itself.

Ingestion is idempotent by construction: a drop point's id is derived from
``sha256(user_id | normalized_url)``, so re-polling a feed that still lists fifty old
entries updates those rows instead of creating fifty more. Without that the poll job
would manufacture spread out of nothing.

**Themes are derived, not generated.** Publisher tags are used when present, otherwise
keywords are extracted from the title and summary. No LLM call: ``core_themes`` is what
``build_strategies`` clusters on, and a background job that silently spends money per
entry — and that returns different phrasings for the same topic — would be worse for
clustering than deterministic keywords, besides needing an API key the poll job cannot
assume. Enrichment belongs in an explicit, user-triggered step.

Pings are deliberately untouched here. A ping means *an echo somewhere else*
(``spread_score`` counts distinct platforms), and nothing in this module can observe
one; treating your own publications as their own ripples would inflate every score in
the domain.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from apps.rippletrace.models import ContentSourceDB, DropPointDB
from apps.rippletrace.services.content_fetch import (
    ContentFetchError,
    FeedEntry,
    ParsedFeed,
    fetch_url,
    infer_platform,
    normalize_url,
    parse_feed,
    parse_page_metadata,
    strip_html,
)

logger = logging.getLogger(__name__)

# Poll cadence. The scheduled job runs hourly; a source is skipped if it was polled
# within MIN_POLL_INTERVAL, so a manual poll shortly before the job does not re-fetch.
POLL_JOB_INTERVAL_MINUTES = 60
MIN_POLL_INTERVAL = timedelta(minutes=30)
# Bound one job run. Anything beyond this waits for the next tick — and is logged,
# because a silent cap reads as "everything was polled".
MAX_SOURCES_PER_RUN = 50
# Guards a first ingest of a long-lived feed from creating hundreds of drop points.
MAX_ENTRIES_PER_POLL = 25

MAX_THEMES = 6

# Only ever used to reject candidate keywords, so over-inclusion costs nothing.
_STOPWORDS = {
    "a", "about", "after", "all", "also", "an", "and", "any", "are", "as", "at", "be",
    "because", "been", "before", "being", "between", "but", "by", "can", "could", "did",
    "do", "does", "doing", "done", "down", "each", "for", "from", "get", "gets", "had",
    "has", "have", "having", "here", "how", "i", "if", "in", "into", "is", "it", "its",
    "just", "like", "made", "make", "many", "may", "me", "more", "most", "much", "my",
    "new", "no", "not", "now", "of", "off", "on", "one", "only", "or", "other", "our",
    "out", "over", "own", "part", "per", "put", "said", "same", "see", "should", "since",
    "so", "some", "such", "than", "that", "the", "their", "them", "then", "there",
    "these", "they", "this", "those", "through", "to", "too", "two", "under", "up",
    "use", "used", "using", "very", "want", "was", "way", "we", "were", "what", "when",
    "where", "which", "while", "who", "why", "will", "with", "would", "you", "your",
}

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'’\-]{2,}")


# ── Identity ──────────────────────────────────────────────────────────────────


def drop_point_id_for(user_id: str | None, url: str) -> str:
    """Deterministic drop point id, so ingesting the same URL twice is an update.

    Scoped by user as well as URL: two users who publish (or syndicate) the same link
    each get their own drop point rather than fighting over one row.
    """
    digest = hashlib.sha256(f"{user_id or ''}|{normalize_url(url)}".encode("utf-8")).hexdigest()
    return f"dp-{digest[:32]}"


def _as_uuid(user_id: str | None) -> uuid.UUID | None:
    if not user_id:
        return None
    try:
        return uuid.UUID(str(user_id))
    except (TypeError, ValueError):
        return None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Theme derivation ──────────────────────────────────────────────────────────


# A term appearing in at least this share of a user's published work carries no information
# about any single piece — it describes the author, not the article. Measured 2026-09-07 on a
# 214-drop corpus: "chatgpt" appeared in most of it, and every Substack drop derived themes of
# `case, study, series, chatgpt` because that is the title template on
# "2025 ChatGPT Case Study Series: ...".
#
# 0.15 was chosen from the measured distribution rather than intuition. On the 214-drop
# corpus the document frequencies fall into two groups with a 5x gap between them:
#
#   chatgpt 97.7%  case 67.3%  study 66.8%  duality 26.6%  progress 26.6%  series 25.7%
#   ---------------------------- gap ----------------------------
#   prompt 5.6%  productivity 5.1%  framework 4.2%  business 4.2%  search 3.7%
#
# Everything above the gap is a naming convention — "2025 ChatGPT Case Study Series: ..." and
# "2025 ChatGPT/AI The Duality Of Progress Series: ...". Everything below is topical. Any
# threshold inside the gap separates them; 0.15 sits in the middle of it rather than on either
# edge, so neither group is one document away from flipping.
#
# Tunable, and deliberately NOT applied to a small corpus (see _MIN_CORPUS_FOR_DISCOUNT):
# with eight documents "in 15% of them" means "in one", which discounts everything.
UBIQUITOUS_TERM_RATIO = 0.15
_MIN_CORPUS_FOR_DISCOUNT = 12


def _discounted_terms(corpus_df: dict[str, int] | None, corpus_size: int) -> set[str]:
    """Terms so common across this author's work that they cannot distinguish one piece."""
    if not corpus_df or corpus_size < _MIN_CORPUS_FOR_DISCOUNT:
        return set()
    threshold = corpus_size * UBIQUITOUS_TERM_RATIO
    return {term for term, count in corpus_df.items() if count >= threshold}


def derive_themes(
    *,
    title: str,
    summary: str,
    tags: list[str],
    corpus_df: dict[str, int] | None = None,
    corpus_size: int = 0,
) -> list[str]:
    """Publisher tags when they exist, keywords from the text when they do not.

    ★ `corpus_df` / `corpus_size` make the text path CORPUS-AWARE. Without them this counted
    words within one document, which for a catalogue of similarly-titled pieces returns the
    title template: every Substack drop was themed `case, study, series, chatgpt` off
    "2025 ChatGPT Case Study Series: ...", and the three strategies built from those themes
    all said the same thing.

    Stopword filtering does not help here — these are real words. What makes them useless is
    that they are in *everything the author writes*, which is only visible from the corpus.

    Tags still win when present. That is a separate and larger question — for 168 of 214 drops
    the themes are labels the author typed, which is declared intent rather than discovery
    (RIPPLETRACE-NO-CONTENT-1). This change improves the derived path only; it does not
    pretend to answer what a piece is *about*.
    """
    cleaned_tags = [tag.strip().lower() for tag in (tags or []) if tag and tag.strip()]
    if cleaned_tags:
        return _unique(cleaned_tags)[:MAX_THEMES]

    counts: dict[str, int] = {}
    # Title words count double — a title is the author's own summary of the topic.
    for source_text, weight in ((title or "", 2), (strip_html(summary or "", limit=600), 1)):
        for match in _WORD_RE.finditer(source_text.lower()):
            word = match.group(0).strip("'’-")
            if len(word) < 3 or word in _STOPWORDS:
                continue
            counts[word] = counts.get(word, 0) + weight

    # Drop terms the author uses everywhere BEFORE ranking, so the discount frees slots for
    # distinguishing terms rather than merely removing the winners and leaving fewer themes.
    ubiquitous = _discounted_terms(corpus_df, corpus_size)
    if ubiquitous:
        filtered = {w: c for w, c in counts.items() if w not in ubiquitous}
        # Never return nothing: a piece whose every term is ubiquitous is genuinely on the
        # author's main beat, and reporting its common terms beats reporting silence.
        counts = filtered or counts

    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [word for word, _count in ranked[:MAX_THEMES]]


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


# ── Drop point upsert ─────────────────────────────────────────────────────────


def corpus_term_frequency(db: Session, user_id: str | None) -> tuple[dict[str, int], int]:
    """Document frequency of each term across one user's existing drop titles.

    Returns ``({term: documents_containing_it}, document_count)`` for
    :func:`derive_themes` to discount the author's ubiquitous vocabulary.

    Reads TITLES only, deliberately. Summaries are not stored (`drop_points` has no content
    column — RIPPLETRACE-NO-CONTENT-1), so titles are the whole corpus available, and a term
    that recurs across an author's titles is exactly the naming-convention noise this exists
    to remove.

    Best-effort: any failure returns an empty map, which makes `derive_themes` behave as it
    did before. Theme derivation must never be the reason an ingest fails.
    """
    uid = _as_uuid(user_id)
    if uid is None:
        return {}, 0
    try:
        titles = [
            row[0] or ""
            for row in db.query(DropPointDB.title)
            .filter(DropPointDB.user_id == uid)
            .all()
        ]
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("[rippletrace] corpus term frequency unavailable: %s", exc)
        return {}, 0

    frequency: dict[str, int] = {}
    for title in titles:
        # Per-DOCUMENT counting, not per-occurrence: a word repeated in one title is still
        # one document, and document frequency is what "appears across the corpus" means.
        seen: set[str] = set()
        for match in _WORD_RE.finditer(title.lower()):
            word = match.group(0).strip("'’-")
            if len(word) < 3 or word in _STOPWORDS:
                continue
            seen.add(word)
        for word in seen:
            frequency[word] = frequency.get(word, 0) + 1
    return frequency, len(titles)


def rederive_themes_for_user(db: Session, user_id: str | None, *, apply: bool = False) -> dict[str, Any]:
    """Recompute derived themes for one user's drop points against the whole corpus.

    Needed because the corpus-aware discount only applies at ingest, so drops already stored
    keep whatever they were themed with — and for a catalogue that is not actively growing,
    that means nothing improves until the next publication.

    Only touches drops whose themes were DERIVED. A drop themed from publisher tags is left
    exactly alone: those are labels the author typed, and silently replacing them with
    inferred ones would answer RIPPLETRACE-NO-CONTENT-1's open question by accident.

    Tags are not stored on the drop point, so "was this derived?" is inferred from whether
    re-deriving the title against the corpus differs from what is stored. That is imprecise
    at the edges and deliberately conservative: `apply=False` (the default) reports what
    would change without writing.
    """
    corpus_df, corpus_size = corpus_term_frequency(db, user_id)
    if corpus_size < _MIN_CORPUS_FOR_DISCOUNT:
        return {"corpus_size": corpus_size, "examined": 0, "changed": 0, "applied": False,
                "reason": "corpus too small to discount"}

    uid = _as_uuid(user_id)
    rows = db.query(DropPointDB).filter(DropPointDB.user_id == uid).all()
    changed: list[dict[str, Any]] = []
    for row in rows:
        current = [t.strip() for t in (row.core_themes or "").split(",") if t.strip()]
        proposed = derive_themes(
            title=row.title or "", summary="", tags=[],
            corpus_df=corpus_df, corpus_size=corpus_size,
        )
        # A drop themed from tags will not match a title-derived list, so requiring the
        # CURRENT value to be reproducible from the title without the corpus is what
        # identifies the derived ones.
        was_derived = current == derive_themes(title=row.title or "", summary="", tags=[])
        if not was_derived or not proposed or proposed == current:
            continue
        changed.append({"title": row.title, "from": current, "to": proposed})
        if apply:
            row.core_themes = ",".join(proposed)

    if apply and changed:
        db.commit()
    return {"corpus_size": corpus_size, "examined": len(rows),
            "changed": len(changed), "applied": bool(apply), "samples": changed[:5]}


def upsert_drop_point(
    db: Session,
    *,
    user_id: str | None,
    url: str,
    title: str,
    platform: str | None = None,
    summary: str = "",
    tags: list[str] | None = None,
    published_at: datetime | None = None,
    intent: str = "published",
) -> tuple[DropPointDB, bool]:
    """Create or refresh the drop point for a URL. Returns ``(row, created)``.

    Does not commit — the caller owns the transaction so a feed poll writes its entries
    and the source's status together.

    The narrative/velocity/spread columns are left alone: they belong to threadweaver
    and are computed from pings. A freshly ingested publication genuinely has no
    ripple yet, and writing a placeholder would be inventing one.
    """
    from apps.rippletrace.services.ripple_detection import naive_utc

    canonical = normalize_url(url)
    identifier = drop_point_id_for(user_id, canonical)
    # Corpus-aware: terms the author uses across most of their catalogue are discounted, so
    # a title template ("2025 ChatGPT Case Study Series: ...") stops becoming the theme.
    # Skipped entirely when tags are present, since tags win anyway.
    corpus_df: dict[str, int] = {}
    corpus_size = 0
    if not (tags or []):
        corpus_df, corpus_size = corpus_term_frequency(db, user_id)
    themes = derive_themes(
        title=title,
        summary=summary,
        tags=tags or [],
        corpus_df=corpus_df,
        corpus_size=corpus_size,
    )
    resolved_platform = platform or infer_platform(canonical)
    # Left NULL when the source published no date, rather than defaulted to "now".
    # "Now" is a lie that costs something concrete: echo detection rejects results
    # predating the drop point, so an ingestion-time stamp makes essentially the whole
    # web look like prior art and detection silently finds nothing forever. NULL says
    # what is true — the publication date is unknown — and every consumer already
    # handles it (threadweaver's _minutes_difference and build_strategies both guard).
    #
    # date_dropped is also a legacy naive column, so an aware value would make
    # threadweaver compare naive-from-DB against aware-in-session. See naive_utc().
    dropped_at = naive_utc(published_at)
    display_title = (title or "").strip() or canonical

    row = db.query(DropPointDB).filter(DropPointDB.id == identifier).first()
    if row is not None:
        row.title = display_title
        row.platform = resolved_platform
        row.url = canonical
        row.core_themes = ",".join(themes)
        # tagged_entities is only ever populated from explicit publisher tags; guessing
        # entities from prose would pollute the strategy conditions built on top of it.
        row.tagged_entities = row.tagged_entities or ""
        if published_at is not None:
            row.date_dropped = naive_utc(published_at)
        return row, False

    row = DropPointDB(
        id=identifier,
        title=display_title,
        platform=resolved_platform,
        url=canonical,
        date_dropped=dropped_at,
        core_themes=",".join(themes),
        tagged_entities="",
        intent=intent,
        user_id=_as_uuid(user_id),
    )
    db.add(row)
    return row, True


def drop_point_to_dict(row: DropPointDB) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "platform": row.platform,
        "url": row.url,
        "date_dropped": row.date_dropped.isoformat() if row.date_dropped else None,
        "core_themes": [theme for theme in (row.core_themes or "").split(",") if theme],
        "tagged_entities": [
            entity for entity in (row.tagged_entities or "").split(",") if entity
        ],
        "intent": row.intent,
        "narrative_score": row.narrative_score or 0.0,
        "velocity_score": row.velocity_score or 0.0,
        "spread_score": row.spread_score or 0.0,
    }


def source_to_dict(row: ContentSourceDB) -> dict[str, Any]:
    return {
        "id": row.id,
        "feed_url": row.feed_url,
        "site_url": row.site_url,
        "title": row.title,
        "platform": row.platform,
        "kind": row.kind,
        "active": bool(row.active),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "last_polled_at": row.last_polled_at.isoformat() if row.last_polled_at else None,
        "last_status": row.last_status,
        "last_error": row.last_error,
        "last_entry_count": row.last_entry_count,
        "ingested_count": row.ingested_count or 0,
    }


# ── Ingestion entry points ────────────────────────────────────────────────────


def ingest_url(db: Session, *, url: str, user_id: str | None) -> dict[str, Any]:
    """Ingest whatever a user pasted, deciding for them whether it is a feed or a page.

    Asking "is this a feed URL or an article URL?" pushes a distinction onto the user
    that the response itself answers, so the URL is fetched once and classified. A page
    that advertises a feed reports it under ``suggested_feeds`` — that is the path from
    "I pasted one article" to a permanent supply.
    """
    result = fetch_url(url, db=db, user_id=user_id)

    if result.looks_like_feed:
        try:
            feed = parse_feed(result.text, result.url)
        except ContentFetchError:
            feed = None
        if feed is not None:
            source, created = _register_feed_source(
                db, feed=feed, feed_url=result.url, user_id=user_id
            )
            ingested = _ingest_feed_entries(db, feed=feed, user_id=user_id)
            _mark_polled(
                source,
                status="ok",
                entry_count=len(feed.entries),
                created_count=ingested["created"],
                etag=result.etag,
                last_modified=result.last_modified,
            )
            db.commit()
            return {
                "kind": "feed",
                "source": source_to_dict(source),
                "source_created": created,
                "created": ingested["created"],
                "updated": ingested["updated"],
                "drop_points": ingested["drop_points"],
                "suggested_feeds": [],
            }

    metadata = parse_page_metadata(result.text, result.url)
    row, created = upsert_drop_point(
        db,
        user_id=user_id,
        url=metadata.canonical_url or result.url,
        title=metadata.title,
        platform=metadata.site_name or infer_platform(result.url),
        summary=metadata.description,
        tags=metadata.tags,
        published_at=metadata.published_at,
    )
    db.commit()
    db.refresh(row)
    return {
        "kind": "page",
        "source": None,
        "source_created": False,
        "created": 1 if created else 0,
        "updated": 0 if created else 1,
        "drop_points": [drop_point_to_dict(row)],
        "suggested_feeds": metadata.feed_urls,
    }


def _register_feed_source(
    db: Session, *, feed: ParsedFeed, feed_url: str, user_id: str | None
) -> tuple[ContentSourceDB, bool]:
    """Find or create the subscription row for a feed. Re-registering is a no-op."""
    canonical = normalize_url(feed_url)
    owner = _as_uuid(user_id)
    existing = (
        db.query(ContentSourceDB)
        .filter(ContentSourceDB.user_id == owner, ContentSourceDB.feed_url == canonical)
        .first()
    )
    if existing is not None:
        # Re-registering an inactive source is how a user turns one back on.
        existing.active = True
        existing.title = existing.title or feed.title
        return existing, False

    source = ContentSourceDB(
        id=str(uuid.uuid4()),
        user_id=owner,
        feed_url=canonical,
        site_url=feed.site_url or None,
        title=feed.title or canonical,
        platform=infer_platform(feed.site_url or canonical),
        kind="feed",
        active=True,
        created_at=_utcnow(),
        ingested_count=0,
    )
    db.add(source)
    return source, True


def _ingest_feed_entries(
    db: Session, *, feed: ParsedFeed, user_id: str | None
) -> dict[str, Any]:
    created = 0
    updated = 0
    rows: list[dict[str, Any]] = []
    for entry in feed.entries[:MAX_ENTRIES_PER_POLL]:
        row, was_created = _ingest_entry(db, entry=entry, user_id=user_id)
        if was_created:
            created += 1
        else:
            updated += 1
        rows.append(drop_point_to_dict(row))
    return {"created": created, "updated": updated, "drop_points": rows}


def _ingest_entry(
    db: Session, *, entry: FeedEntry, user_id: str | None
) -> tuple[DropPointDB, bool]:
    return upsert_drop_point(
        db,
        user_id=user_id,
        url=entry.url,
        title=entry.title,
        summary=entry.summary,
        tags=entry.tags,
        published_at=entry.published_at,
    )


def _mark_polled(
    source: ContentSourceDB,
    *,
    status: str,
    entry_count: int | None = None,
    created_count: int = 0,
    error: str | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
) -> None:
    source.last_polled_at = _utcnow()
    source.last_status = status
    source.last_error = error
    if entry_count is not None:
        source.last_entry_count = entry_count
    if created_count:
        source.ingested_count = (source.ingested_count or 0) + created_count
    if etag is not None:
        source.etag = etag
    if last_modified is not None:
        source.last_modified = last_modified


def list_sources(db: Session, *, user_id: str | None) -> list[dict[str, Any]]:
    rows = (
        db.query(ContentSourceDB)
        .filter(ContentSourceDB.user_id == _as_uuid(user_id))
        .order_by(ContentSourceDB.created_at.desc().nullslast())
        .all()
    )
    return [source_to_dict(row) for row in rows]


def get_source(db: Session, *, source_id: str, user_id: str | None) -> ContentSourceDB | None:
    """Fetch one source, scoped to its owner so an id guess cannot reach someone else's."""
    return (
        db.query(ContentSourceDB)
        .filter(
            ContentSourceDB.id == source_id,
            ContentSourceDB.user_id == _as_uuid(user_id),
        )
        .first()
    )


def set_source_active(
    db: Session, *, source_id: str, user_id: str | None, active: bool
) -> dict[str, Any] | None:
    source = get_source(db, source_id=source_id, user_id=user_id)
    if source is None:
        return None
    source.active = bool(active)
    db.commit()
    db.refresh(source)
    return source_to_dict(source)


def delete_source(db: Session, *, source_id: str, user_id: str | None) -> bool:
    """Remove a subscription. Drop points it produced are kept.

    Unsubscribing means "stop watching this feed", not "erase what I published" — the
    ripple history on those drop points is the whole point of having recorded them.
    """
    source = get_source(db, source_id=source_id, user_id=user_id)
    if source is None:
        return False
    db.delete(source)
    db.commit()
    return True


def poll_source(db: Session, source: ContentSourceDB) -> dict[str, Any]:
    """Re-fetch one feed and ingest anything new. Never raises.

    A fetch failure is recorded on the row rather than propagated: one dead feed must
    not stop the poll job, and ``last_status``/``last_error`` are how a broken source
    becomes visible instead of just going quiet.
    """
    owner = str(source.user_id) if source.user_id else None
    try:
        result = fetch_url(
            source.feed_url,
            etag=source.etag,
            last_modified=source.last_modified,
            db=db,
            user_id=owner,
        )
    except ContentFetchError as exc:
        _mark_polled(source, status="error", error=str(exc))
        db.commit()
        return {"status": "error", "error": str(exc), "created": 0, "updated": 0}
    except Exception as exc:  # transport/library surprises must not kill the job
        logger.warning("[rippletrace] poll failed for %s: %s", source.feed_url, exc)
        _mark_polled(source, status="error", error=str(exc))
        db.commit()
        return {"status": "error", "error": str(exc), "created": 0, "updated": 0}

    if result.not_modified:
        _mark_polled(source, status="unchanged")
        db.commit()
        return {"status": "unchanged", "created": 0, "updated": 0}

    try:
        feed = parse_feed(result.text, result.url)
    except ContentFetchError as exc:
        _mark_polled(source, status="error", error=str(exc))
        db.commit()
        return {"status": "error", "error": str(exc), "created": 0, "updated": 0}

    ingested = _ingest_feed_entries(db, feed=feed, user_id=owner)
    if feed.title and not source.title:
        source.title = feed.title
    _mark_polled(
        source,
        status="ok",
        entry_count=len(feed.entries),
        created_count=ingested["created"],
        etag=result.etag,
        last_modified=result.last_modified,
    )
    db.commit()
    return {
        "status": "ok",
        "created": ingested["created"],
        "updated": ingested["updated"],
        "entries": len(feed.entries),
    }


# ── Scheduled poll ────────────────────────────────────────────────────────────

# The runtime registers app scheduled jobs without APScheduler's coalesce/max_instances
# (scheduler_service.py), so a slow run could otherwise overlap the next tick.
_poll_lock = threading.Lock()


def poll_due_sources() -> dict[str, Any]:
    """Scheduled job body: poll every active source that is due.

    Takes no arguments so it satisfies the runtime's job-handler contract, and owns its
    own session because the scheduler has no request to borrow one from.
    """
    if not _poll_lock.acquire(blocking=False):
        logger.info("[rippletrace] content poll already running; skipping this tick")
        return {"skipped": True, "reason": "already_running"}

    from AINDY.db.database import SessionLocal

    db = SessionLocal()
    summary = {"polled": 0, "created": 0, "errors": 0, "skipped": False}
    try:
        cutoff = _utcnow() - MIN_POLL_INTERVAL
        due = (
            db.query(ContentSourceDB)
            .filter(
                ContentSourceDB.active.is_(True),
                (ContentSourceDB.last_polled_at.is_(None))
                | (ContentSourceDB.last_polled_at < cutoff),
            )
            .order_by(ContentSourceDB.last_polled_at.asc().nullsfirst())
            .limit(MAX_SOURCES_PER_RUN + 1)
            .all()
        )
        if len(due) > MAX_SOURCES_PER_RUN:
            logger.info(
                "[rippletrace] %d sources due, polling %d this run; the rest follow next tick",
                len(due),
                MAX_SOURCES_PER_RUN,
            )
            due = due[:MAX_SOURCES_PER_RUN]

        for source in due:
            outcome = poll_source(db, source)
            summary["polled"] += 1
            summary["created"] += int(outcome.get("created") or 0)
            if outcome.get("status") == "error":
                summary["errors"] += 1
    except Exception as exc:
        logger.warning("[rippletrace] content poll run failed: %s", exc)
        summary["error"] = str(exc)
    finally:
        db.close()
        _poll_lock.release()
    return summary
