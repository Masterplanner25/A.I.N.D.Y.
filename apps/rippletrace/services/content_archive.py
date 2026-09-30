"""The owner's published writing, stored and made recallable — `WORK_MODEL_SPEC.md` §5, phase B.

Until this, RippleTrace knew 214 pieces by title, url, platform and date, and nothing they said.
The feeds delivered the text and ingestion kept a 2,000-character summary to extract themes, so
memory recall returned telemetry about the owner's work and never the work. The agent could not cite
a piece it had never read.

Verified per platform before building (2026-09-30):

| Platform | Pieces | Where the text comes from |
|---|---|---|
| DEV      | 143 | the public API, by the piece's own url (`/api/articles/{user}/{slug}` → `body_markdown`); the feed carries the newest 12 whole |
| Substack | 46  | the per-post API, by url (`/api/v1/posts/{slug}` → `body_html`), back to February 2025; the feed carries the newest 20 whole |
| Medium   | 10  | the feed only (`content:encoded`), which covers all ten |
| YouTube  | 15  | no text without transcripts: out of scope (§5.2), recorded as `none` |

Three steps, each resumable:

1. **Keep** — a feed poll keeps a body that is the article (`keep_feed_content`), going forward.
2. **Backfill** — pieces with no text are fetched from their platform, a batch at a time.
3. **Remember** — stored text is chunked into memory nodes, source `published_work`, tagged with
   the piece, its series and the owner's Works for that series. Rewritten only when the text changes.

A scheduled job runs 2 and 3 until the catalogue is done, then only for what is new.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from html import unescape
from typing import Any, Callable
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from apps.rippletrace.drop import DropPointDB

logger = logging.getLogger(__name__)

#: A piece's text, at most. The catalogue measured 5-11k characters a piece; the cap is for the
#: outlier, not the norm (HEALTH-EVENT-VOLUME-1 is the reminder of what unbounded text costs).
CONTENT_MAX_CHARS = 50_000
#: A feed body shorter than this is an excerpt, not the article (Substack's description is ~50).
FEED_MIN_CHARS = 1_500
#: One memory node's text, about a screen of prose: long enough to carry an argument, short enough
#: that recall returns the passage and not the whole piece.
CHUNK_CHARS = 1_500
#: Pieces per step per run, and the pause between platform requests.
BATCH = 40
REQUEST_PAUSE_SECONDS = 0.5
JOB_INTERVAL_MINUTES = 10
MEMORY_SOURCE = "published_work"

_archive_lock = threading.Lock()
#: A fetch failure that will not get better: the piece is gone, so it is marked, not retried.
_GONE = re.compile(r"HTTP (?:404|410)\b")


def _uid(user_id):
    """The owner id as the drop_points column stores it (routes hand a string)."""
    import uuid

    return user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))


# ── Text ──────────────────────────────────────────────────────────────────────────────────

_BLOCK_END = re.compile(r"</(?:p|div|h[1-6]|li|blockquote|pre|tr|section|article)\s*>|<br\s*/?>", re.I)
_TAG = re.compile(r"<[^>]+>")


def to_text(raw: str | None) -> str:
    """HTML or markdown to plain text, keeping paragraph breaks (chunking splits on them)."""
    text = raw or ""
    if "<" in text and ">" in text:
        text = _BLOCK_END.sub("\n\n", text)
        text = re.sub(r"<(script|style)\b.*?</\1>", " ", text, flags=re.I | re.S)
        text = _TAG.sub(" ", text)
    text = unescape(text)
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def store_content(row: DropPointDB, text: str, source: str) -> bool:
    """Keep a piece's text on its drop point. Returns whether it changed. Does not commit."""
    text = (text or "").strip()[:CONTENT_MAX_CHARS]
    if not text:
        return False
    digest = _hash(text)
    if row.content_hash == digest:
        return False
    row.content_text = text
    row.content_source = source
    row.content_hash = digest
    row.content_fetched_at = datetime.now(timezone.utc)
    return True


def keep_feed_content(row: DropPointDB, raw: str | None) -> bool:
    """Step 1: keep a feed body when it is the article, not an excerpt."""
    text = to_text(raw)
    if len(text) < FEED_MIN_CHARS:
        return False
    return store_content(row, text, "feed")


# ── Step 2: backfill from each platform ───────────────────────────────────────────────────


def _get_json(url: str, *, db=None, user_id=None) -> Any:
    from apps.rippletrace.services.content_fetch import fetch_url

    result = fetch_url(url, db=db, user_id=user_id, purpose="rippletrace_content_archive")
    return json.loads(result.text)


def _dev_text(row: DropPointDB, *, db=None) -> str | None:
    parts = [p for p in urlparse(row.url or "").path.split("/") if p]
    if len(parts) < 2:
        return None
    data = _get_json(f"https://dev.to/api/articles/{parts[0]}/{parts[1]}", db=db, user_id=row.user_id)
    return data.get("body_markdown") or data.get("body_html")


def _substack_text(row: DropPointDB, *, db=None) -> str | None:
    parsed = urlparse(row.url or "")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2 or parts[0] != "p":
        return None
    data = _get_json(f"https://{parsed.netloc}/api/v1/posts/{parts[1]}", db=db, user_id=row.user_id)
    return data.get("body_html")


def _medium_texts(db: Session, user_id) -> dict[str, str]:
    """Medium's text is only in its feed: url → body for every Medium source the owner registered."""
    from apps.rippletrace.content_source import ContentSourceDB
    from apps.rippletrace.services.content_fetch import fetch_url, normalize_url, parse_feed

    out: dict[str, str] = {}
    for source in db.query(ContentSourceDB).filter(ContentSourceDB.user_id == user_id,
                                                     ContentSourceDB.platform == "Medium").all():
        feed = parse_feed(fetch_url(source.feed_url, db=db, user_id=user_id).text, source.feed_url)
        for entry in feed.entries:
            if entry.content:
                out[normalize_url(entry.url)] = entry.content
    return out


def _platform_fetchers(db: Session, user_id) -> dict[str, Callable[[DropPointDB], str | None]]:
    medium: dict[str, str] | None = None

    def medium_text(row: DropPointDB) -> str | None:
        nonlocal medium
        if medium is None:
            medium = _medium_texts(db, user_id)
        from apps.rippletrace.services.content_fetch import normalize_url

        return medium.get(normalize_url(row.url or ""))

    return {
        "DEV": lambda row: _dev_text(row, db=db),
        "Substack": lambda row: _substack_text(row, db=db),
        "Medium": medium_text,
    }


def backfill_content(
    db: Session, *, user_id, limit: int = BATCH,
    fetchers: dict[str, Callable[[DropPointDB], str | None]] | None = None,
    pause: float = REQUEST_PAUSE_SECONDS,
) -> dict:
    """Step 2: fetch the text of pieces that have none, newest first. A platform that answers with
    no text marks the piece `none` so it is not asked again; a failed request leaves it for the next
    run. Commits."""
    user_id = _uid(user_id)
    fetchers = fetchers if fetchers is not None else _platform_fetchers(db, user_id)
    rows = (
        db.query(DropPointDB)
        .filter(DropPointDB.user_id == user_id, DropPointDB.content_source.is_(None))
        .order_by(DropPointDB.date_dropped.desc().nullslast())
        .limit(limit)
        .all()
    )
    out = {"fetched": 0, "none": 0, "failed": 0}
    for row in rows:
        fetch = fetchers.get(row.platform or "")
        if fetch is None:
            row.content_source = "none"  # YouTube and anything without a text source
            out["none"] += 1
            continue
        try:
            raw = fetch(row)
        except Exception as exc:
            if _GONE.search(str(exc)):
                row.content_source = "none"  # deleted or moved: asking again will not help
                out["none"] += 1
            else:
                out["failed"] += 1  # transient: left for the next run
                logger.info("[content_archive] %s not fetched (%s): %s", row.url, row.platform, exc)
            continue
        finally:
            if pause:
                time.sleep(pause)
        if store_content(row, to_text(raw), "api" if row.platform != "Medium" else "feed"):
            out["fetched"] += 1
        else:
            row.content_source = "none"
            out["none"] += 1
    db.commit()
    return out


# ── Step 3: remember ──────────────────────────────────────────────────────────────────────


def chunk_text(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """Paragraphs packed to about `size`; a paragraph longer than that is cut at sentence ends."""
    pieces: list[str] = []
    for paragraph in (p.strip() for p in text.split("\n\n")):
        if not paragraph:
            continue
        if len(paragraph) <= size:
            pieces.append(paragraph)
            continue
        sentence_run = ""
        for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
            if sentence_run and len(sentence_run) + len(sentence) + 1 > size:
                pieces.append(sentence_run)
                sentence_run = ""
            sentence_run = f"{sentence_run} {sentence}".strip()
            while len(sentence_run) > size:
                pieces.append(sentence_run[:size])
                sentence_run = sentence_run[size:]
        if sentence_run:
            pieces.append(sentence_run)
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) + 2 > size:
            chunks.append(current)
            current = piece
        else:
            current = f"{current}\n\n{piece}" if current else piece
    if current:
        chunks.append(current)
    return chunks


def _series_and_works(db: Session, user_id) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Confirmed series by normalised name → container id, and container id → the owner's Works."""
    from AINDY.platform_layer.registry import get_job
    from apps.rippletrace.container import CONTAINER_CONFIRMED, ContainerDB
    from apps.rippletrace.services.container_service import _normalize

    containers = db.query(ContainerDB).filter(ContainerDB.user_id == user_id,
                                              ContainerDB.status == CONTAINER_CONFIRMED).all()
    series = {_normalize(c.name): c.id for c in containers}
    works_job = get_job("masterplan.works_by_container")
    works = works_job(user_id=str(user_id), db=db) if works_job else {}
    return series, works or {}


def _tags_for(row: DropPointDB, series: dict[str, str], works: dict[str, list[str]], names: dict[str, str]) -> list[str]:
    from apps.rippletrace.services.container_service import _normalize

    tags = [MEMORY_SOURCE, (row.platform or "web").lower(), f"drop:{row.id}"]
    for entity in (e.strip() for e in (row.tagged_entities or "").split(",") if e.strip()):
        container_id = series.get(_normalize(entity))
        if container_id:
            tags.append(f"series:{names[container_id]}")
            tags.extend(f"work:{work}" for work in works.get(container_id, []))
    return list(dict.fromkeys(tags))


def remember_piece(db: Session, row: DropPointDB, tags: list[str]) -> int:
    """Replace a piece's memory chunks with ones written from its current text. Does not commit."""
    from AINDY.db.dao.memory_node_dao import MemoryNodeDAO

    dao = MemoryNodeDAO(db)
    user_id = str(row.user_id)
    for node in dao.get_by_tags([f"drop:{row.id}"], limit=500, user_id=user_id):
        dao.delete_by_id(str(node["id"]), user_id=user_id)
    chunks = chunk_text(row.content_text or "")
    published = row.date_dropped.date().isoformat() if row.date_dropped else "undated"
    for index, chunk in enumerate(chunks, start=1):
        header = f"{row.title} ({row.platform}, {published}; part {index} of {len(chunks)})"
        dao.save(
            content=f"{header}\n\n{chunk}",
            source=MEMORY_SOURCE,
            tags=tags,
            user_id=user_id,
            node_type="insight",
            extra={"drop_point_id": row.id, "url": row.url, "title": row.title, "platform": row.platform,
                   "published": published, "chunk": index, "chunks": len(chunks), "content_hash": row.content_hash},
            commit=False,
        )
    row.content_memory_hash = row.content_hash
    return len(chunks)


def remember_content(db: Session, *, user_id, limit: int = BATCH) -> dict:
    """Step 3: write memory for pieces whose text is newer than their memory. Commits per piece."""
    from apps.rippletrace.container import ContainerDB

    user_id = _uid(user_id)
    rows = (
        db.query(DropPointDB)
        .filter(DropPointDB.user_id == user_id, DropPointDB.content_hash.isnot(None),
                (DropPointDB.content_memory_hash.is_(None)) | (DropPointDB.content_memory_hash != DropPointDB.content_hash))
        .order_by(DropPointDB.date_dropped.desc().nullslast())
        .limit(limit)
        .all()
    )
    if not rows:
        return {"remembered": 0, "chunks": 0}
    series, works = _series_and_works(db, user_id)
    names = {c.id: c.name for c in db.query(ContainerDB).filter(ContainerDB.user_id == user_id).all()}
    remembered = chunks = 0
    for row in rows:
        try:
            chunks += remember_piece(db, row, _tags_for(row, series, works, names))
            db.commit()
            remembered += 1
        except Exception as exc:
            db.rollback()
            logger.warning("[content_archive] memory for %s not written: %s", row.id, exc)
    return {"remembered": remembered, "chunks": chunks}


# ── Status and the scheduled job ──────────────────────────────────────────────────────────


def archive_status(db: Session, *, user_id) -> dict:
    """What is stored and recallable, per platform."""
    user_id = _uid(user_id)
    rows = db.query(DropPointDB.platform, DropPointDB.content_source, DropPointDB.content_hash,
                    DropPointDB.content_memory_hash).filter(DropPointDB.user_id == user_id).all()
    platforms: dict[str, dict[str, int]] = {}
    for platform, source, digest, memory in rows:
        entry = platforms.setdefault(platform or "web", {"pieces": 0, "stored": 0, "recallable": 0, "no_text": 0})
        entry["pieces"] += 1
        entry["stored"] += int(digest is not None)
        entry["recallable"] += int(digest is not None and memory == digest)
        entry["no_text"] += int(source == "none")
    totals = {key: sum(p[key] for p in platforms.values()) for key in ("pieces", "stored", "recallable", "no_text")}
    return {**totals, "pending": totals["pieces"] - totals["stored"] - totals["no_text"], "platforms": platforms}


def archive_step(db: Session, *, user_id, limit: int = BATCH, fetchers=None, pause: float = REQUEST_PAUSE_SECONDS) -> dict:
    """One batch of both steps for one owner, then where things stand."""
    fetched = backfill_content(db, user_id=user_id, limit=limit, fetchers=fetchers, pause=pause)
    remembered = remember_content(db, user_id=user_id, limit=limit)
    return {**fetched, **remembered, "status": archive_status(db, user_id=user_id)}


def archive_published_work() -> dict:
    """Scheduled job body: one batch per owner with pieces to fetch or remember. Its own session and a
    non-blocking guard, like the feed poll, since the scheduler does not prevent overlap."""
    if not _archive_lock.acquire(blocking=False):
        return {"skipped": True, "reason": "already_running"}
    from AINDY.db.database import SessionLocal

    db = SessionLocal()
    summary: dict[str, Any] = {"owners": 0, "fetched": 0, "remembered": 0, "chunks": 0, "skipped": False}
    try:
        owners = {
            row[0] for row in db.query(DropPointDB.user_id).filter(
                DropPointDB.user_id.isnot(None),
                (DropPointDB.content_source.is_(None))
                | ((DropPointDB.content_hash.isnot(None))
                   & ((DropPointDB.content_memory_hash.is_(None)) | (DropPointDB.content_memory_hash != DropPointDB.content_hash))),
            ).distinct()
        }
        for owner in owners:
            outcome = archive_step(db, user_id=owner)
            summary["owners"] += 1
            for key in ("fetched", "remembered", "chunks"):
                summary[key] += int(outcome.get(key) or 0)
    except Exception as exc:
        logger.warning("[content_archive] run failed: %s", exc)
        summary["error"] = str(exc)
    finally:
        db.close()
        _archive_lock.release()
    return summary
