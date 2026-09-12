"""TRACE-ID-DUAL-1 / runtime FR-26: one request, one trace id.

Before aindy-runtime 2.12.0 every enveloped ``/apps/*`` response carried two different trace
ids — the ``X-Trace-ID`` header (minted by the ``log_requests`` middleware, and the id every
syscall, flow node and memory write actually landed under) and the body's top-level
``trace_id`` (minted a second time by ``ExecutionContext.from_request``, holding only the
route's own ``execution.started/completed``). Anyone debugging from the body id saw a route
that ran and produced nothing.

2.12.0 makes the pipeline adopt the middleware's id. This is the probe that closed the item,
kept so the next runtime adoption re-measures it instead of trusting the handoff.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.app_profile


def _register_and_login(client) -> str:
    email = f"trace-{uuid.uuid4().hex[:8]}@aindy.test"
    password = "IntegrationTest1!"
    r = client.post("/auth/register", json={"email": email, "password": password})
    assert r.status_code in (200, 201, 202), f"register failed: {r.status_code} {r.text[:300]}"
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:300]}"
    body = r.json()
    token = body.get("access_token") or (body.get("data") or {}).get("access_token")
    assert token, f"no access_token: {body}"
    return token


def test_enveloped_app_response_carries_one_trace_id(client):
    token = _register_and_login(client)

    r = client.post(
        "/apps/tasks/create",
        json={"title": "trace id probe", "description": "FR-26"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"

    header_id = r.headers.get("X-Trace-ID")
    body = r.json()
    body_id = body.get("trace_id")

    assert header_id, "no X-Trace-ID header — the log_requests middleware is not running"
    assert body_id, f"no top-level trace_id in the envelope: {list(body)}"
    assert body_id == header_id, (
        f"two trace ids on one request: header {header_id}, body {body_id} — "
        "TRACE-ID-DUAL-1 is back (runtime FR-26 regressed)"
    )

    # The flow's own id is the one everything inside the handler used; it must be the same
    # graph, not a third one.
    data_id = (body.get("data") or {}).get("trace_id")
    if data_id is not None:
        assert data_id == header_id, f"data.trace_id {data_id} != header {header_id}"
