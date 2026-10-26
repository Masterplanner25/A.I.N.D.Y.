"""Share drafts — what to post once a piece is published, written from the piece itself.

Owner, 2026-10-25: after publishing, they took each article to ChatGPT for a LinkedIn post built on
its central lesson, a meta description and the previous article's *What's Next?* footer. That half of
the editorial process can be automated; the half before publication needs the author. So once a
piece's text is stored, A.I.N.D.Y. writes four drafts into the Drafts section, for the owner to copy
and send by hand. Nothing is posted.

| kind | what |
|---|---|
| ``linkedin_post`` | a standalone post on the piece's central point, not promotion |
| ``short_post`` | one or two lines of the same point |
| ``meta_description`` | the point, within the description budget, keeping the title's framing |
| ``series_footer`` | the PREVIOUS piece in its series, its *What's Next?* rewritten to link this one |

Rules, each the owner's:
- **New pieces only.** The migration marked every stored piece ``skipped``; an older piece gets drafts
  when the owner asks (`queue_piece`).
- **One set per piece.** A cross-post is the same piece: the earliest copy gets the drafts, the others
  are marked ``cross_post``.
- **Links are ours, not the model's.** The piece's url is appended to the posts by this code, and a
  footer that lost the link gets it back, so a draft never carries an invented address.

The model reads the whole piece (as the SEO tool does since #495) and says the central point it found,
which every draft states in its brief: a reading that is wrong looks wrong.

`share_nodus.py` runs this as `share_drafts_v1.nd`, one piece per run.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Callable

from sqlalchemy.orm import Session

from apps.rippletrace.drop import DropPointDB

logger = logging.getLogger(__name__)

#: gpt-5.5, the drafter's model: it follows a multi-part brief where gpt-4o skipped parts (WORK_MODEL_SPEC).
MODEL = "gpt-5.5"
REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4")
REASONING_MAX_TOKENS = 16_000
REASONING_EFFORT = "low"
#: The whole piece, bounded like every external call here; stored text is capped at 50,000 anyway.
ARTICLE_MAX_CHARS = 60_000
#: The end of the previous piece, where its What's Next? section is.
PREVIOUS_TAIL_CHARS = 5_000
META_BUDGET = 160
SHORT_POST_BUDGET = 280

DUE, MADE, FAILED, CROSS_POST, SKIPPED = None, "made", "failed", "cross_post", "skipped"

_SYSTEM = """You prepare share material for a piece the writer has just published.

First read the WHOLE piece and decide its central point: the lesson or discovery it exists to deliver,
in the writer's own terms. Not its most frequent topic, and not a theme it passes through.

Then write, from that point:
- linkedin_post: a standalone LinkedIn post that teaches the central point, so it is worth reading
  without clicking. In the writer's voice as it shows in the piece. 120 to 250 words. No "excited to
  share", no emoji, at most three hashtags. Do NOT include any link: one is added after your text.
- short_post: the same point in one or two lines, at most 230 characters. No link.
- meta_description: at most 160 characters, the central point, keeping the framing of the title.
- series_footer: only when a PREVIOUS PIECE is given. Rewrite the previous piece's "What's Next?"
  section (or its closing section that points readers onward) so it links to this new piece, using
  exactly the NEW PIECE LINK given. Keep that section's format, headings and existing links. If it has
  no such section, write a short one that fits how it ends. When no previous piece is given, null.

Never introduce a claim, number, name or result that is not in the piece.

Return ONLY valid JSON:
{"central_point": "...", "linkedin_post": "...", "short_post": "...", "meta_description": "...",
 "series_footer": "..." or null}"""


def _uid(user_id):
    from apps.rippletrace.services.content_archive import _uid as archive_uid

    return archive_uid(user_id)


def _normalize(text: str) -> str:
    from apps.rippletrace.services.container_service import _normalize as container_normalize

    return container_normalize(text or "")


# ── Which piece ─────────────────────────────────────────────────────────────────────────


def _copies(db: Session, row: DropPointDB) -> list[DropPointDB]:
    """Every copy of the piece (same title, any platform), earliest first."""
    key = _normalize(row.title)
    if not key:
        return [row]
    candidates = db.query(DropPointDB).filter(DropPointDB.user_id == row.user_id).all()
    same = [r for r in candidates if _normalize(r.title) == key]
    return sorted(same, key=lambda r: (r.date_dropped is None, r.date_dropped, r.id))


def _canonical(db: Session, row: DropPointDB) -> DropPointDB:
    """The copy that gets the drafts: the earliest one with text."""
    stored = [r for r in _copies(db, row) if r.content_hash]
    return stored[0] if stored else row


def share_due(db: Session, user_id: Any) -> DropPointDB | None:
    """The oldest piece waiting for drafts, or None. A piece waits until its text is stored and
    remembered, which is also when its cross-posts have been collapsed. Copies found on the way are
    marked ``cross_post`` (and committed) so they are not looked at again."""
    uid = _uid(user_id)
    rows = (
        db.query(DropPointDB)
        .filter(DropPointDB.user_id == uid, DropPointDB.share_drafts.is_(None),
                DropPointDB.content_hash.isnot(None), DropPointDB.content_memory_hash == DropPointDB.content_hash)
        .order_by(DropPointDB.date_dropped.asc().nullslast(), DropPointDB.id)
        .all()
    )
    marked = False
    due = None
    for row in rows:
        if _canonical(db, row).id != row.id:
            row.share_drafts = CROSS_POST
            marked = True
            continue
        due = row
        break
    if marked:
        db.commit()
    return due


def queue_piece(db: Session, user_id: Any, drop_point_id: str) -> dict:
    """The owner asks for drafts for a piece (an older one, or again). It joins the queue: the next
    run writes them, within about ten minutes. A copy queues its earliest copy instead."""
    row = db.query(DropPointDB).filter(DropPointDB.id == drop_point_id,
                                       DropPointDB.user_id == _uid(user_id)).first()
    if row is None:
        return {"queued": False, "reason": "not_found"}
    target = _canonical(db, row)
    if not target.content_hash:
        return {"queued": False, "reason": "no_text", "drop_point_id": target.id}
    target.share_drafts = DUE
    db.commit()
    return {"queued": True, "drop_point_id": target.id}


def previous_in_series(db: Session, row: DropPointDB) -> tuple[str, DropPointDB] | None:
    """The piece before this one in the same confirmed series, as ``(series name, piece)``."""
    from apps.rippletrace.container import CONTAINER_CONFIRMED, ContainerDB

    series = {
        _normalize(c.name): c.name
        for c in db.query(ContainerDB).filter(ContainerDB.user_id == row.user_id,
                                              ContainerDB.status == CONTAINER_CONFIRMED).all()
    }
    mine = [series[_normalize(e)] for e in (row.tagged_entities or "").split(",") if _normalize(e) in series]
    if not mine or row.date_dropped is None:
        return None
    name = mine[0]
    earlier = (
        db.query(DropPointDB)
        .filter(DropPointDB.user_id == row.user_id, DropPointDB.content_hash.isnot(None),
                DropPointDB.date_dropped < row.date_dropped, DropPointDB.id != row.id)
        .order_by(DropPointDB.date_dropped.desc())
        .all()
    )
    own_key = _normalize(row.title)
    for candidate in earlier:
        if _normalize(candidate.title) == own_key:
            continue
        entities = {_normalize(e) for e in (candidate.tagged_entities or "").split(",")}
        if _normalize(name) in entities and _canonical(db, candidate).id == candidate.id:
            return name, candidate
    return None


# ── The model ───────────────────────────────────────────────────────────────────────────


def _model() -> str:
    return (os.getenv("AINDY_SHARE_DRAFTS_MODEL") or "").strip() or MODEL


def _sampling(model: str) -> dict:
    if model.startswith(REASONING_PREFIXES):
        return {"max_completion_tokens": REASONING_MAX_TOKENS, "reasoning_effort": REASONING_EFFORT}
    return {"temperature": 0.5, "max_tokens": 3_000}


def _complete(prompt: str, *, db: Session, user_id: Any) -> str:
    from AINDY.config import settings
    from AINDY.platform_layer.external_call_service import perform_external_call
    from AINDY.platform_layer.openai_client import chat_completion, get_openai_client

    model = _model()
    completion = perform_external_call(
        service_name="openai",
        db=db,
        user_id=str(user_id),
        endpoint="chat.completions.create",
        model=model,
        method="openai.chat",
        extra={"purpose": "share_drafts"},
        operation=lambda: chat_completion(
            get_openai_client(),
            model=model,
            messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            timeout=max(float(settings.OPENAI_CHAT_TIMEOUT_SECONDS or 0), 120.0),
            **_sampling(model),
        ),
    )
    return (completion.choices[0].message.content or "").strip()


def build_prompt(row: DropPointDB, url: str, previous: tuple[str, DropPointDB] | None,
                 previous_link: str | None) -> str:
    parts = [f'NEW PIECE: "{row.title}" ({row.platform})', f"NEW PIECE LINK: {previous_link or url}"]
    if previous:
        series, prev = previous
        tail = (prev.content_text or "")[-PREVIOUS_TAIL_CHARS:]
        parts.append(f'PREVIOUS PIECE in the series "{series}": "{prev.title}" ({prev.platform})\n'
                     f"Its ending:\n{tail}")
    else:
        parts.append("PREVIOUS PIECE: none")
    parts.append("THE NEW PIECE, WHOLE:\n" + (row.content_text or "")[:ARTICLE_MAX_CHARS])
    return "\n\n".join(parts)


def parse(content: str) -> dict:
    text = (content or "").strip()
    if not text.startswith("{"):
        match = re.search(r"\{.*\}", text, re.DOTALL)
        text = match.group(0) if match else ""
    try:
        payload = json.loads(text) if text else {}
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        return {}
    out: dict = {}
    for key, value in payload.items():
        if not isinstance(value, str):
            out[key] = None
        elif key in ("linkedin_post", "series_footer"):
            out[key] = value.strip()  # paragraphs matter in these two
        else:
            out[key] = " ".join(value.split())
    return out


# ── The drafts ──────────────────────────────────────────────────────────────────────────


def _drafts(row: DropPointDB, url: str, reading: dict, previous: tuple[str, DropPointDB] | None,
            previous_link: str | None) -> list[dict]:
    point = reading.get("central_point") or ""
    brief = f"Read as: {point}" if point else ""
    out = []
    if reading.get("linkedin_post"):
        out.append({"kind": "linkedin_post", "title": f"LinkedIn post: {row.title}",
                    "body": f"{reading['linkedin_post']}\n\n{url}", "brief": brief})
    if reading.get("short_post"):
        out.append({"kind": "short_post", "title": f"Short post: {row.title}",
                    "body": f"{reading['short_post']} {url}", "brief": brief})
    meta = reading.get("meta_description")
    if meta:
        out.append({"kind": "meta_description",
                    "title": f"Meta description ({len(meta)} of {META_BUDGET} characters): {row.title}",
                    "body": meta, "brief": brief})
    footer = reading.get("series_footer")
    if previous and footer:
        series, prev = previous
        link = previous_link or url
        if link not in footer:
            footer = f"{footer}\n\nNext: [{row.title}]({link})"
        out.append({"kind": "series_footer", "title": f"What's Next? for “{prev.title}”",
                    "body": footer,
                    "brief": f"Paste into “{prev.title}” ({prev.url}), {series}. {brief}".strip()})
    return out


def make_share_drafts(db: Session, user_id: Any, drop_point_id: str, *,
                      complete: Callable[..., str] | None = None) -> dict:
    """Write and save one piece's share drafts, and mark it made, in one transaction. Idempotent: a
    piece already made returns without a model call, so a retried step cannot write a second set."""
    from AINDY.platform_layer.registry import get_job

    uid = _uid(user_id)
    row = db.query(DropPointDB).filter(DropPointDB.id == drop_point_id, DropPointDB.user_id == uid).first()
    if row is None:
        return {"made": 0, "reason": "not_found", "drop_point_id": drop_point_id}
    if row.share_drafts == MADE:
        return {"made": 0, "reason": "already_made", "drop_point_id": row.id}
    if not row.content_text:
        return {"made": 0, "reason": "no_text", "drop_point_id": row.id}

    previous = previous_in_series(db, row)
    previous_link = None
    if previous:
        # The footer goes into the previous piece where it lives, so it links this piece's copy on
        # the same platform when there is one.
        same_platform = [c for c in _copies(db, row) if c.platform == previous[1].platform and c.url]
        previous_link = same_platform[0].url if same_platform else None
    url = row.url or ""

    raw = (complete or _complete)(build_prompt(row, url, previous, previous_link), db=db, user_id=uid)
    reading = parse(raw)
    items = _drafts(row, url, reading, previous, previous_link)
    if not items:
        raise ValueError("the model returned no usable share drafts")

    save = get_job("masterplan.save_share_drafts")
    if save is None:
        raise RuntimeError("masterplan.save_share_drafts is not registered")
    ids = save(user_id=uid, drop_point_id=row.id,
               piece={"title": row.title, "url": row.url, "platform": row.platform},
               items=items, model=_model(), db=db)
    row.share_drafts = MADE
    db.commit()
    return {"made": len(ids), "drop_point_id": row.id, "title": row.title,
            "kinds": [i["kind"] for i in items], "series_footer": bool(previous)}


def mark_failed(db: Session, drop_point_id: str) -> None:
    """Both paths failed: stop retrying it every tick. The owner can queue it again."""
    db.rollback()
    row = db.query(DropPointDB).filter(DropPointDB.id == drop_point_id).first()
    if row is not None and row.share_drafts is None:
        row.share_drafts = FAILED
        db.commit()
