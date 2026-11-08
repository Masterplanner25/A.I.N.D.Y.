"""A series' published pieces, as text, for the SEO tool's structure view (ARTICLE_ANSWERS_SPEC §5, phase D2).

A series is one of the owner's CONFIRMED series (RippleTrace containers); a piece belongs to it when its stored entities
name it, the same membership `piece_links` uses. One text per piece: the longest stored copy across platforms, since a
cross-post can be a trimmed version of the same piece. Only the caller's pieces are read. No model call.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from apps.rippletrace.drop import DropPointDB
from apps.rippletrace.services.container_service import _normalize as _normalize_title

MAX_PIECES = 30  # the most recent, which is where a series' current shape is


def _uid(user_id: Any) -> uuid.UUID:
    return user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))


def confirmed_series(db: Session, owner: uuid.UUID) -> dict[str, str]:
    """Normalised name → name, for the owner's confirmed series."""
    from apps.rippletrace.container import CONTAINER_CONFIRMED, ContainerDB

    return {
        _normalize_title(c.name): c.name
        for c in db.query(ContainerDB.name).filter(ContainerDB.user_id == owner,
                                                   ContainerDB.status == CONTAINER_CONFIRMED).all()
        if c.name
    }


def pick_series(names: dict[str, str], *, title: str | None, series: str | None) -> str | None:
    """The series the writer named, else the one the draft's title starts with (the longest such name)."""
    if series:
        return names.get(_normalize_title(series))
    normalized = _normalize_title(title or "")
    matches = [key for key in names if key and normalized.startswith(key)]
    return names[max(matches, key=len)] if matches else None


def series_pieces(db: Session, user_id: Any, *, title: str | None = None, series: str | None = None,
                  exclude_title: str | None = None) -> dict[str, Any]:
    """The draft's series and its published pieces' text, newest first. ``exclude_title`` leaves the draft
    itself out when it is already published."""
    owner = _uid(user_id)
    names = confirmed_series(db, owner)
    chosen = pick_series(names, title=title, series=series)
    result: dict[str, Any] = {"series": chosen, "options": sorted(names.values(), key=str.lower), "pieces": []}
    if chosen is None:
        return result

    target = _normalize_title(chosen)
    skip = _normalize_title(exclude_title or "") or None
    rows = (
        db.query(DropPointDB.title, DropPointDB.content_text, DropPointDB.date_dropped, DropPointDB.tagged_entities)
        .filter(DropPointDB.user_id == owner, DropPointDB.content_text.isnot(None))
        .all()
    )
    pieces: dict[str, dict[str, Any]] = {}
    for title_, text, dropped, entities in rows:
        names_in = {_normalize_title(e) for e in (entities or "").split(",") if e.strip()}
        key = _normalize_title(title_ or "")
        if target not in names_in or not key or key == skip:
            continue
        piece = pieces.setdefault(key, {"title": title_ or "", "text": "", "date": None})
        if len(text or "") > len(piece["text"]):
            piece["text"] = text or ""
        if dropped is not None and (piece["date"] is None or dropped < piece["date"]):
            piece["date"] = dropped
    ordered = sorted(pieces.values(), key=lambda p: (p["date"] is not None, p["date"]), reverse=True)[:MAX_PIECES]
    result["pieces"] = [{"title": p["title"], "text": p["text"],
                         "published": p["date"].date().isoformat() if p["date"] is not None else None}
                        for p in ordered]
    return result
