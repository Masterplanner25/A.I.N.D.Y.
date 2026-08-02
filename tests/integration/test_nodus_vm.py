"""
RTR-1 §5 — validate the opt-in `nodus_vm` agent-execution backend with REAL app tools.

See HANDOFF-aindy-runtime-1.5.0.md §5 and .github/workflows/nodus-vm-integration.yml.

Why this suite exists
---------------------
The runtime validated `nodus_vm` end-to-end on Postgres, but ONLY with its own
runtime-native tools (`memory.recall`/`memory.write`). The open question — and the
last gate before `nodus_vm` could ever become the default — is whether tools
registered by THIS repo's plugin manifest resolve AND execute inside the
`nodus_worker` subprocess spawned by `NodusRuntimeAdapter`. That subprocess loads
tools via `_ensure_tools_loaded → load_plugins()`, which resolves the app manifest
relative to the subprocess cwd (the PLANNER-SUBPROC-1 risk class).

Crucially, `memory.recall`/`memory.write` are ALSO registered as runtime defaults
inside the subprocess, so a run over a memory tool can pass even if the app manifest
failed to load — masking the failure. To actually close the gate we must drive a tool
that ONLY the app manifest provides (`task.create`), which the runtime has no default
for. Gate 1 uses the deterministic `stub_app_tool` planner to emit exactly that step —
no LLM, key, or network. (It was previously LLM-driven via `anthropic_chat` to have
Claude *select* task.create, but that reduced Gate 1 to a `skip` in CI: the create-500
was an `anthropic.APIConnectionError` — the runner cannot reach api.anthropic.com — not
a code bug, and plan generation is in-process regardless of the execution backend, so an
LLM was never needed to prove subprocess app-tool execution. See TECH_DEBT
RTR-1-NODUS-APPTOOL-500.) The suite therefore needs no secret.

Run:
    docker compose -f docker-compose.test.yml up -d
    pytest -c pytest.nodus.ini tests/integration/test_nodus_vm.py -v

History: execute-to-completion of a resumed nodus_vm segment was blocked by two stacked
runtime bugs, both PG-only (SQLite masked them) and both surfaced by driving the scheduler
in-process here:
  1. aindy-runtime#152 — ExecutionPipeline emitted its own execution.started BEFORE marking
     itself active, so the nested flow-runner pipeline tripped the ExecutionContract guard
     ('execution.started emitted outside pipeline'); the swallowed error poisoned the PG txn.
     Fixed in 1.5.2 (PR #155): set pipeline_active before the first emit.
  2. aindy-runtime#157 — with #152 cleared, the syscall dispatcher's idempotency gate cast
     the run-scoped execution_unit_id ('run_<uuid>') to the ExecutionUnit.id UUID column
     (InvalidTextRepresentation); the caught error, lacking a savepoint, poisoned the txn
     (InFailedSqlTransaction), so the flow_runs INSERT failed and the run never completed.
     Fixed in 1.5.3 (PR #158): only look up bare-UUID ids + SAVEPOINT/rollback the lookup.
With both fixed (pin floor >=1.5.3), the resumed segment runs to a terminal state, so Gate 2
hard-asserts completion. See TECH_DEBT RTR-1-NODUS-COMPLETION (RESOLVED).
"""
from __future__ import annotations

import os
import time
import uuid

import pytest


pytestmark = [pytest.mark.integration, pytest.mark.app_profile, pytest.mark.postgres]


# --- app-manifest-only tools (no runtime default) vs runtime-default tools ------
# A run that executes an APP_MANIFEST_TOOL inside the subprocess proves the app
# manifest loaded there. RUNTIME_DEFAULT_TOOLS can resolve via the runtime fallback
# even if the manifest did not, so they do NOT close the §5 gate on their own.
APP_MANIFEST_TOOLS = {"task.create", "task.complete"}
RUNTIME_DEFAULT_TOOLS = {"memory.recall", "memory.write"}

TERMINAL_STATUSES = {"completed", "failed", "rejected"}
_RESOLUTION_FAILURE_MARKERS = (
    "not found",
    "unknown tool",
    "no such tool",
    "not registered",
    "unavailable tool",
    "could not resolve tool",
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _token_from_login(client, email: str, password: str) -> str:
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login: {r.status_code} {r.text[:200]}"
    body = r.json()
    token = body.get("access_token") or (body.get("data") or {}).get("access_token")
    assert token, f"no access_token in login response: {body}"
    return token


def _register_and_login(client) -> str:
    """Register + login via the API — the user lives in the harness's transactional
    (rolled-back) session. Fine for runs that never write a user-FK'd row from the
    nodus subprocess (Gate 2 over memory.recall). Gate 1 needs `_login_committed_user`."""
    email = f"test-nodus-{uuid.uuid4().hex[:8]}@aindy.test"
    password = "IntegrationTest1!"
    r = client.post("/auth/register", json={"email": email, "password": password})
    assert r.status_code in (200, 201, 202), f"register: {r.status_code} {r.text[:200]}"
    return _token_from_login(client, email, password)


def _login_committed_user(client, testing_session_factory) -> str:
    """Create a COMMITTED user (engine-bound session, separate connection) and log in.

    Gate 1 drives a real app-manifest DB write (`task.create`) inside the `nodus_worker`
    subprocess, which uses its own committed-only DB connection. The default
    transactional-rollback harness user (`tests/fixtures/client.py`) is invisible to that
    connection, so the user must be committed for the `tasks_user_id_fkey` write to
    succeed. `testing_session_factory` is bound to the engine (commits independently of the
    app's rolled-back outer transaction); `cleanup_committed_test_state` TRUNCATEs it
    between tests. `/auth/login` needs only the `users` row (verify password → JWT). See
    TECH_DEBT RTR-1-NODUS-APPTOOL-500-DBVIS.
    """
    from AINDY.db.models.user import User
    from AINDY.services.auth_service import hash_password

    email = f"test-nodus-committed-{uuid.uuid4().hex[:8]}@aindy.test"
    password = "IntegrationTest1!"
    session = testing_session_factory()
    try:
        session.add(User(email=email, hashed_password=hash_password(password), is_active=True))
        session.commit()
    finally:
        session.close()
    return _token_from_login(client, email, password)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _extract_run_id(body: dict) -> str | None:
    er = body.get("execution_record") or {}
    return er.get("run_id") or body.get("run_id") or ((body.get("data") or {}).get("run_id"))


def _status_from(body: dict) -> str:
    return str(body.get("status") or "").lower()


def _steps(client, token, run_id) -> list[dict]:
    r = client.get(f"/apps/agent/runs/{run_id}/steps", headers=_auth(token))
    assert r.status_code == 200, f"steps: {r.status_code} {r.text[:200]}"
    body = r.json()
    return body.get("data") if isinstance(body, dict) and "data" in body else body


def _poll_run(client, token, run_id, *, until, timeout=90.0, interval=2.0) -> dict:
    """Poll GET /runs/{id} until ``until(status)`` is truthy or timeout. Returns last body."""
    deadline = time.monotonic() + timeout
    body: dict = {}
    while time.monotonic() < deadline:
        r = client.get(f"/apps/agent/runs/{run_id}", headers=_auth(token))
        assert r.status_code == 200, f"get run: {r.status_code} {r.text[:200]}"
        body = r.json()
        if until(_status_from(body)):
            return body
        time.sleep(interval)
    return body


def _assert_no_tool_resolution_failure(steps: list[dict], run_body: dict) -> None:
    """The failure mode §5 hunts: a tool that never resolved in the subprocess."""
    haystacks = [str(run_body.get("error") or "")]
    for s in steps:
        haystacks.append(str(s.get("error_message") or ""))
    for text in haystacks:
        low = text.lower()
        for marker in _RESOLUTION_FAILURE_MARKERS:
            assert marker not in low, (
                f"tool-resolution failure detected ({marker!r}) — app manifest likely "
                f"did not load in the nodus_worker subprocess: {text[:300]}"
            )


# --------------------------------------------------------------------------- #
# Module guard — this suite is only meaningful on live Postgres + nodus_vm
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _require_nodus_vm():
    if os.getenv("AINDY_AGENT_EXECUTION_BACKEND", "agent_flow").strip().lower() != "nodus_vm":
        pytest.skip("nodus_vm validation requires AINDY_AGENT_EXECUTION_BACKEND=nodus_vm "
                    "(use -c pytest.nodus.ini)")


# --------------------------------------------------------------------------- #
# Gate 1 — a REAL app-manifest tool resolves AND executes inside nodus_vm
# --------------------------------------------------------------------------- #
class TestNodusVmAppTool:
    """Deterministic (no LLM/key/network): the app `stub_app_tool` planner emits a single
    high-risk `task.create` step — an app-manifest-only tool the runtime has NO default
    for (unlike `memory.recall`). AINDY_AGENT_WAIT_BEFORE_HIGH_RISK parks the run; the §4
    resume route + an in-process scheduler tick drive it to completion. A clean completion
    proves the app plugin manifest resolved AND executed inside the `nodus_worker`
    subprocess — the §5 gate. See TECH_DEBT RTR-1-NODUS-APPTOOL-500.

    History: this gate was previously LLM-driven (the `anthropic_chat` planner selecting
    task.create), which reduced it to a `skip` in CI — the create-500 was an
    `anthropic.APIConnectionError` (the runner cannot reach api.anthropic.com), not a code
    bug. Plan generation is in-process regardless of the execution backend, so an LLM was
    never needed to prove subprocess app-tool execution; the deterministic stub removes the
    egress/key dependency entirely.
    """

    @pytest.fixture
    def _stub_app_tool_planner(self, monkeypatch):
        # Select the app-manifest-tool stub via settings (the create path resolves the
        # backend from settings.AINDY_AGENT_PLANNER_BACKEND); Gate 2 monkeypatches the
        # same way for the runtime-default `stub`.
        from AINDY.config import settings

        monkeypatch.setattr(settings, "AINDY_AGENT_PLANNER_BACKEND", "stub_app_tool", raising=False)
        return "stub_app_tool"

    def test_app_tool_resolves_and_executes_in_subprocess(
        self, client, testing_session_factory, _stub_app_tool_planner
    ):
        # Committed user — the nodus subprocess's committed-only connection must see it
        # for task.create's tasks_user_id_fkey write to succeed (see _login_committed_user).
        token = _login_committed_user(client, testing_session_factory)
        goal = f"nodus-vm app-tool {uuid.uuid4().hex[:6]}"  # becomes the task name
        r = client.post("/apps/agent/run", json={"goal": goal}, headers=_auth(token))
        if r.status_code in (202, 500):
            pytest.skip(f"stub_app_tool planner unavailable or run deferred "
                        f"(status={r.status_code}): {r.text[:300]}")
        assert r.status_code in (200, 201), f"create: {r.status_code} {r.text[:200]}"

        body = r.json()
        run_id = _extract_run_id(body)
        assert run_id, f"no run_id in create response: {body}"

        if _status_from(body) == "pending_approval":
            ra = client.post(f"/apps/agent/runs/{run_id}/approve", headers=_auth(token))
            assert ra.status_code in (200, 201, 202), f"approve: {ra.status_code} {ra.text[:200]}"

        # The high-risk task.create step parks behind an approval WAIT.
        parked = _poll_run(client, token, run_id, until=lambda s: s == "waiting", timeout=60.0)
        if _status_from(parked) != "waiting":
            pytest.skip(f"run never parked at 'waiting' (status={_status_from(parked)!r}); "
                        "wait-before-high-risk policy did not insert a WAIT — investigate")

        # Release via the §4 resume route, then drive the scheduler in-process to RUN the
        # resumed segment — the app tool executes inside the nodus_worker subprocess here.
        rr = client.post(f"/apps/agent/runs/{run_id}/resume", headers=_auth(token))
        assert rr.status_code == 200, f"resume: {rr.status_code} {rr.text[:200]}"
        assert rr.json().get("resumed_event") == "agent.approval.granted", (
            f"unexpected resume envelope: {rr.json()}"
        )

        from AINDY.kernel.scheduler import get_scheduler_engine

        get_scheduler_engine().schedule()  # dispatch + run the resumed segment, inline

        run_body = _poll_run(
            client, token, run_id, until=lambda s: s in TERMINAL_STATUSES, timeout=30.0
        )
        status = _status_from(run_body)
        steps = _steps(client, token, run_id)

        # THE §5 GATE: the app tool must never fail to resolve inside the subprocess. A
        # manifest-load failure would surface here as a "tool not found" error, red.
        _assert_no_tool_resolution_failure(steps, run_body)

        assert status in TERMINAL_STATUSES, (
            f"nodus_vm app-tool run did not complete (status={status!r}); with "
            "aindy-runtime>=1.5.3 the resumed segment should reach a terminal state. See "
            "TECH_DEBT RTR-1-NODUS-COMPLETION / RTR-1-NODUS-APPTOOL-500."
        )

        # Full gate: the app-manifest tool (task.create) executed cleanly in the subprocess.
        assert steps, f"nodus_vm run produced no steps (status={status})"
        executed_tools = {
            s.get("tool_name") for s in steps
            if s.get("tool_name") and _status_from(s) not in {"pending", "skipped", ""}
        }
        app_tools_hit = executed_tools & APP_MANIFEST_TOOLS
        assert app_tools_hit, (
            f"expected an app-manifest tool {APP_MANIFEST_TOOLS} to execute in the subprocess; "
            f"got {executed_tools} (RUNTIME_DEFAULT_TOOLS={RUNTIME_DEFAULT_TOOLS} do not close "
            "the §5 gate — they resolve via the runtime fallback)"
        )
        for s in steps:
            if s.get("tool_name") not in app_tools_hit:
                continue
            # The user is committed (see _login_committed_user), so the app tool's DB write
            # completes end-to-end inside the subprocess — a full app-manifest execute proof.
            assert _status_from(s) in {"success", "completed", "executed", "ok"}, (
                f"app tool {s.get('tool_name')} did not execute cleanly in the subprocess: "
                f"status={s.get('status')} error={str(s.get('error_message'))[:200]}"
            )


# --------------------------------------------------------------------------- #
# Gate 2 — mid-plan WAIT parks the run; the resume route drives it to completion
# --------------------------------------------------------------------------- #
class TestNodusVmWaitResume:
    """Deterministic (no LLM): the app `stub` planner emits a canned high-risk step;
    AINDY_AGENT_WAIT_BEFORE_HIGH_RISK inserts an approval WAIT before it, so the run
    parks at status='waiting' under nodus_vm and the resume route releases it."""

    @pytest.fixture
    def _stub_planner(self, monkeypatch):
        from AINDY.config import settings

        monkeypatch.setattr(settings, "AINDY_AGENT_PLANNER_BACKEND", "stub", raising=False)
        return "stub"

    def test_wait_then_resume_completes(self, client, _stub_planner):
        token = _register_and_login(client)
        r = client.post(
            "/apps/agent/run",
            json={"goal": f"nodus-vm wait/resume {uuid.uuid4().hex[:6]}"},
            headers=_auth(token),
        )
        if r.status_code in (202, 500):
            pytest.skip(f"stub planner unavailable or run deferred (status={r.status_code}): {r.text[:300]}")
        assert r.status_code in (200, 201), f"create: {r.status_code} {r.text[:200]}"

        body = r.json()
        run_id = _extract_run_id(body)
        assert run_id, f"no run_id in create response: {body}"

        if _status_from(body) == "pending_approval":
            ra = client.post(f"/apps/agent/runs/{run_id}/approve", headers=_auth(token))
            assert ra.status_code in (200, 201, 202), f"approve: {ra.status_code} {ra.text[:200]}"

        # The wait policy should park the run before the high-risk stub step.
        parked = _poll_run(client, token, run_id, until=lambda s: s == "waiting", timeout=60.0)
        if _status_from(parked) != "waiting":
            pytest.skip(f"run never parked at 'waiting' (status={_status_from(parked)!r}); "
                        "wait-before-high-risk policy did not insert a WAIT — investigate")

        # The resume route (§4) releases the parked run.
        rr = client.post(f"/apps/agent/runs/{run_id}/resume", headers=_auth(token))
        assert rr.status_code == 200, f"resume: {rr.status_code} {rr.text[:200]}"
        resumed = rr.json()
        assert resumed.get("resumed_event") == "agent.approval.granted", (
            f"unexpected resume envelope: {resumed}"
        )

        assert resumed.get("waiters_notified", 0) >= 1, (
            f"resume notified no waiters — event not delivered: {resumed}"
        )

        # Resume enqueues the continuation onto the scheduler queue. The TestClient
        # harness runs no heartbeat, so drive the scheduler directly — the in-process
        # equivalent of the 1s scheduler_heartbeat_tick — to dispatch and RUN the
        # resumed segment inline.
        #
        # On aindy-runtime >=1.5.3 both blockers are fixed: #152 / PR #155 (v1.5.2 —
        # ExecutionPipeline marks itself active before emitting execution.started) and
        # #157 / PR #158 (v1.5.3 — the idempotency gate no longer casts the run-scoped
        # execution_unit_id 'run_<uuid>' to the ExecutionUnit.id UUID column, and wraps the
        # lookup in a savepoint). So the resumed nodus_vm segment now runs to a terminal
        # state. A regression of either fix would poison the run's PG transaction and leave
        # it non-terminal (or 401 the poll on the poisoned session), failing the assert red.
        from AINDY.kernel.scheduler import get_scheduler_engine

        get_scheduler_engine().schedule()  # dispatch + run the resumed segment, inline

        final = _status_from(
            _poll_run(client, token, run_id, until=lambda s: s in TERMINAL_STATUSES, timeout=30.0)
        )
        assert final in TERMINAL_STATUSES, (
            "resumed nodus_vm segment did not run to completion "
            f"(observed status={final!r}); expected the aindy-runtime>=1.5.3 fixes "
            "(#152 pipeline-active + #157 idempotency-gate UUID/savepoint) to let the "
            "continuation reach a terminal state. If this fails, a run's PG transaction "
            "was likely poisoned again — reopen TECH_DEBT RTR-1-NODUS-COMPLETION."
        )
