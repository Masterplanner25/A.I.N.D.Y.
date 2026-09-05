"""Job-submission payloads must survive the effect gate's JSON round-trip.

`sys.v1.job.submit` is effect-gated. The dispatcher computes an action id by
JSON-serialising the payload in `execution_gate.compute_action_id` **before the handler
runs**, so a payload carrying a non-JSON-native value never reaches the handler at all —
it raises `TypeError: Object of type UUID is not JSON serializable` inside dispatch.

This was a live defect, not a hypothetical. `genesis_message_orchestrate` passed
`context["user_id"]` — a UUID object — straight through, and on 2026-09-05 a real Genesis
turn produced zero `analytics.infinity_recalc` rows in `job_logs` while
`memory.generate_embedding` queued twice in the same turn. The Infinity recalculation
simply never happened, and the node's fail-soft `except` reported the turn as successful.

Why every existing check missed it: the node's *previous* inline call passed the same raw
UUID to `sys.v1.analytics.execute_infinity`, which is **not** effect-gated, so it worked.
The difference is the gate path, not the payload shape — invisible to unit tests that
stub the dispatcher, and to any contract test that only inspects the payload dict.

These tests therefore assert the thing the gate actually does: `json.dumps` on the payload.
"""

from __future__ import annotations

import json
import os
import uuid

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-required-length-1234567890")

pytestmark = pytest.mark.app_profile


def _captured_job_submit_payload(context: dict) -> dict:
    """Run `genesis_message_orchestrate` with a stubbed dispatcher and return the payload
    it handed to `sys.v1.job.submit`."""
    from apps.automation.flows import flow_definitions

    captured: dict = {}

    def _fake_syscall_data(name, payload, ctx, capability):
        captured["name"] = name
        captured["payload"] = payload
        captured["capability"] = capability
        return {}

    original = flow_definitions._syscall_data
    flow_definitions._syscall_data = _fake_syscall_data
    try:
        result = flow_definitions.genesis_message_orchestrate({}, context)
    finally:
        flow_definitions._syscall_data = original

    assert result["status"] == "SUCCESS"
    return captured


def test_genesis_orchestrate_payload_survives_json_dumps():
    """The regression: a UUID user_id must not reach the gate un-stringified."""
    context = {"user_id": uuid.uuid4()}

    captured = _captured_job_submit_payload(context)

    assert captured["name"] == "sys.v1.job.submit"
    assert captured["capability"] == "job.submit"

    # This is the exact operation `execution_gate.compute_action_id` performs. Before the
    # fix it raised TypeError here, inside dispatch, and the job was never queued.
    json.dumps(captured["payload"])


def test_genesis_orchestrate_stringifies_user_id():
    """The value must be the string form, not `str(None)` or a repr of the UUID object."""
    user_id = uuid.uuid4()

    captured = _captured_job_submit_payload({"user_id": user_id})

    inner = captured["payload"]["payload"]
    assert inner["user_id"] == str(user_id)
    assert isinstance(inner["user_id"], str)
    assert inner["trigger_event"] == "genesis_message"
    assert captured["payload"]["task_name"] == "analytics.infinity_recalc"


def test_genesis_orchestrate_missing_user_id_stays_none():
    """A missing user_id must serialise as null rather than the string "None".

    `_job_infinity_recalc` raises on a falsy user_id, which is the intended failure. The
    string "None" would be truthy and would reach `execute()` as a bogus user id.
    """
    captured = _captured_job_submit_payload({})

    inner = captured["payload"]["payload"]
    assert inner["user_id"] is None
    json.dumps(captured["payload"])


def test_orchestrate_reports_success_when_queueing_fails():
    """Scoring is downstream of answering: a turn that produced a reply must not be
    reported as failed because the recalculation could not be queued.

    This half of the node worked correctly during the live incident — it is what kept a
    broken payload from failing user-visible turns — so it is pinned here."""
    from apps.automation.flows import flow_definitions

    def _boom(*args, **kwargs):
        raise TypeError("Object of type UUID is not JSON serializable")

    original = flow_definitions._syscall_data
    flow_definitions._syscall_data = _boom
    try:
        result = flow_definitions.genesis_message_orchestrate({}, {"user_id": uuid.uuid4()})
    finally:
        flow_definitions._syscall_data = original

    assert result["status"] == "SUCCESS"
    assert result["output_patch"] == {}
