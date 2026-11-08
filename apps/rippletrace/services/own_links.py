"""Authority, the owner's definition: links back to your own relevant pieces (ARTICLE_ANSWERS_SPEC §3).

Given a draft's text, this reports three things about the owner's own published pieces:

* **linked**: which of them the draft already links to. Any copy counts: a link to the DEV
  copy of a piece cross-posted to Substack and Medium is a link to that piece. Copies are
  grouped by title, the same way the archive groups cross-posts.
* **missing**: relevant pieces it does not link to, each with the passage that makes it relevant.
  Relevance is semantic similarity between parts of the draft and the archive's `published_work`
  memory, the owner's own pieces only. A candidate is information for the writer; nothing here
  inserts a link (`SEO_EDITING_AID_SPEC`).
* **other_links**: links to anything that is not one of the owner's pieces, listed so the writer can
  see what is external.

Phase A of the spec: read-only, no schema. It never fetches a URL.
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

from apps.rippletrace.drop import DropPointDB
from apps.rippletrace.services.content_archive import MEMORY_SOURCE
from apps.rippletrace.services.content_fetch import normalize_url
from apps.rippletrace.services.links import extract_links
from apps.rippletrace.services.container_service import _normalize as _normalize_title

logger = logging.getLogger(__name__)


DRAFT_PART_CHARS = 2500  # each part of the draft is embedded on its own
MAX_DRAFT_PARTS = 4
CANDIDATES_PER_PART = 60
DEFAULT_MISSING_LIMIT = 8
PASSAGE_CHARS = 320


def _uid(user_id) -> uuid.UUID:
    return user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))


def _owner_pieces(db: Session, owner: uuid.UUID) -> dict[str, dict[str, Any]]:
    """The owner's pieces, one per title, each with every copy's URL."""
    rows = (
        db.query(DropPointDB.id, DropPointDB.title, DropPointDB.platform, DropPointDB.url, DropPointDB.date_dropped)
        .filter(DropPointDB.user_id == owner, DropPointDB.url.isnot(None))
        .all()
    )
    pieces: dict[str, dict[str, Any]] = {}
    for drop_id, title, platform, url, dropped in rows:
        key = _normalize_title(title or "") or f"id:{drop_id}"
        piece = pieces.setdefault(key, {"key": key, "title": title or "", "copies": [], "drop_ids": set()})
        piece["copies"].append({"platform": platform, "url": url,
                                "published": dropped.date().isoformat() if dropped else None})
        piece["drop_ids"].add(drop_id)
    return pieces


def _draft_parts(text: str) -> list[str]:
    """Up to MAX_DRAFT_PARTS slices of the draft, on paragraph breaks where possible, so a piece
    relevant to one section is found even when the draft as a whole is about something else."""
    body = (text or "").strip()
    if not body:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    parts: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) > DRAFT_PART_CHARS:
            parts.append(current)
            current = ""
        current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        parts.append(current)
    if len(parts) > MAX_DRAFT_PARTS:
        step = len(parts) / MAX_DRAFT_PARTS
        parts = [parts[int(i * step)] for i in range(MAX_DRAFT_PARTS)]
    return [part[:DRAFT_PART_CHARS * 2] for part in parts]


def _passage(content: str) -> str:
    """The chunk's text without its archive header line, trimmed for display."""
    body = (content or "").split("\n\n", 1)
    text = " ".join((body[1] if len(body) > 1 else body[0]).split())
    return text if len(text) <= PASSAGE_CHARS else text[: PASSAGE_CHARS - 1].rstrip() + "…"


def _similar_chunks(db: Session, owner: uuid.UUID, parts: list[str]) -> tuple[list[dict], str | None]:
    """`published_work` chunks similar to any part of the draft: (chunks, reason if unavailable)."""
    from AINDY.db.dao.memory_node_dao import MemoryNodeDAO
    from AINDY.memory.embedding_service import generate_query_embedding

    dao = MemoryNodeDAO(db)
    chunks: list[dict] = []
    for part in parts:
        try:
            embedding = generate_query_embedding(part)
        except Exception as exc:  # the embedding API; the rest of the report still stands
            logger.warning("[own_links] query embedding failed: %s", exc)
            return chunks, "the relevance service could not be reached"
        for node in dao.find_similar(embedding, limit=CANDIDATES_PER_PART, user_id=str(owner), node_type="insight"):
            if node.get("source") == MEMORY_SOURCE:
                chunks.append(node)
    return chunks, None


def own_piece_links(
    db: Session,
    *,
    user_id,
    text: str,
    title: str | None = None,
    exclude_url: str | None = None,
    missing_limit: int = DEFAULT_MISSING_LIMIT,
) -> dict[str, Any]:
    """What the draft links to among the owner's pieces, what it could link to, and what is external.

    ``title`` and ``exclude_url`` name the draft itself when it is already published, so it is
    never offered as a link to itself.
    """
    owner = _uid(user_id)
    pieces = _owner_pieces(db, owner)
    by_url = {normalize_url(copy["url"]): piece for piece in pieces.values() for copy in piece["copies"]}
    by_drop = {drop_id: piece for piece in pieces.values() for drop_id in piece["drop_ids"]}

    linked: dict[str, dict[str, Any]] = {}
    other_links: list[str] = []
    for url in extract_links(text):
        piece = by_url.get(normalize_url(url))
        if piece is None:
            other_links.append(url)
            continue
        entry = linked.setdefault(piece["key"], {"title": piece["title"], "copies": piece["copies"], "linked_urls": []})
        entry["linked_urls"].append(url)

    itself: set[str] = set()
    if title:
        itself.add(_normalize_title(title))
    if exclude_url:
        piece = by_url.get(normalize_url(exclude_url))
        if piece is not None:
            itself.add(piece["key"])

    chunks, reason = _similar_chunks(db, owner, _draft_parts(text))
    best: dict[str, dict[str, Any]] = {}
    for node in chunks:
        if node.get("source") != MEMORY_SOURCE:  # only the archive of the owner's published pieces
            continue
        extra = node.get("extra") or {}
        piece = by_drop.get(extra.get("drop_point_id"))
        if piece is None or piece["key"] in linked or piece["key"] in itself:
            continue
        similarity = float(node.get("similarity") or 0.0)
        current = best.get(piece["key"])
        if current is None or similarity > current["similarity"]:
            best[piece["key"]] = {"title": piece["title"], "copies": piece["copies"],
                                  "similarity": round(similarity, 4), "passage": _passage(node.get("content", ""))}
    missing = sorted(best.values(), key=lambda item: item["similarity"], reverse=True)[: max(0, int(missing_limit))]

    return {
        "linked": list(linked.values()),
        "missing": missing,
        "other_links": other_links,
        "pieces_known": len(pieces),
        "reason": reason,
    }
