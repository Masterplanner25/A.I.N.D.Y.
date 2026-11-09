"""The autonomy gate for a scheduled job, with the signals it is meant to see (audit 2026-11-01 D3, owner 2026-11-08).

Scheduled triggers execute by default (owner): the gate is meant to hold one back only when the system is critical,
overloaded, or repeating failures. Until 2026-11-08 it could not: the runtime runs the evaluator in a callback
subprocess and redacts the DB session on the way in, so it never saw any of those signals. `gate` computes them here,
in the job's own process, through the agent domain's `autonomy.signals` job (this module imports no domain), and
passes them in as data. If the signals cannot be computed, the gate still runs on what it has, as before.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def gate(db, *, trigger: dict[str, Any], context: dict[str, Any] | None = None, user_id: Any = None) -> dict[str, Any]:
    """The gate's decision for ``trigger``. Put the job's ``importance`` in ``trigger``: that is where it is read."""
    from AINDY.agents.autonomous_controller import evaluate_live_trigger
    from AINDY.platform_layer.registry import get_job

    ctx = dict(context or {})
    signals = get_job("autonomy.signals")
    if signals is not None:
        try:
            ctx = signals(db=db, trigger=trigger, user_id=user_id, context=ctx)
        except Exception as exc:  # the gate still decides, on less
            logger.warning("[autonomy] signals for %s could not be computed: %s", trigger.get("source"), exc)
    return evaluate_live_trigger(db=db, trigger=trigger, user_id=user_id, context=ctx)
