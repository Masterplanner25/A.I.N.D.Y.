"""`apps/_shared/flow.py` — the one place a route decides what a flow result means.

These tests exist because eighteen route sites tested `result.get("status") == "error"`
against an envelope whose statuses are `SUCCESS | FAILED | SKIPPED | WAITING | QUEUED |
DEFERRED`. That comparison never matches, so a FAILED flow reached the success path and the
route returned 200. See `APP-FLOW-STATUS-DEADBRANCH-1`.

The load-bearing assertion is `test_failed_flow_raises`: it fails against the old
`== "error"` condition, which is what makes it a regression test rather than a restatement.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-required-length-1234567890")

from fastapi import HTTPException  # noqa: E402

pytestmark = pytest.mark.app_profile


def _patch_run_flow(monkeypatch, envelope):
    """Make `AINDY.runtime.flow_engine.run_flow` return `envelope`.

    Patched on the runtime module rather than on our helper, because the helper imports it
    lazily inside the function — patching our namespace would silently miss.
    """
    import AINDY.runtime.flow_engine as fe

    monkeypatch.setattr(fe, "run_flow", lambda *a, **k: envelope, raising=True)


def test_failed_flow_raises(monkeypatch):
    """★ The regression. A FAILED flow must not reach the caller as a result."""
    from apps._shared.flow import run_flow_or_raise

    _patch_run_flow(monkeypatch, {"status": "FAILED", "error": "node blew up", "data": {}})

    with pytest.raises(HTTPException) as exc:
        run_flow_or_raise("task_create", {}, db=None, user_id="u1")
    assert exc.value.status_code == 500
    assert "node blew up" in str(exc.value.detail)


def test_success_returns_whole_envelope(monkeypatch):
    """Callers differ — some read `data`, some pass the whole envelope on."""
    from apps._shared.flow import run_flow_or_raise

    envelope = {"status": "SUCCESS", "data": {"task_id": 7}, "trace_id": "t"}
    _patch_run_flow(monkeypatch, envelope)

    assert run_flow_or_raise("task_create", {}, db=None, user_id="u1") == envelope


def test_run_flow_data_unwraps(monkeypatch):
    from apps._shared.flow import run_flow_data

    _patch_run_flow(monkeypatch, {"status": "SUCCESS", "data": {"task_id": 7}})

    assert run_flow_data("task_create", {}, db=None, user_id="u1") == {"task_id": 7}


def test_http_prefixed_error_maps_to_its_status(monkeypatch):
    """A flow's deliberate 404 must reach the client as a 404, not an opaque 500.

    Flow nodes emit this shape — see `apps/agent/flows/agent_flows.py`.
    """
    from apps._shared.flow import run_flow_or_raise

    _patch_run_flow(monkeypatch, {"status": "FAILED", "error": "HTTP_404:Run not found"})

    with pytest.raises(HTTPException) as exc:
        run_flow_or_raise("agent_get", {}, db=None, user_id="u1")
    assert exc.value.status_code == 404
    assert exc.value.detail == "Run not found"


def test_malformed_http_prefix_does_not_raise_valueerror(monkeypatch):
    """`HTTP_abc:` must degrade to a 500, not throw ValueError out of the handler."""
    from apps._shared.flow import run_flow_or_raise

    _patch_run_flow(monkeypatch, {"status": "FAILED", "error": "HTTP_abc:nonsense"})

    with pytest.raises(HTTPException) as exc:
        run_flow_or_raise("x", {}, db=None, user_id="u1")
    assert exc.value.status_code == 500


def test_nested_error_message_is_found(monkeypatch):
    """Three of the four hand-rolled copies read only the top level and would have raised
    a bare "<flow> failed" here."""
    from apps._shared.flow import run_flow_or_raise

    _patch_run_flow(
        monkeypatch,
        {"status": "FAILED", "data": {"message": "duplicate task name"}},
    )

    with pytest.raises(HTTPException) as exc:
        run_flow_or_raise("task_create", {}, db=None, user_id="u1")
    assert "duplicate task name" in str(exc.value.detail)


def test_failure_with_no_message_still_names_the_flow(monkeypatch):
    from apps._shared.flow import run_flow_or_raise

    _patch_run_flow(monkeypatch, {"status": "FAILED"})

    with pytest.raises(HTTPException) as exc:
        run_flow_or_raise("goals_list", {}, db=None, user_id="u1")
    assert "goals_list" in str(exc.value.detail)


@pytest.mark.parametrize("status", ["WAITING", "QUEUED", "DEFERRED", "SKIPPED"])
def test_non_terminal_statuses_do_not_raise(status, monkeypatch):
    """Pins the deliberate gap documented in the module.

    These are not failures, so raising would break async handoff. They are not success
    either — this asserts today's behaviour so that the day someone adds the 202 handoff
    branch, this test fails and forces the decision to be made explicitly rather than
    drifting.
    """
    from apps._shared.flow import run_flow_or_raise

    envelope = {"status": status, "data": {}}
    _patch_run_flow(monkeypatch, envelope)

    assert run_flow_or_raise("f", {}, db=None, user_id="u1") == envelope
