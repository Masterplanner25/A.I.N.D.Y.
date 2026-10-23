"""Daily Infinity recalculation — one user's run, on the Nodus VM or in Python.

Owner, 2026-10-22: our own workflows are written in Nodus. The daily job
(`_scheduler_recalculate_all_scores`) keeps the autonomy gate and the user list, and hands each
user to `infinity_recalc_v1.nd` behind `AINDY_INFINITY_RECALC_NODUS` (default off in code, on in
compose). The workflow calls `sys.v1.score.recalculate`, which runs the same orchestrator the job
called directly and reads the user from the run, never from the payload — so each run is the
user's own and nothing reaches the identity-mismatch counter. Any Nodus failure falls back to the
Python path for that user, so a VM fault never costs a score.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_FLAG = "AINDY_INFINITY_RECALC_NODUS"
_TRUTHY = {"1", "true", "yes", "on"}
_WORKFLOW = "infinity_recalc_v1"
_TRIGGER_EVENT = "scheduled"


def nodus_recalc_enabled() -> bool:
    """Whether the daily recalculation routes each user through the Nodus VM."""
    return os.environ.get(_FLAG, "").strip().lower() in _TRUTHY


def recalculate_user(db: Any, user_id: Any) -> tuple[bool, str]:
    """Recalculate one user's Infinity score. Returns ``(ok, via)``, via ``nodus`` or ``python``."""
    if nodus_recalc_enabled():
        try:
            if _recalc_via_nodus(db, user_id):
                return True, "nodus"
            logger.warning("[Infinity Scheduler] nodus recalc failed for %s; falling back to python", user_id)
        except Exception as exc:  # pragma: no cover - defensive; the score must not be lost
            logger.warning("[Infinity Scheduler] nodus recalc raised for %s, falling back to python: %s", user_id, exc)
    return bool(_recalc_via_python(db, user_id)), "python"


def _recalc_via_python(db: Any, user_id: Any) -> Any:
    from apps.analytics.services.orchestration.infinity_orchestrator import execute

    return execute(user_id=str(user_id), db=db, trigger_event=_TRIGGER_EVENT)


def _recalc_via_nodus(db: Any, user_id: Any) -> bool:
    from AINDY.runtime.nodus_workflow_registry import run_nodus_workflow

    out = run_nodus_workflow(
        _WORKFLOW,
        db=db,
        user_id=str(user_id),
        input_payload={"args": {"trigger_event": _TRIGGER_EVENT}},
    )
    return _succeeded(out)


def _succeeded(out: dict[str, Any] | None) -> bool:
    """True when the VM run and the syscall inside it both succeeded with a score.

    The VM surfaces ``set_state`` at ``data.nodus_output_state``; the step stores the syscall
    envelope under ``infinity_recalc_result``, whose data is ``{"score_recalculate_result": …}``.
    """
    data = (out or {}).get("data") or {}
    if str(data.get("nodus_status") or "").lower() != "success":
        return False
    envelope = (data.get("nodus_output_state") or {}).get("infinity_recalc_result") or {}
    if str(envelope.get("status") or "").lower() != "success":
        return False
    return bool((envelope.get("data") or {}).get("score_recalculate_result"))
