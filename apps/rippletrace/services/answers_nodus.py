"""Piece answers: one piece per owner per run, on the Nodus VM or in Python.

The fifth of our `.nd` workflows (owner, 2026-10-22: new workflows are written in Nodus). Same shape as
share drafts (`share_nodus.py`): the scheduled job finds the owner's next due piece in Python, so a
quiet tick starts no worker, then hands that one piece to `piece_answers_v1.nd` behind
`AINDY_PIECE_ANSWERS_NODUS` (off in code, on in compose). Any VM failure falls back to Python for that
piece, recorded with `record_nodus_fallback`. If both fail, the piece is marked ``failed`` rather than
retried every tick, and the owner can queue it again.

**One piece a run.** The gpt-5.5 read takes 18-50 s (18 s measured on 2026-11-08), and a cold worker
17-21 s, inside the callback's 90 s. New pieces arrive a few a month.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

from sqlalchemy.orm import Session

from apps.rippletrace.drop import DropPointDB

logger = logging.getLogger(__name__)

_FLAG = "AINDY_PIECE_ANSWERS_NODUS"
_TRUTHY = {"1", "true", "yes", "on"}
_WORKFLOW = "piece_answers_v1"
JOB_INTERVAL_MINUTES = 10

_lock = threading.Lock()


def nodus_answers_enabled() -> bool:
    return os.environ.get(_FLAG, "").strip().lower() in _TRUTHY


def answers_owner(db: Session, user_id: Any) -> tuple[dict | None, str]:
    """The owner's next due piece, if any. Returns ``(outcome, via)``: via ``nodus``, ``python``,
    ``none`` (nothing due) or ``failed``."""
    from apps.rippletrace.services.piece_answers import answers_due, make_piece_answers, mark_failed

    row = answers_due(db, user_id)
    if row is None:
        return None, "none"
    piece = row.id
    if nodus_answers_enabled():
        reason: object = "the VM run did not report success"
        try:
            outcome = _answers_via_nodus(db, user_id, piece)
            if outcome is not None:
                return outcome, "nodus"
            logger.warning("[piece_answers] nodus run failed for %s; falling back to python", piece)
        except Exception as exc:  # pragma: no cover - defensive
            reason = exc
            logger.warning("[piece_answers] nodus run raised for %s, falling back to python: %s", piece, exc)
        db.rollback()
        from apps._shared.nodus import record_nodus_fallback

        record_nodus_fallback(db, workflow=_WORKFLOW, user_id=user_id, reason=reason)
    try:
        return make_piece_answers(db, user_id, piece), "python"
    except Exception as exc:
        logger.warning("[piece_answers] %s failed: %s", piece, exc)
        mark_failed(db, piece)
        return {"answers": 0, "drop_point_id": piece, "error": str(exc)}, "failed"


def _answers_via_nodus(db: Session, user_id: Any, drop_point_id: str) -> dict | None:
    from apps._shared.nodus import run_domain_nodus_workflow

    out = run_domain_nodus_workflow(
        "rippletrace",
        _WORKFLOW,
        db=db,
        user_id=str(user_id),
        input_payload={"args": {"drop_point_id": drop_point_id}},
    )
    return _outcome(out)


def _outcome(out: dict[str, Any] | None) -> dict | None:
    """The step's result, or None unless it succeeded (`set_state` lands at `data.nodus_output_state`)."""
    data = (out or {}).get("data") or {}
    if str(data.get("nodus_status") or "").lower() != "success":
        return None
    envelope = (data.get("nodus_output_state") or {}).get("answers_result") or {}
    if str(envelope.get("status") or "").lower() != "success":
        return None
    return envelope.get("data") or {}


def write_piece_answers() -> dict:
    """Scheduled job body: one due piece per owner. Its own session and a non-blocking guard, since
    the scheduler does not prevent overlap."""
    if not _lock.acquire(blocking=False):
        return {"skipped": True, "reason": "already_running"}
    from AINDY.db.database import SessionLocal

    db = SessionLocal()
    summary: dict[str, Any] = {"owners": 0, "answered": 0, "via_nodus": 0, "failed": 0, "skipped": False}
    try:
        owners = {
            row[0] for row in db.query(DropPointDB.user_id).filter(
                DropPointDB.user_id.isnot(None), DropPointDB.answers.is_(None),
                DropPointDB.content_hash.isnot(None),
            ).distinct()
        }
        for owner in owners:
            outcome, via = answers_owner(db, owner)
            if via == "none":
                continue
            summary["owners"] += 1
            summary["answered"] += via in {"nodus", "python"}
            summary["via_nodus"] += via == "nodus"
            summary["failed"] += via == "failed"
    except Exception as exc:
        logger.warning("[piece_answers] run failed: %s", exc)
        summary["error"] = str(exc)
    finally:
        db.close()
        _lock.release()
    return summary
