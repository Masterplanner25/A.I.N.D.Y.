"""One correct way to run a flow from a route and act on its result.

## Why this exists

`run_flow()` returns the **flow** envelope, whose `status` is one of
`SUCCESS | FAILED | SKIPPED | WAITING | QUEUED | DEFERRED` — **all uppercase, and never
`"error"`**. Lowercase `"error"` belongs to the *syscall* envelope, which is a different
thing that happens to sit two lines away inside `_syscall_node`.

Eighteen route sites across four routers tested `result.get("status") == "error"`. That
never matches, so a `FAILED` flow fell through to the success path and the route returned
**200 with whatever `data` held**. The failure was real, recorded in `flow_runs`, and
invisible to the caller. Tracked as `APP-FLOW-STATUS-DEADBRANCH-1`; `CLAUDE.md` documented
the envelope as `{"status": "SUCCESS"|"error"}` until 2026-09-05, which is the likely
origin of all eighteen.

Four *other* routers — automation, autonomy, dashboard, health_dashboard — had already
hand-rolled this correctly, three of them byte-identically. Eight copies of one decision is
how four of them came to be wrong, so there is now one copy.

## What it does NOT handle, and why that is deliberate

`WAITING` / `QUEUED` / `DEFERRED` are **not** failures — they are async-handoff states, and
a route that raised on them would break the handoff. They are also not *success*: returning
`data` for a run that has not finished would be its own defect.

No flow has ever entered one of those states on this deployment (0 of 349 `flow_runs`; the
flows behind these routes contain no wait or suspend nodes), so there is nothing to write
against and no way to test it. Rather than ship an untestable branch, this treats them as
success-shaped and leaves the extension point marked: the runtime's own
`memory_router._mem_run_flow` handles the handoff by checking `data["_http_status"] == 202`
and returning a `JSONResponse(202, data["_http_response"])`. Copy that here when a flow in
this repo first waits — it is one edit in one place, which is the point of the module.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

#: The only flow status that means "finished, and it worked".
FLOW_STATUS_SUCCESS = "SUCCESS"

#: The only flow status that means "finished, and it did not work".
FLOW_STATUS_FAILED = "FAILED"


def flow_failure_message(result: dict[str, Any]) -> str:
    """Best available error string from a failed flow envelope.

    A flow node can report its error at the top level or nest it under `data` / `result`,
    so all three are checked. This is `automation`'s version, which was the only one of the
    four hand-rolled copies that looked past the top level — the other three read
    `result.get("error", "")` and would have raised a bare "<flow> failed" for any node that
    nested its message.
    """
    direct_error = result.get("error")
    if isinstance(direct_error, str) and direct_error:
        return direct_error
    for key in ("data", "result"):
        payload = result.get(key)
        if isinstance(payload, dict):
            nested = payload.get("error") or payload.get("message")
            if isinstance(nested, str) and nested:
                return nested
    return ""


def run_flow_or_raise(
    flow_name: str,
    payload: dict[str, Any],
    *,
    db: Session,
    user_id: str,
) -> dict[str, Any]:
    """Run a flow and raise `HTTPException` if it failed; otherwise return the envelope.

    Returns the **whole envelope**, not `data`, because callers differ: some read
    `result["data"]`, others hand the entire result to a `_flow_envelope(...)` builder.
    Use `run_flow_data` when only the payload is wanted.

    A flow node signals an intended HTTP status by prefixing its error `HTTP_<code>:<msg>`
    (see `apps/agent/flows/agent_flows.py`). That is mapped here, which is why a flow's
    deliberate 404 reaches the client as a 404 rather than an opaque 500 — the failure shape
    behind walk-log item 3.

    Raising `HTTPException` from inside a `execute_with_pipeline_sync` handler is the
    established pattern in this repo, not a new one: the four routers listed in the module
    docstring have done it from inside `def handler(ctx)` since before this module existed.
    """
    from AINDY.runtime.flow_engine import run_flow

    result = run_flow(flow_name, payload, db=db, user_id=user_id)

    if result.get("status") == FLOW_STATUS_FAILED:
        error = flow_failure_message(result)
        if error.startswith("HTTP_"):
            parts = error.split(":", 1)
            try:
                code = int(parts[0].replace("HTTP_", ""))
            except ValueError:
                # A malformed prefix must not become a 500 *about the prefix*; fall through
                # to the generic failure rather than raising ValueError out of the handler.
                raise HTTPException(status_code=500, detail=error) from None
            raise HTTPException(
                status_code=code,
                detail=parts[1] if len(parts) > 1 else error,
            )
        raise HTTPException(status_code=500, detail=error or f"{flow_name} failed")

    return result


def run_flow_data(
    flow_name: str,
    payload: dict[str, Any],
    *,
    db: Session,
    user_id: str,
) -> Any:
    """`run_flow_or_raise`, returning only the handler output under `data`."""
    return run_flow_or_raise(flow_name, payload, db=db, user_id=user_id).get("data")
