"""Verify the agent planner is wired end-to-end with the runtime_local backend.

This is the proof that "wiring the planner" is a pure configuration concern in
this repo: the runtime ships the backend, the apps register the tools, and
selecting AINDY_AGENT_PLANNER_BACKEND=runtime_local makes the planner produce
real plans over the registered tool catalog and a run get created + approved —
with no LLM and no edits to the runtime package.

Runs on the app-profile sqlite harness (no Postgres/Redis/Mongo required).

Scope note: the *execute* half of the loop (Nodus run -> syscall dispatch ->
tool side effects) requires the full Postgres schema (the runtime `agents`
table and friends) and belongs in the integration suite, run with
AINDY_AGENT_PLANNER_BACKEND=runtime_local against docker-compose.test.yml.
A live exercise of that path surfaced a runtime contract bug, pinned by the
xfail below.
"""
from __future__ import annotations

import uuid

import pytest

pytestmark = [pytest.mark.app_profile]


def _register_and_login(client) -> str:
    email = f"planner-{uuid.uuid4().hex[:8]}@aindy.test"
    password = "IntegrationTest1!"
    r = client.post("/auth/register", json={"email": email, "password": password})
    assert r.status_code in (200, 201, 202), f"register failed: {r.status_code} {r.text[:300]}"
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:300]}"
    body = r.json()
    token = body.get("access_token") or (body.get("data") or {}).get("access_token")
    assert token, f"no access_token: {body}"
    return token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def runtime_local_planner(monkeypatch):
    """Select the deterministic no-LLM planner backend for the duration of a test."""
    from AINDY.config import settings

    monkeypatch.setattr(settings, "AINDY_AGENT_PLANNER_BACKEND", "runtime_local", raising=False)
    return "runtime_local"


def test_runtime_local_backend_is_registered(client, runtime_local_planner):
    from AINDY.platform_layer.registry import get_agent_planner_backend

    assert get_agent_planner_backend("runtime_local") is not None


def test_planner_generates_plan_over_registered_tools(client, runtime_local_planner):
    """generate_plan must produce a plan whose steps reference real registered tools."""
    from AINDY.agents.agent_runtime import generate_plan
    from AINDY.agents.tool_registry import TOOL_REGISTRY
    from AINDY.db.database import SessionLocal

    assert TOOL_REGISTRY, "no agent tools registered — app bootstrap not loaded"

    db = SessionLocal()
    try:
        plan = generate_plan(
            objective="Record a note that the planner wiring is verified.",
            user_id=None,
            db=db,
        )
    finally:
        db.close()

    assert isinstance(plan, dict), f"expected a plan dict, got {plan!r}"
    steps = plan.get("steps") or []
    assert steps, f"plan has no steps: {plan}"
    chosen = [s.get("tool") for s in steps]
    assert all(t in TOOL_REGISTRY for t in chosen), (
        f"plan referenced unregistered tool(s): {chosen} not all in {sorted(TOOL_REGISTRY)}"
    )
    assert plan.get("overall_risk") in {"low", "medium", "high"}


def test_run_created_with_persisted_plan(client, runtime_local_planner):
    """POST /apps/agent/run generates a plan and persists an agent run.

    Without auto-execute trust the run lands in pending_approval — proving the
    planner-driven create path without depending on the Postgres-only execute path.
    """
    token = _register_and_login(client)
    r = client.post(
        "/apps/agent/run",
        json={"goal": "Summarise my recent strategic priorities."},
        headers=_auth(token),
    )
    if r.status_code == 202:
        pytest.skip("run was deferred by autonomy gate (202)")
    assert r.status_code in (200, 201), f"create run: {r.status_code} {r.text[:400]}"

    body = r.json()
    status = str(body.get("status") or "").lower()
    assert status in {"pending_approval", "approved", "executing", "completed"}, (
        f"unexpected status {status!r}: {body}"
    )

    run_id = (
        (body.get("execution_record") or {}).get("run_id")
        or body.get("run_id")
        or (body.get("data") or {}).get("run_id")
    )
    assert run_id, f"no run_id in create response: {list(body.keys())}"

    run = client.get(f"/apps/agent/runs/{run_id}", headers=_auth(token)).json()
    plan = run.get("plan") or {}
    assert plan.get("steps"), f"persisted run has no plan steps: {run}"
    assert plan["steps"][0].get("tool") in {
        "memory.recall", "memory.write",
    }, f"runtime_local should plan a memory tool first, got {plan['steps']}"


def test_runtime_memory_write_node_type_contract_is_self_consistent():
    """The memory.write syscall's default node_type must be accepted by its own validator.

    Originally an xfail pinning a runtime contract bug: every memory.write path
    defaulted node_type to "execution", which VALID_NODE_TYPES rejects, so the
    before_insert validator blocked every default write (and thus the execute half
    of the planner loop). Fixed in aindy-runtime 1.4.2 (MEM-NODETYPE-1) by changing
    the defaults to "insight" rather than widening VALID_NODE_TYPES — so this asserts
    the runtime's *actual* default, read from source, rather than a hardcoded literal.
    """
    import inspect
    import re

    from AINDY.kernel import syscall_registry
    from AINDY.memory.memory_persistence import VALID_NODE_TYPES

    src = inspect.getsource(syscall_registry._handle_memory_write)
    match = re.search(
        r'payload\.get\(\s*["\']node_type["\']\s*,\s*["\']([^"\']+)["\']\s*\)', src
    )
    assert match, "could not locate the memory.write default node_type in _handle_memory_write"
    default_node_type = match.group(1)

    assert default_node_type in VALID_NODE_TYPES, (
        f"runtime memory.write defaults node_type={default_node_type!r} but its validator "
        f"allows only {sorted(VALID_NODE_TYPES)}"
    )
