"""What each published piece answers, stored once per version of its text (ARTICLE_ANSWERS_SPEC phase B2).

The owner's decisions (2026-11-08):
- **gpt-5.5 reads** (decision 1): the same reading as the SEO tool's button (`article_answers`).
- **New pieces only** (decision 3): the migration marked every stored piece ``skipped``. An older
  piece gets answers when the owner asks (`queue_piece_answers`).
- **Not in the Infinity score** (decision 4): stored and shown, nothing more.

Same lifecycle as share drafts (`share_drafts.py`), one set per piece:
- A piece is due once its text is stored and remembered, which is also when its cross-posts have
  been collapsed. A cross-post is the same piece: the earliest copy gets the answers, later copies
  are marked ``cross_post``.
- Stored per ``content_hash``: answers read from older text are kept, and the current text's are
  the ones `get_piece_answers` returns.

`answers_nodus.py` runs this as `piece_answers_v1.nd`, one piece per run.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from apps.rippletrace.drop import DropPointDB
from apps.rippletrace.piece_answers import PieceAnswersDB

logger = logging.getLogger(__name__)

DUE, MADE, FAILED, CROSS_POST, SKIPPED = None, "made", "failed", "cross_post", "skipped"


def _uid(user_id):
    from apps.rippletrace.services.share_drafts import _uid as share_uid

    return share_uid(user_id)


def _canonical(db: Session, row: DropPointDB) -> DropPointDB:
    """The copy that holds the answers: one that already has them, else the first with text."""
    from apps.rippletrace.services.share_drafts import _copies

    copies = _copies(db, row)
    made = [r for r in copies if r.answers == MADE]
    if made:
        return made[0]
    stored = [r for r in copies if r.content_hash]
    return stored[0] if stored else row


def answers_due(db: Session, user_id: Any) -> DropPointDB | None:
    """The oldest piece waiting for answers, or None. Copies found on the way are marked
    ``cross_post`` (and committed) so they are not looked at again."""
    uid = _uid(user_id)
    rows = (
        db.query(DropPointDB)
        .filter(DropPointDB.user_id == uid, DropPointDB.answers.is_(None),
                DropPointDB.content_hash.isnot(None), DropPointDB.content_memory_hash == DropPointDB.content_hash)
        .order_by(DropPointDB.date_dropped.asc().nullslast(), DropPointDB.id)
        .all()
    )
    marked = False
    due = None
    for row in rows:
        if _canonical(db, row).id != row.id:
            row.answers = CROSS_POST
            marked = True
            continue
        due = row
        break
    if marked:
        db.commit()
    return due


def queue_piece_answers(db: Session, user_id: Any, drop_point_id: str) -> dict:
    """The owner asks for a piece's answers (an older one, or again). The next run reads it, within
    about ten minutes. A copy queues its earliest copy instead."""
    row = db.query(DropPointDB).filter(DropPointDB.id == drop_point_id,
                                       DropPointDB.user_id == _uid(user_id)).first()
    if row is None:
        return {"queued": False, "reason": "not_found"}
    target = _canonical(db, row)
    if not target.content_hash:
        return {"queued": False, "reason": "no_text", "drop_point_id": target.id}
    target.answers = DUE
    db.commit()
    return {"queued": True, "drop_point_id": target.id}


def _reader(text: str, *, title: str | None, user_id: Any, db: Session) -> dict:
    from apps.rippletrace.services.article_answers import article_answers

    return article_answers(text, title=title, user_id=str(user_id), db=db)


def make_piece_answers(db: Session, user_id: Any, drop_point_id: str) -> dict:
    """Read one of the owner's pieces and store what it answers. The answers row and the piece's
    mark are one transaction, so a retried run never stores them twice. Raises when nothing usable
    came back, so the caller can fall back or mark it failed."""
    uid = _uid(user_id)
    row = db.query(DropPointDB).filter(DropPointDB.id == drop_point_id, DropPointDB.user_id == uid).first()
    if row is None:
        raise LookupError(f"drop point {drop_point_id} not found")
    if not row.content_hash:
        raise ValueError(f"drop point {drop_point_id} has no stored text")

    existing = (db.query(PieceAnswersDB)
                .filter(PieceAnswersDB.drop_point_id == row.id, PieceAnswersDB.content_hash == row.content_hash)
                .first())
    if existing is not None:  # already read from this exact text: idempotent
        row.answers = MADE
        db.commit()
        return {"drop_point_id": row.id, "answers": len(existing.answers or []), "stored": False}

    reading = _reader(row.content_text or "", title=row.title, user_id=uid, db=db)
    if reading.get("reason"):
        raise RuntimeError(f"no answers for {row.id}: {reading['reason']}")

    db.add(PieceAnswersDB(
        user_id=uid, drop_point_id=row.id, content_hash=row.content_hash,
        answers=reading.get("answers") or [], raised=reading.get("raised") or [],
        answer_range=reading.get("range") or {}, model=reading.get("model"),
    ))
    row.answers = MADE
    db.commit()
    return {"drop_point_id": row.id, "answers": len(reading.get("answers") or []), "stored": True}


def mark_failed(db: Session, drop_point_id: str) -> None:
    """Both paths failed: stop retrying it every tick. The owner can queue it again."""
    db.rollback()
    row = db.query(DropPointDB).filter(DropPointDB.id == drop_point_id).first()
    if row is not None and row.answers is None:
        row.answers = FAILED
        db.commit()


def get_piece_answers(db: Session, user_id: Any, drop_point_id: str) -> dict:
    """The stored answers for one of the caller's pieces, read from its CURRENT text when they exist.

    For a copy, the answers live on its earliest copy (`_canonical`). ``stale`` says the newest stored
    reading was taken from older text. Never reads another user's pieces: not found reads as missing."""
    uid = _uid(user_id)
    row = db.query(DropPointDB).filter(DropPointDB.id == drop_point_id, DropPointDB.user_id == uid).first()
    if row is None:
        return {"found": False}
    holder = _canonical(db, row)
    readings = (db.query(PieceAnswersDB)
                .filter(PieceAnswersDB.drop_point_id == holder.id, PieceAnswersDB.user_id == uid)
                .order_by(PieceAnswersDB.created_at.desc())
                .all())
    current = next((r for r in readings if r.content_hash == holder.content_hash), None)
    chosen = current or (readings[0] if readings else None)
    return {
        "found": True,
        "drop_point_id": row.id,
        "read_from": holder.id,
        "status": holder.answers,
        "stale": chosen is not None and current is None,
        "answers": chosen.answers if chosen else [],
        "raised": chosen.raised if chosen else [],
        "range": chosen.answer_range if chosen else {},
        "model": chosen.model if chosen else None,
        "read_at": chosen.created_at.isoformat() if chosen and chosen.created_at else None,
    }
