"""Archiving published work — one owner's batch, on the Nodus VM or in Python.

Owner, 2026-10-22: our own workflows are written in Nodus. `archive_published_work` keeps its lock,
its session and the owner list, and hands each owner to `archive_published_work_v1.nd` behind
`AINDY_ARCHIVE_NODUS` (default off in code, on in compose). The workflow runs the four steps of
`content_archive.archive_step` as four syscalls, each retried by Nodus, each for the run's own user.

**Only an owner with something due goes to Nodus.** The job fires every 10 minutes from a fresh
callback process, so every VM run pays a cold worker (~17 s, `CLAUDE.md`). A settled catalogue,
the normal case, stays on the Python path, which costs a few small queries. The Nodus batch is
smaller than Python's (`NODUS_BATCH`) so a cold worker plus a full fetch stays inside the
callback's 90 s. Any VM failure falls back to Python for that owner.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from sqlalchemy.orm import Session

from apps.rippletrace.drop import DropPointDB

logger = logging.getLogger(__name__)

_FLAG = "AINDY_ARCHIVE_NODUS"
_TRUTHY = {"1", "true", "yes", "on"}
_WORKFLOW = "archive_published_work_v1"
#: Pieces per step on the Nodus path. New pieces arrive one or two at a time once the catalogue is
#: done; a fetch pauses 0.5 s a piece, so 10 keeps the run well inside the callback budget.
NODUS_BATCH = 10
#: The keys the four steps' results are stored under (`set_state`), in step order.
STEP_KEYS = ("reclean_result", "fetch_result", "collapse_result", "remember_result")


def nodus_archive_enabled() -> bool:
    return os.environ.get(_FLAG, "").strip().lower() in _TRUTHY


def archive_due(db: Session, user_id: Any) -> bool:
    """Whether a step has work for this owner: text to fetch, memory older than its text, or text
    stored before `to_text` cleaned it (`reclean_stored`'s match). Cross-posts are not checked:
    a new copy always arrives as text to fetch or to remember first."""
    from apps.rippletrace.services.content_archive import _uid

    uid = _uid(user_id)
    text = DropPointDB.content_text
    return db.query(
        db.query(DropPointDB).filter(
            DropPointDB.user_id == uid,
            DropPointDB.content_source.is_(None)
            | (DropPointDB.content_hash.isnot(None)
               & (DropPointDB.content_memory_hash.is_(None) | (DropPointDB.content_memory_hash != DropPointDB.content_hash)))
            | (text.isnot(None) & (text.like("---%") | text.like("%![%") | text.ilike("%<img%"))),
        ).exists()
    ).scalar()


def archive_owner(db: Session, user_id: Any) -> tuple[dict, str]:
    """One batch for one owner. Returns ``(outcome, via)``, via ``nodus`` or ``python``."""
    if nodus_archive_enabled() and archive_due(db, user_id):
        try:
            outcome = _archive_via_nodus(db, user_id)
            if outcome is not None:
                return outcome, "nodus"
            logger.warning("[content_archive] nodus run failed for %s; falling back to python", user_id)
        except Exception as exc:  # pragma: no cover - defensive; the batch must not be lost
            logger.warning("[content_archive] nodus run raised for %s, falling back to python: %s", user_id, exc)
        db.rollback()
    from apps.rippletrace.services.content_archive import archive_step

    return archive_step(db, user_id=user_id), "python"


def _archive_via_nodus(db: Session, user_id: Any) -> dict | None:
    from AINDY.runtime.nodus_workflow_registry import run_nodus_workflow

    out = run_nodus_workflow(
        _WORKFLOW,
        db=db,
        user_id=str(user_id),
        input_payload={"args": {"limit": NODUS_BATCH}},
    )
    return _outcome(out)


def _outcome(out: dict[str, Any] | None) -> dict | None:
    """The four steps' results merged, like `archive_step`'s, or None unless all four succeeded.

    The VM surfaces ``set_state`` at ``data.nodus_output_state``; each step stores its syscall
    envelope under its key in `STEP_KEYS`.
    """
    data = (out or {}).get("data") or {}
    if str(data.get("nodus_status") or "").lower() != "success":
        return None
    state = data.get("nodus_output_state") or {}
    merged: dict[str, Any] = {}
    for key in STEP_KEYS:
        envelope = state.get(key) or {}
        if str(envelope.get("status") or "").lower() != "success":
            return None
        merged.update(envelope.get("data") or {})
    return merged
