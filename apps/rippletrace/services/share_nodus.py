"""Share drafts — one piece per owner per run, on the Nodus VM or in Python.

The fourth of our `.nd` workflows (owner, 2026-10-22: new workflows are written in Nodus). The
scheduled job finds the owner's next due piece in Python, so a quiet tick starts no worker, then
hands that one piece to `share_drafts_v1.nd` behind `AINDY_SHARE_DRAFTS_NODUS` (off in code, on in
compose). Any VM failure falls back to Python for that piece; if both fail the piece is marked
``failed`` rather than retried every tick, and the owner can queue it again.

**One piece a run.** The model call takes 25-50 s, and a cold worker 17-21 s, inside the callback's
90 s. A backlog drains a piece every ten minutes, which suits a publishing rate of a few a month.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

from sqlalchemy.orm import Session

from apps.rippletrace.drop import DropPointDB

logger = logging.getLogger(__name__)

_FLAG = "AINDY_SHARE_DRAFTS_NODUS"
_TRUTHY = {"1", "true", "yes", "on"}
_WORKFLOW = "share_drafts_v1"
JOB_INTERVAL_MINUTES = 10

_lock = threading.Lock()


def nodus_share_enabled() -> bool:
    return os.environ.get(_FLAG, "").strip().lower() in _TRUTHY


def share_owner(db: Session, user_id: Any) -> tuple[dict | None, str]:
    """The owner's next due piece, if any. Returns ``(outcome, via)``: via ``nodus``, ``python``,
    ``none`` (nothing due) or ``failed``."""
    from apps.rippletrace.services.share_drafts import make_share_drafts, mark_failed, share_due

    row = share_due(db, user_id)
    if row is None:
        return None, "none"
    piece = row.id
    if nodus_share_enabled():
        try:
            outcome = _share_via_nodus(db, user_id, piece)
            if outcome is not None:
                return outcome, "nodus"
            logger.warning("[share_drafts] nodus run failed for %s; falling back to python", piece)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[share_drafts] nodus run raised for %s, falling back to python: %s", piece, exc)
        db.rollback()
    try:
        return make_share_drafts(db, user_id, piece), "python"
    except Exception as exc:
        logger.warning("[share_drafts] %s failed: %s", piece, exc)
        mark_failed(db, piece)
        return {"made": 0, "drop_point_id": piece, "error": str(exc)}, "failed"


def _share_via_nodus(db: Session, user_id: Any, drop_point_id: str) -> dict | None:
    from AINDY.runtime.nodus_workflow_registry import run_nodus_workflow

    out = run_nodus_workflow(
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
    envelope = (data.get("nodus_output_state") or {}).get("share_result") or {}
    if str(envelope.get("status") or "").lower() != "success":
        return None
    return envelope.get("data") or {}


def write_share_drafts() -> dict:
    """Scheduled job body: one due piece per owner. Its own session and a non-blocking guard, like the
    archive job, since the scheduler does not prevent overlap."""
    if not _lock.acquire(blocking=False):
        return {"skipped": True, "reason": "already_running"}
    from AINDY.db.database import SessionLocal

    db = SessionLocal()
    summary: dict[str, Any] = {"owners": 0, "made": 0, "via_nodus": 0, "failed": 0, "skipped": False}
    try:
        owners = {
            row[0] for row in db.query(DropPointDB.user_id).filter(
                DropPointDB.user_id.isnot(None), DropPointDB.share_drafts.is_(None),
                DropPointDB.content_hash.isnot(None),
            ).distinct()
        }
        for owner in owners:
            outcome, via = share_owner(db, owner)
            if via == "none":
                continue
            summary["owners"] += 1
            summary["made"] += int((outcome or {}).get("made") or 0)
            summary["via_nodus"] += via == "nodus"
            summary["failed"] += via == "failed"
    except Exception as exc:
        logger.warning("[share_drafts] run failed: %s", exc)
        summary["error"] = str(exc)
    finally:
        db.close()
        _lock.release()
    return summary
