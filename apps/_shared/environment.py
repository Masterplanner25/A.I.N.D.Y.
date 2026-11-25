"""Dev mode: a stack that must not act on the world (OFF_LAPTOP_DEPLOYMENT_SPEC §5, phase D).

A local stack restored from a copy of the real data would otherwise run the instance's scheduled jobs against it:
pay for the Resolution Check again, email owner notices, poll GitHub and act on release approvals, spend on
RippleTrace's model calls. `AINDY_ENVIRONMENT=dev` (set by `docker-compose.dev.yml`) turns those jobs off.

Every scheduled job is registered through `schedule_job(..., outward=True|False)`, never `register_scheduled_job`
directly, so each one declares its side (`test_dev_mode.py` fails on one that does not). Not the runtime's
`register_job`, which registers a synchronous job looked up by name: a different mechanism (OPS-026).

An outward job's function carries `@outward_job` on its definition: the module attribute itself is the guarded function, so it stays
importable by name (the runtime can run a job in a callback subprocess that imports it by module and name).

**Outward** means it spends money, sends mail, calls GitHub, or reaches the web for new data the instance acts on.
Everything else runs in dev mode too, so a local stack still behaves like the real one.
"""
from __future__ import annotations

import functools
import logging
import os
from typing import Any, Callable

logger = logging.getLogger(__name__)

ENV_VAR = "AINDY_ENVIRONMENT"
OUTWARD_MARK = "__aindy_outward_job__"

#: job_id -> outward, for every job registered through `schedule_job` in this process.
JOB_SIDES: dict[str, bool] = {}


def dev_mode() -> bool:
    return os.environ.get(ENV_VAR, "").strip().lower() == "dev"


def outward_job(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Skip this job in dev mode. Put it on the job function's definition, not around it at registration."""

    @functools.wraps(fn)
    def guarded(*args: Any, **kwargs: Any) -> Any:
        if dev_mode():
            logger.info("[dev mode] skipped outward job %s.%s", fn.__module__, fn.__name__)
            return {"skipped": True, "reason": "dev_mode"}
        return fn(*args, **kwargs)

    setattr(guarded, OUTWARD_MARK, True)
    return guarded


def is_outward(handler: Callable[..., Any]) -> bool:
    return bool(getattr(handler, OUTWARD_MARK, False))


def schedule_job(job_id: str, handler: Callable[..., Any], *, outward: bool, **kwargs: Any) -> Callable[..., Any]:
    """`register_scheduled_job`, with the job's side declared and checked against its function."""
    from AINDY.platform_layer.registry import register_scheduled_job

    if outward != is_outward(handler):
        raise ValueError(
            f"scheduled job '{job_id}' is declared outward={outward} but its function "
            f"{'lacks' if outward else 'carries'} @outward_job"
        )
    JOB_SIDES[job_id] = outward
    return register_scheduled_job(job_id, handler, **kwargs)
