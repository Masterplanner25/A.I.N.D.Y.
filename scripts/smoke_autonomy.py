"""
Autonomy / Coordination / Automation domain smoke test.

Covers:
  autonomy  — GET /apps/autonomy/decisions (legacy_envelope_adapter)
  coordination — register → list → status → heartbeat → graph → shared memory
               → conflict detection → deregister
  automation — logs list, scheduler status (raw_json_adapter)

Since runtime 2.31.3 (DEC-114) the coordination registry routes answer 403 unless the caller is an
operator, so the coordination steps need an admin login. This script's own signup account is not one.

Response shapes:
  legacy_envelope_adapter (autonomy + coordination):
    {"status": "SUCCESS", "data": <payload>, "result": <payload>, "events": [], "trace_id": "..."}
  raw_json_adapter (automation):
    body IS the payload — no wrapping layer

Usage:
  python scripts/smoke_autonomy.py
  python scripts/smoke_autonomy.py --base-url http://localhost:8000
"""

import argparse
import sys
import uuid

try:
    import requests
except ImportError:
    print("FATAL: 'requests' not installed. Run: pip install requests")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(label: str, detail: str = "") -> None:
    print(f"  OK  {label}" + (f" -- {detail}" if detail else ""))


def _fail(label: str, detail: str = "") -> None:
    print(f"  FAIL {label}" + (f" -- {detail}" if detail else ""))


def _legacy(body: dict):
    """Extract payload from legacy_envelope_adapter response."""
    if not isinstance(body, dict):
        return {}
    d = body.get("data")
    if d is not None:
        return d
    return body.get("result") or {}


def _get(session, base, path, label, expect=200):
    r = session.get(f"{base}{path}")
    if r.status_code != expect:
        _fail(label, f"GET {path} -> {r.status_code}: {r.text[:300]}")
        return None, False
    return r.json(), True


def _post(session, base, path, body, label, expect=(200, 201, 202)):
    r = session.post(f"{base}{path}", json=body)
    if r.status_code not in expect:
        _fail(label, f"POST {path} -> {r.status_code}: {r.text[:300]}")
        return None, False
    return r.json(), True


def _delete(session, base, path, label, expect=(200, 204)):
    r = session.delete(f"{base}{path}")
    if r.status_code not in expect:
        _fail(label, f"DELETE {path} -> {r.status_code}: {r.text[:300]}")
        return None, False
    return r.json() if r.content else {}, True


# ---------------------------------------------------------------------------
# Test steps
# ---------------------------------------------------------------------------

def step_health(session, base, results):
    body, ok = _get(session, base, "/health", "health check")
    if ok:
        _ok("health check", f"status={body.get('status')}")
    results["health"] = "PASS" if ok else "FAIL"


def step_auth(session, base, results):
    email = f"smoke-autonomy-{uuid.uuid4().hex[:8]}@aindy.local"
    pw = "SmokeTest1!"

    _, ok = _post(session, base, "/auth/register", {"email": email, "password": pw}, "register")
    if not ok:
        results["auth"] = "FAIL"
        return None

    body, ok = _post(session, base, "/auth/login", {"email": email, "password": pw}, "login")
    if not ok:
        results["auth"] = "FAIL"
        return None

    token = body.get("access_token") or (body.get("data") or {}).get("access_token")
    if not token:
        _fail("login", f"no access_token in: {body}")
        results["auth"] = "FAIL"
        return None

    session.headers["Authorization"] = f"Bearer {token}"
    _ok("auth register + login", email)
    results["auth"] = "PASS"
    return token


def step_autonomy_decisions(session, base, results):
    """GET /apps/autonomy/decisions — legacy_envelope_adapter, list empty initially."""
    body, ok = _get(session, base, "/apps/autonomy/decisions", "autonomy decisions list")
    if not ok:
        results["autonomy_decisions"] = "FAIL"
        return

    payload = _legacy(body)
    # payload is either the list directly or a dict with a decisions key
    if isinstance(payload, list):
        decisions = payload
    elif isinstance(payload, dict):
        decisions = payload.get("decisions") or payload.get("data") or []
    else:
        decisions = []

    _ok("autonomy decisions list", f"{len(decisions)} decision(s) (empty list is OK for fresh user)")
    results["autonomy_decisions"] = "PASS"


def step_agent_register(session, base, agent_id, results):
    """POST /apps/coordination/agents/register."""
    body, ok = _post(
        session, base,
        "/apps/coordination/agents/register",
        {
            "agent_id": agent_id,
            "capabilities": ["smoke.test", "task.read"],
            "current_state": {"phase": "smoke"},
            "load": 0.1,
            "health_status": "healthy",
        },
        "register agent",
    )
    if not ok:
        results["agent_register"] = "FAIL"
        return False

    payload = _legacy(body)
    got_id = payload.get("agent_id") if isinstance(payload, dict) else None
    _ok("register agent", f"agent_id={got_id}  health={payload.get('health_status') if isinstance(payload, dict) else '?'}")
    results["agent_register"] = "PASS"
    return True


def step_agent_list(session, base, agent_id, results):
    """GET /apps/coordination/agents — verify registered agent present."""
    body, ok = _get(session, base, "/apps/coordination/agents", "list agents")
    if not ok:
        results["agent_list"] = "FAIL"
        return

    payload = _legacy(body)
    if isinstance(payload, list):
        agents = payload
    elif isinstance(payload, dict):
        agents = payload.get("agents") or []
    else:
        agents = []

    found = any(str(a.get("agent_id") or "") == agent_id for a in agents if isinstance(a, dict))
    if not found:
        _fail("list agents", f"agent_id {agent_id} not found in {len(agents)} agents")
        results["agent_list"] = "FAIL"
        return

    _ok("list agents", f"{len(agents)} agent(s), registered agent present")
    results["agent_list"] = "PASS"


def step_agent_status(session, base, results):
    """GET /apps/coordination/agents/status — summary counts."""
    body, ok = _get(session, base, "/apps/coordination/agents/status", "agent status summary")
    if not ok:
        results["agent_status"] = "FAIL"
        return

    payload = _legacy(body)
    total = payload.get("total_agents") if isinstance(payload, dict) else None
    _ok("agent status summary", f"total_agents={total}  healthy={payload.get('healthy_agents') if isinstance(payload, dict) else '?'}")
    results["agent_status"] = "PASS"


def step_heartbeat(session, base, agent_id, results):
    """POST /apps/coordination/agents/{id}/heartbeat."""
    body, ok = _post(
        session, base,
        f"/apps/coordination/agents/{agent_id}/heartbeat",
        {"load": 0.2, "health_status": "healthy"},
        "agent heartbeat",
    )
    if not ok:
        results["heartbeat"] = "FAIL"
        return

    payload = _legacy(body)
    _ok("agent heartbeat", f"agent_id={payload.get('agent_id') if isinstance(payload, dict) else '?'}")
    results["heartbeat"] = "PASS"


def step_coord_graph(session, base, results):
    """GET /apps/coordination/graph — coordination event graph."""
    body, ok = _get(session, base, "/apps/coordination/graph", "coordination graph")
    if not ok:
        results["coord_graph"] = "FAIL"
        return

    payload = _legacy(body)
    nodes = payload.get("nodes") if isinstance(payload, dict) else None
    edges = payload.get("edges") if isinstance(payload, dict) else None
    _ok("coordination graph", f"nodes={len(nodes) if isinstance(nodes, (list, dict)) else nodes}  edges={len(edges) if isinstance(edges, list) else edges}")
    results["coord_graph"] = "PASS"


def step_shared_memory(session, base, results):
    """GET /apps/coordination/memory/shared."""
    body, ok = _get(session, base, "/apps/coordination/memory/shared", "shared memory")
    if not ok:
        results["shared_memory"] = "FAIL"
        return

    payload = _legacy(body)
    count = payload.get("count") if isinstance(payload, dict) else None
    _ok("shared memory", f"count={count} (empty is OK for fresh user)")
    results["shared_memory"] = "PASS"


def step_conflict_run(session, base, results):
    """POST /apps/coordination/conflict/run — no active runs → conflict=False."""
    body, ok = _post(
        session, base,
        "/apps/coordination/conflict/run",
        {"objective": "smoke test conflict detection probe"},
        "conflict/run detection",
    )
    if not ok:
        results["conflict_run"] = "FAIL"
        return

    payload = _legacy(body)
    conflict = payload.get("conflict") if isinstance(payload, dict) else None
    _ok("conflict/run detection", f"conflict={conflict} (False expected for fresh user)")
    results["conflict_run"] = "PASS"


def step_conflict_memory(session, base, agent_id, results):
    """POST /apps/coordination/conflict/memory — no recent writes → conflict=False."""
    body, ok = _post(
        session, base,
        "/apps/coordination/conflict/memory",
        {"memory_path": f"/memory/smoke/{agent_id}", "agent_id": agent_id},
        "conflict/memory detection",
    )
    if not ok:
        results["conflict_memory"] = "FAIL"
        return

    payload = _legacy(body)
    conflict = payload.get("conflict") if isinstance(payload, dict) else None
    _ok("conflict/memory detection", f"conflict={conflict} (False expected for fresh user)")
    results["conflict_memory"] = "PASS"


def step_agent_deregister(session, base, agent_id, results):
    """DELETE /apps/coordination/agents/{id}."""
    body, ok = _delete(session, base, f"/apps/coordination/agents/{agent_id}", "deregister agent")
    if not ok:
        results["agent_deregister"] = "FAIL"
        return

    payload = _legacy(body) if body else {}
    status = payload.get("status") if isinstance(payload, dict) else None
    _ok("deregister agent", f"status={status}")
    results["agent_deregister"] = "PASS"


def step_automation_logs(session, base, results):
    """GET /apps/automation/logs — raw_json_adapter, body IS the payload."""
    body, ok = _get(session, base, "/apps/automation/logs", "automation logs list")
    if not ok:
        results["automation_logs"] = "FAIL"
        return

    # raw_json_adapter: body is the raw data dict
    if isinstance(body, dict):
        logs = body.get("logs") or body.get("results") or body.get("data") or []
        count = body.get("count") if "count" in body else (len(logs) if isinstance(logs, list) else "?")
        _ok("automation logs list", f"count={count} (empty is OK)")
    else:
        _ok("automation logs list", f"200 returned, type={type(body).__name__}")
    results["automation_logs"] = "PASS"


def step_scheduler_status(session, base, results):
    """GET /apps/automation/scheduler/status — raw_json_adapter."""
    body, ok = _get(session, base, "/apps/automation/scheduler/status", "scheduler status")
    if not ok:
        results["scheduler_status"] = "FAIL"
        return

    # raw_json_adapter: body is {"running": bool, "jobs": [...], "job_count": N}
    running = body.get("running") if isinstance(body, dict) else None
    job_count = body.get("job_count") if isinstance(body, dict) else None
    _ok("scheduler status", f"running={running}  job_count={job_count}")
    results["scheduler_status"] = "PASS"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Autonomy/coordination/automation domain smoke test")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Server base URL")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    agent_id = str(uuid.uuid4())

    print("=" * 60)
    print("AUTONOMY / COORDINATION / AUTOMATION SMOKE TEST")
    print(f"Target: {base}")
    print(f"Test agent_id: {agent_id}")
    print("=" * 60)

    session = requests.Session()
    session.headers["Content-Type"] = "application/json"
    results = {}

    print("\n[1] Health")
    step_health(session, base, results)

    print("\n[2] Auth")
    token = step_auth(session, base, results)
    if not token:
        print("\nAuth failed — cannot continue.")
        _print_summary(results)
        sys.exit(1)

    print("\n[3] Autonomy decisions (GET /apps/autonomy/decisions)")
    step_autonomy_decisions(session, base, results)

    print("\n[4] Register coordination agent")
    registered = step_agent_register(session, base, agent_id, results)
    if not registered:
        print("\nAgent register failed — skipping coordination lifecycle steps.")
        for k in ("agent_list", "agent_status", "heartbeat", "coord_graph", "shared_memory",
                   "conflict_run", "conflict_memory", "agent_deregister"):
            results[k] = "SKIP"
    else:
        print("\n[5] List coordination agents")
        step_agent_list(session, base, agent_id, results)

        print("\n[6] Agent status summary")
        step_agent_status(session, base, results)

        print("\n[7] Heartbeat")
        step_heartbeat(session, base, agent_id, results)

        print("\n[8] Coordination graph")
        step_coord_graph(session, base, results)

        print("\n[9] Shared memory")
        step_shared_memory(session, base, results)

        print("\n[10] Conflict detection — run objective")
        step_conflict_run(session, base, results)

        print("\n[11] Conflict detection — memory path")
        step_conflict_memory(session, base, agent_id, results)

        print("\n[12] Deregister agent")
        step_agent_deregister(session, base, agent_id, results)

    print("\n[13] Automation logs (GET /apps/automation/logs)")
    step_automation_logs(session, base, results)

    print("\n[14] Scheduler status (GET /apps/automation/scheduler/status)")
    step_scheduler_status(session, base, results)

    _print_summary(results)

    failed = [k for k, v in results.items() if v == "FAIL"]
    sys.exit(1 if failed else 0)


def _print_summary(results):
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    icons = {"PASS": "OK", "FAIL": "FAIL", "SKIP": "--"}
    for name, result in results.items():
        icon = icons.get(result, "??")
        print(f"  {icon}  {name}: {result}")
    print()
    failed = [k for k, v in results.items() if v == "FAIL"]
    if failed:
        print(f"FAILED: {', '.join(failed)}")
    else:
        print("ALL TESTS PASSED -- autonomy/coordination/automation domain smoke OK")


if __name__ == "__main__":
    main()
