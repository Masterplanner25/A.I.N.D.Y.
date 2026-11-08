"""How one of the owner's published pieces connects to the rest (ARTICLE_ANSWERS_SPEC §3, phase B3).

Authority, the owner's definition: links back to your own relevant pieces. For one piece this reports:

* **links_to**: the owner's other pieces this one links to;
* **linked_from**: the owner's pieces that link to this one (inbound). Possible across platforms since
  B1 kept the links Substack and Medium had lost;
* **series**: in a confirmed series, the previous and next piece, and whether each pair links to the
  other (the *What's Next?* footer);
* **other_links**: how many links go anywhere else.

A piece is every copy of it: copies share a title (as the archive groups cross-posts), so a link to the
DEV copy and a link to the Medium copy both point at the piece. ``unread_copies`` counts copies whose
links are unknown (`content_links` NULL), so a gap in the data is never read as "links to nothing".

Read-only, computed from `drop_points` on request. Only the caller's pieces are ever read.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from apps.rippletrace.drop import DropPointDB
from apps.rippletrace.services.container_service import _normalize as _normalize_title
from apps.rippletrace.services.content_fetch import normalize_url


def _uid(user_id) -> uuid.UUID:
    return user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))


def _pieces(db: Session, owner: uuid.UUID) -> dict[str, dict[str, Any]]:
    """The owner's pieces, one per title, with every copy, its links and the earliest date."""
    rows = (
        db.query(DropPointDB.id, DropPointDB.title, DropPointDB.platform, DropPointDB.url,
                 DropPointDB.date_dropped, DropPointDB.content_links, DropPointDB.tagged_entities)
        .filter(DropPointDB.user_id == owner)
        .all()
    )
    pieces: dict[str, dict[str, Any]] = {}
    for drop_id, title, platform, url, dropped, links, entities in rows:
        key = _normalize_title(title or "") or f"id:{drop_id}"
        piece = pieces.setdefault(key, {"key": key, "title": title or "", "copies": [], "links": [],
                                        "unread": 0, "date": None, "entities": set()})
        piece["copies"].append({"id": drop_id, "platform": platform, "url": url})
        if links is None:
            piece["unread"] += 1
        else:
            piece["links"].extend(links)
        if dropped is not None and (piece["date"] is None or dropped < piece["date"]):
            piece["date"] = dropped
        piece["entities"].update(_normalize_title(e) for e in (entities or "").split(",") if e.strip())
    return pieces


def _summary(piece: dict[str, Any]) -> dict[str, Any]:
    return {"title": piece["title"], "copies": piece["copies"],
            "published": piece["date"].date().isoformat() if isinstance(piece["date"], datetime) else None}


def _targets(piece: dict[str, Any], by_url: dict[str, str]) -> tuple[set[str], int]:
    """The keys of the owner's pieces a piece links to, and how many of its links go elsewhere."""
    own: set[str] = set()
    other = 0
    for url in piece["links"]:
        key = by_url.get(normalize_url(url))
        if key is None:
            other += 1
        elif key != piece["key"]:
            own.add(key)
    return own, other


def _confirmed_series(db: Session, owner: uuid.UUID) -> dict[str, str]:
    from apps.rippletrace.container import CONTAINER_CONFIRMED, ContainerDB

    return {
        _normalize_title(c.name): c.name
        for c in db.query(ContainerDB).filter(ContainerDB.user_id == owner,
                                              ContainerDB.status == CONTAINER_CONFIRMED).all()
    }


def piece_link_report(db: Session, user_id, drop_point_id: str) -> dict[str, Any]:
    """Links to, linked from, and series neighbours for one of the caller's pieces."""
    owner = _uid(user_id)
    row = db.query(DropPointDB.id, DropPointDB.title).filter(
        DropPointDB.id == drop_point_id, DropPointDB.user_id == owner).first()
    if row is None:
        return {"found": False}

    pieces = _pieces(db, owner)
    key = _normalize_title(row.title or "") or f"id:{row.id}"
    me = pieces[key]
    by_url = {normalize_url(c["url"]): p["key"] for p in pieces.values() for c in p["copies"] if c["url"]}

    links_to, other_links = _targets(me, by_url)
    linked_from = [p for p in pieces.values() if p["key"] != key and key in _targets(p, by_url)[0]]

    series_names = _confirmed_series(db, owner)
    series: list[dict[str, Any]] = []
    for normalized in sorted(me["entities"] & set(series_names)):
        members = sorted((p for p in pieces.values() if normalized in p["entities"] and p["date"] is not None),
                         key=lambda p: p["date"])
        keys = [p["key"] for p in members]
        if key not in keys:
            continue
        at = keys.index(key)
        previous = members[at - 1] if at > 0 else None
        nxt = members[at + 1] if at + 1 < len(members) else None
        entry: dict[str, Any] = {"name": series_names[normalized], "position": at + 1, "of": len(members),
                                 "previous": None, "next": None}
        if previous is not None:
            entry["previous"] = {**_summary(previous),
                                 "this_links_to_it": previous["key"] in links_to,
                                 "it_links_here": key in _targets(previous, by_url)[0]}
        if nxt is not None:
            entry["next"] = {**_summary(nxt),
                             "this_links_to_it": nxt["key"] in links_to,
                             "it_links_here": key in _targets(nxt, by_url)[0]}
        series.append(entry)

    return {
        "found": True,
        "drop_point_id": row.id,
        "title": me["title"],
        "links_to": sorted((_summary(pieces[k]) for k in links_to), key=lambda s: s["title"]),
        "linked_from": sorted((_summary(p) for p in linked_from), key=lambda s: s["title"]),
        "other_links": other_links,
        "unread_copies": me["unread"],
        "series": series,
    }
