"""Mark an adapter's response as the execution envelope — the `X-AINDY-Envelope` discriminator.

The runtime stamps `X-AINDY-Envelope: v1` only on `adapt_response`'s default exit
(`AINDY/core/response_adapter.py`). A route whose domain registers an adapter returns whatever
that adapter builds, unstamped — including the runtime's own `raw_canonical_adapter`, whose body
IS the canonical envelope, and `legacy_envelope_adapter`, whose body is `{status, data, events,
next_action, trace_id}`. Found adopting `@aindy/ui-kit` 2.1.0 (FR-37) on 2026-09-23: 45 of our
route names answer through `raw_canonical_adapter` and 9 through the legacy one, every one of them
an envelope, none of them marked.

Why that matters now: 2.1.0's `request()` resolves a stamped body itself, and once it has seen
ONE stamped response it treats every unstamped body as final — `unwrapEnvelope` stops unwrapping
it. So an unmarked envelope is unwrapped or not depending on whether the page that loaded first
happened to hit a stamped route. Marking the envelopes we serve makes the client's answer
depend on the response, not on history. Runtime half: `RUNTIME_FEATURE_REQUESTS.md` FR-45.

Only wrap an adapter whose success body carries the payload under `data` — the kit resolves a
stamped body to `body.data` (or `null`). A bare-JSON adapter (`raw_json_adapter`) must never be
wrapped: that is the lie the runtime's comment on the header warns about.
"""
from __future__ import annotations

import functools

ENVELOPE_HEADER = "X-AINDY-Envelope"
ENVELOPE_VERSION = "v1"


def stamped(adapter):
    """Wrap a response adapter so its success responses carry `X-AINDY-Envelope: v1`."""

    @functools.wraps(adapter)
    def _stamped(**kwargs):
        response = adapter(**kwargs)
        if getattr(response, "status_code", 500) < 400:
            response.headers[ENVELOPE_HEADER] = ENVELOPE_VERSION
        return response

    return _stamped
