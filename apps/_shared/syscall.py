"""A syscall that fails must say so somewhere a person will read.

## Why this exists

`SYSCALL-SILENT-ERRORS-1`. The runtime's dispatcher has thirteen error paths and eleven of
them emit neither a log line nor a durable event — the failure appears solely as a metric
increment (`aindy_syscall_outcome_total{status="error"}`), and the envelope's `error`
string, which carries the exact message, is returned to the caller and to nobody else.

Every app caller then does the *correct* defensive thing:

```python
result = get_dispatcher().dispatch(name, payload, ctx)
if result.get("status") != "success":
    return 0          # or {}, or []
```

…which is where the message dies. The combination — a silent dispatcher and a correct swallow
— is what turns a failing syscall into a confident zero on a surface someone reads: agent run
counts, recent durations, the Infinity loop's adjustment record. Investigated 2026-09-05; every
out-of-process reproduction succeeded, so the mechanism cannot be found from outside. It has to
be caught in the act, and the only place that can catch it is the caller holding the envelope.

## What it does

`swallowed(name, result, *, default, log)` is the swallow, made loud: the same early return the
callers already wrote, plus one WARNING carrying the syscall name, the envelope status, and the
envelope's `error` string. Nothing about control flow changes — a caller that returned `0`
still returns `0` — so a surface that showed a zero still shows a zero. The difference is that
the log now says why, which is the next step the debt entry asks for.

Filed upstream as FR-25 for the dispatcher's own logging; this is the half that is ours.
"""

from __future__ import annotations

import logging
from typing import Any, TypeVar

T = TypeVar("T")

SYSCALL_SUCCESS = "success"


def failed(result: Any) -> bool:
    """True when a syscall envelope did not resolve to `success`.

    Lowercase — this is the syscall envelope (`success | partial | unknown | error` since
    runtime 2.9.0), not the uppercase flow envelope. `partial` and `unknown` count as failed
    here on purpose: a caller that reads `data` off a partial result is reading an
    incomplete answer as a complete one.
    """
    return not isinstance(result, dict) or result.get("status") != SYSCALL_SUCCESS


def swallowed(
    name: str, result: Any, *, default: T, log: logging.Logger, caller: str | None = None
) -> T:
    """Return `default` for a failed syscall, and say why at WARNING.

    Call it only after `failed(result)` is true; it does not re-check. The `error` string
    is the dispatcher's own message — permission denied, input validation, quota backend
    unavailable, handler contract — and until this it was thrown away at every one of these
    sites.
    """
    status = result.get("status") if isinstance(result, dict) else type(result).__name__
    error = result.get("error") if isinstance(result, dict) else None
    where = f" in {caller}" if caller else ""
    log.warning(
        "[syscall] %s returned %r%s — swallowed as %r; error=%s",
        name, status, where, default, error if error else "(no error string in envelope)",
    )
    return default
