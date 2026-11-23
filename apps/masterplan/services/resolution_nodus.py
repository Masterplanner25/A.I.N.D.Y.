"""The Resolution Check on the Nodus VM — one workflow per check, sleeping between batches (FR-55).

Until runtime 2.39.0 a guest Nodus script could not sleep until a time, so the check stayed a Python
tick: every minute `resolution_tick` answered six (question, engine) pairs of every open check. Behind
`AINDY_RESOLUTION_NODUS` (off in code, on in compose) the tick instead hands a new check to
`resolution_check_v1.nd`, which answers one batch per wake through `sys.v1.resolution.update_run` and
sleeps between batches with `await_event_for`. The tick stays as the launcher and the fallback:

* **Launch.** A `pending` check with no driver is started on the VM. The script's first run only parks
  (one second), so the tick's callback, a fresh process with a 90 s budget, pays the cold worker and
  nothing more. Only then is the check marked `driver="nodus"` with the flow run's id.
* **Leave alone.** While that flow run is waiting or executing, the tick does not touch the check, so
  no pair is answered twice.
* **Fall back.** If the flow run failed, finished with the check still open, or is missing, the check
  goes back to Python (`driver=None`) and a `nodus.fallback` event is recorded. Answers already stored
  are kept: `process_run` skips every pair that has a row.
"""
from __future__ import annotations

import logging
import math
import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from apps.masterplan.work_model import ResolutionAnswer, ResolutionRun

logger = logging.getLogger(__name__)

_FLAG = "AINDY_RESOLUTION_NODUS"
_TRUTHY = {"1", "true", "yes", "on"}
WORKFLOW = "resolution_check_v1"
DRIVER = "nodus"
#: Seconds between batches. Python's tick is a minute from start to start, batch included; a batch
#: takes most of half a minute and the runtime delivers a deadline within ~15 s, so 30 keeps the pace.
SLEEP_SECONDS = 30
#: Extra batches beyond the pairs' own count before the script stops and leaves the rest to Python.
SPARE_BATCHES = 2
#: Flow-run states in which the workflow still owns the check.
LIVE_FLOW_STATES = {"pending", "running", "executing", "waiting"}


def nodus_resolution_enabled() -> bool:
    return os.environ.get(_FLAG, "").strip().lower() in _TRUTHY


def _pairs(run: ResolutionRun) -> int:
    return len(run.questions or []) * len(run.engines or [])


def max_batches(run: ResolutionRun, per_batch: int) -> int:
    return math.ceil(_pairs(run) / max(per_batch, 1)) + SPARE_BATCHES


def remaining_pairs(db: Session, run: ResolutionRun) -> int:
    answered = db.query(ResolutionAnswer).filter(ResolutionAnswer.run_id == run.id).count()
    return max(_pairs(run) - answered, 0)


def _flow_status(db: Session, flow_run_id: str | None) -> str | None:
    if not flow_run_id:
        return None
    from AINDY.db.models.flow_run import FlowRun

    row = db.query(FlowRun.status).filter(FlowRun.id == flow_run_id).first()
    return str(row[0]).lower() if row else None


def launch(db: Session, run: ResolutionRun, *, per_batch: int) -> bool:
    """Start the workflow for one pending check. True if it parked and now owns the check."""
    from apps._shared.nodus import run_domain_nodus_workflow

    reason: object = "the VM run did not park"
    try:
        out = run_domain_nodus_workflow(
            "masterplan",
            WORKFLOW,
            db=db,
            user_id=str(run.user_id),
            input_payload={"args": {"run_id": run.id, "max_batches": max_batches(run, per_batch),
                                    "sleep_seconds": SLEEP_SECONDS}},
        )
        status = str((out or {}).get("status") or "").upper()
        flow_run_id = (out or {}).get("run_id")
        if status == "WAITING" and flow_run_id:
            run.driver, run.driver_run_id, run.status = DRIVER, str(flow_run_id), "running"
            db.commit()
            logger.info("[resolution] check %s handed to nodus run %s", run.id, flow_run_id)
            return True
        reason = f"status={status or 'none'} run_id={flow_run_id}"
    except Exception as exc:
        reason = exc
        logger.warning("[resolution] nodus launch raised for check %s: %s", run.id, exc)
    db.rollback()
    _fall_back(db, run, reason)
    return False


def owned_by_nodus(db: Session, run: ResolutionRun) -> bool:
    """Whether the workflow still drives this check. A dead one hands the check back to Python here."""
    if run.driver != DRIVER:
        return False
    status = _flow_status(db, run.driver_run_id)
    if status in LIVE_FLOW_STATES:
        return True
    _fall_back(db, run, f"flow run {run.driver_run_id} is {status or 'missing'} with the check still {run.status}")
    return False


def _fall_back(db: Session, run: ResolutionRun, reason: object) -> None:
    from apps._shared.nodus import record_nodus_fallback

    run.driver = None
    db.commit()
    record_nodus_fallback(db, workflow=WORKFLOW, user_id=run.user_id, reason=reason)
    db.commit()


def lateness_seconds(woke: Any) -> float | None:
    """How long after its own deadline the wait woke, from `await_event_for`'s marker."""
    if not isinstance(woke, dict) or not woke.get("timed_out") or not woke.get("deadline"):
        return None
    try:
        deadline = datetime.fromisoformat(str(woke["deadline"]).replace("Z", "+00:00"))
    except ValueError:
        return None
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - deadline).total_seconds(), 1)
