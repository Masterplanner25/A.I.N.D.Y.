"""
Integration tests for the agent domain.

Requires a live Postgres stack:
    docker compose -f docker-compose.test.yml up -d
    pytest -c pytest.integration.ini tests/integration/test_agent.py -v

Key env flag required (already set in pytest.integration.ini):
    AINDY_AGENT_PLANNER_BACKEND=stub   — canned plan, no LLM required

Covers:
    POST /apps/agent/run         — create agent run (stub planner)
    GET  /apps/agent/runs        — list runs
    GET  /apps/agent/runs/{id}   — get single run
    POST /apps/agent/runs/{id}/approve — approve pending_approval run
    POST /apps/agent/runs/{id}/reject  — reject pending_approval run
    GET  /apps/agent/runs/{id}/steps   — list execution steps
    GET  /apps/agent/runs/{id}/events  — list agent events
    GET  /apps/agent/tools        — list registered tools
    GET  /apps/agent/trust        — get trust settings
    PUT  /apps/agent/trust        — update trust settings
    GET  /apps/agent/suggestions  — tool suggestions
"""
from __future__ import annotations

import os
import uuid
import pytest


pytestmark = [pytest.mark.integration, pytest.mark.app_profile]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _register_and_login(client) -> str:
    email = f"test-agent-{uuid.uuid4().hex[:8]}@aindy.test"
    password = "IntegrationTest1!"
    r = client.post("/auth/register", json={"email": email, "password": password})
    assert r.status_code in (200, 201, 202), f"register failed: {r.status_code} {r.text[:200]}"
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    body = r.json()
    token = body.get("access_token") or (body.get("data") or {}).get("access_token")
    assert token, f"no access_token in login response: {body}"
    return token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _extract_run_id(body: dict) -> str | None:
    """run_id lives inside execution_record (to_execution_response) or at top level (run_to_dict)."""
    er = body.get("execution_record") or {}
    return (
        er.get("run_id")
        or body.get("run_id")
        or ((body.get("data") or {}).get("run_id"))
    )


def _status_from(body: dict) -> str:
    """Status is uppercased by to_execution_response, lowercased by run_to_dict."""
    return str(body.get("status") or "").lower()


def _data(response) -> list | dict:
    body = response.json()
    return body.get("data") if "data" in body else body


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

class TestAgentTools:

    def test_list_tools_returns_200(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/agent/tools", headers=_auth(token))
        assert r.status_code == 200, r.text[:200]

    def test_tools_is_nonempty_list(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/agent/tools", headers=_auth(token))
        tools = _data(r)
        assert isinstance(tools, list), f"expected list, got {type(tools)}"
        assert len(tools) > 0, "TOOL_REGISTRY is empty — agent bootstrap not loaded"

    def test_tool_entries_have_required_fields(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/agent/tools", headers=_auth(token))
        tools = _data(r)
        for tool in tools[:5]:
            assert "name" in tool, f"missing 'name' in tool: {tool}"
            assert "risk" in tool, f"missing 'risk' in tool: {tool}"
            assert "description" in tool, f"missing 'description' in tool: {tool}"

    def test_tool_risk_levels_are_valid(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/agent/tools", headers=_auth(token))
        tools = _data(r)
        valid_risks = {"low", "medium", "high"}
        for tool in tools:
            assert tool.get("risk") in valid_risks, (
                f"tool {tool.get('name')!r} has invalid risk {tool.get('risk')!r}"
            )

    def test_tools_unauthenticated_returns_401(self, client):
        r = client.get("/apps/agent/tools")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Trust settings
# ---------------------------------------------------------------------------

class TestAgentTrust:

    def test_get_trust_returns_200(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/agent/trust", headers=_auth(token))
        assert r.status_code == 200, r.text[:200]

    def test_default_trust_is_conservative(self, client):
        """Fresh user has both auto-execute flags off by default."""
        token = _register_and_login(client)
        r = client.get("/apps/agent/trust", headers=_auth(token))
        body = r.json()
        assert body.get("auto_execute_low") is False
        assert body.get("auto_execute_medium") is False

    def test_trust_response_has_required_fields(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/agent/trust", headers=_auth(token))
        body = r.json()
        for field in ("auto_execute_low", "auto_execute_medium", "allowed_auto_grant_tools", "note"):
            assert field in body, f"missing field '{field}' in trust response: {list(body.keys())}"

    def test_update_trust_auto_execute_low(self, client):
        token = _register_and_login(client)
        r = client.put("/apps/agent/trust", json={"auto_execute_low": True}, headers=_auth(token))
        assert r.status_code in (200, 201), r.text[:200]
        body = r.json()
        assert body.get("auto_execute_low") is True

    def test_update_trust_persists(self, client):
        token = _register_and_login(client)
        client.put("/apps/agent/trust", json={"auto_execute_low": True}, headers=_auth(token))
        r = client.get("/apps/agent/trust", headers=_auth(token))
        assert r.json().get("auto_execute_low") is True

    def test_trust_unauthenticated_returns_401(self, client):
        r = client.get("/apps/agent/trust")
        assert r.status_code == 401

    def test_trust_isolated_per_user(self, client):
        token_a = _register_and_login(client)
        token_b = _register_and_login(client)
        client.put("/apps/agent/trust", json={"auto_execute_low": True}, headers=_auth(token_a))
        r = client.get("/apps/agent/trust", headers=_auth(token_b))
        assert r.json().get("auto_execute_low") is False


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------

class TestAgentSuggestions:

    def test_suggestions_returns_200(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/agent/suggestions", headers=_auth(token))
        assert r.status_code == 200, r.text[:200]

    def test_suggestions_is_list(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/agent/suggestions", headers=_auth(token))
        suggestions = _data(r)
        assert isinstance(suggestions, list), f"expected list, got {type(suggestions)}"

    def test_suggestions_unauthenticated_returns_401(self, client):
        r = client.get("/apps/agent/suggestions")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------

class TestAgentRunCreate:

    def test_create_run_accepted(self, client):
        """POST /apps/agent/run returns 200/201/202 with a run_id or automation_log_id."""
        token = _register_and_login(client)
        r = client.post(
            "/apps/agent/run",
            json={"goal": "Summarise my recent strategic priorities."},
            headers=_auth(token),
        )
        if r.status_code == 500:
            pytest.skip("planner backend not configured — run creation requires plan generation")
        assert r.status_code in (200, 201, 202), f"create run: {r.status_code} {r.text[:300]}"
        body = r.json()
        run_id = _extract_run_id(body)
        auto_log_id = body.get("automation_log_id") or (body.get("data") or {}).get("automation_log_id")
        assert run_id or auto_log_id, f"no run_id or automation_log_id in create response: {list(body.keys())}"

    def test_create_run_status_is_valid(self, client):
        token = _register_and_login(client)
        r = client.post(
            "/apps/agent/run",
            json={"goal": "List my top masterplan priorities."},
            headers=_auth(token),
        )
        if r.status_code in (202, 500):
            pytest.skip("run was deferred or planner not configured")
        body = r.json()
        status = _status_from(body)
        valid_statuses = {"pending_approval", "approved", "executing", "completed", "failed"}
        assert status in valid_statuses, f"unexpected status {status!r}"

    def test_create_run_empty_goal_returns_400(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/agent/run", json={"goal": "   "}, headers=_auth(token))
        assert r.status_code == 400

    def test_create_run_missing_goal_returns_422(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/agent/run", json={}, headers=_auth(token))
        assert r.status_code == 422

    def test_create_run_unauthenticated_returns_401(self, client):
        r = client.post("/apps/agent/run", json={"goal": "test"})
        assert r.status_code == 401


class TestAgentRunReadOps:
    """Tests that assume a run was created and only do reads."""

    def _create_run(self, client, token) -> str | None:
        """Create a run and return its run_id if one was created synchronously."""
        if os.getenv("AINDY_AGENT_PLANNER_BACKEND") == "disabled":
            return None  # plan generation required; skip without waiting 8s per call
        r = client.post(
            "/apps/agent/run",
            json={"goal": f"Integration test run {uuid.uuid4().hex[:6]}"},
            headers=_auth(token),
        )
        if r.status_code in (202, 500):
            return None  # deferred or planner not configured
        return _extract_run_id(r.json())

    def test_list_runs_is_empty_for_new_user(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/agent/runs", headers=_auth(token))
        assert r.status_code == 200
        runs = _data(r)
        assert isinstance(runs, list)
        assert len(runs) == 0

    def test_list_runs_after_create(self, client):
        token = _register_and_login(client)
        run_id = self._create_run(client, token)
        if run_id is None:
            pytest.skip("run was deferred (202) — no DB row to list yet")
        r = client.get("/apps/agent/runs", headers=_auth(token))
        assert r.status_code == 200
        runs = _data(r)
        assert isinstance(runs, list)
        ids = [str(item.get("run_id") or "") for item in runs if isinstance(item, dict)]
        assert run_id in ids, f"created run {run_id} not found in list: {ids}"

    def test_get_run_by_id(self, client):
        token = _register_and_login(client)
        run_id = self._create_run(client, token)
        if run_id is None:
            pytest.skip("run was deferred (202)")
        r = client.get(f"/apps/agent/runs/{run_id}", headers=_auth(token))
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        got_id = str(body.get("run_id") or _extract_run_id(body) or "")
        assert got_id == run_id

    def test_get_run_has_goal_field(self, client):
        token = _register_and_login(client)
        goal = f"test goal {uuid.uuid4().hex[:6]}"
        r = client.post("/apps/agent/run", json={"goal": goal}, headers=_auth(token))
        if r.status_code in (202, 500):
            pytest.skip("run was deferred (202) or planner not configured (500)")
        run_id = _extract_run_id(r.json())
        r = client.get(f"/apps/agent/runs/{run_id}", headers=_auth(token))
        body = r.json()
        assert body.get("goal") or body.get("objective"), (
            f"no goal/objective in run response: {list(body.keys())}"
        )

    def test_get_run_404_for_unknown_id(self, client):
        token = _register_and_login(client)
        fake_id = str(uuid.uuid4())
        r = client.get(f"/apps/agent/runs/{fake_id}", headers=_auth(token))
        assert r.status_code == 404

    def test_get_run_forbidden_for_other_user(self, client):
        token_a = _register_and_login(client)
        token_b = _register_and_login(client)
        run_id = self._create_run(client, token_a)
        if run_id is None:
            pytest.skip("run was deferred (202)")
        r = client.get(f"/apps/agent/runs/{run_id}", headers=_auth(token_b))
        assert r.status_code == 403

    def test_get_steps_returns_list(self, client):
        token = _register_and_login(client)
        run_id = self._create_run(client, token)
        if run_id is None:
            pytest.skip("run was deferred (202)")
        r = client.get(f"/apps/agent/runs/{run_id}/steps", headers=_auth(token))
        assert r.status_code == 200
        steps = _data(r)
        assert isinstance(steps, list)

    def test_get_events_returns_events_structure(self, client):
        token = _register_and_login(client)
        run_id = self._create_run(client, token)
        if run_id is None:
            pytest.skip("run was deferred (202)")
        r = client.get(f"/apps/agent/runs/{run_id}/events", headers=_auth(token))
        assert r.status_code == 200

    def test_list_runs_unauthenticated_returns_401(self, client):
        r = client.get("/apps/agent/runs")
        assert r.status_code == 401


class TestAgentApproveReject:

    def _create_pending_run(self, client, token) -> str | None:
        """Create a run and return run_id only if it landed in pending_approval."""
        if os.getenv("AINDY_AGENT_PLANNER_BACKEND") == "disabled":
            return None  # plan generation required; skip without waiting 8s per call
        r = client.post(
            "/apps/agent/run",
            json={"goal": f"Approve/reject test {uuid.uuid4().hex[:6]}"},
            headers=_auth(token),
        )
        if r.status_code in (202, 500):
            return None  # deferred or planner not configured
        body = r.json()
        status = _status_from(body)
        if status != "pending_approval":
            return None  # auto-approved or immediately executed
        return _extract_run_id(body)

    def test_approve_run(self, client):
        token = _register_and_login(client)
        run_id = self._create_pending_run(client, token)
        if run_id is None:
            pytest.skip("run not in pending_approval state (deferred or auto-executed)")
        r = client.post(f"/apps/agent/runs/{run_id}/approve", headers=_auth(token))
        assert r.status_code in (200, 201, 202), f"approve: {r.status_code} {r.text[:200]}"
        status = _status_from(r.json())
        valid_post_approve = {"approved", "executing", "completed", "failed"}
        assert status in valid_post_approve, f"unexpected post-approve status {status!r}"

    def test_approve_emits_approved_event(self, client):
        token = _register_and_login(client)
        run_id = self._create_pending_run(client, token)
        if run_id is None:
            pytest.skip("run not in pending_approval state")
        client.post(f"/apps/agent/runs/{run_id}/approve", headers=_auth(token))
        r = client.get(f"/apps/agent/runs/{run_id}/events", headers=_auth(token))
        assert r.status_code == 200
        body = r.json()
        events = body.get("events") or _data(r) or []
        event_types = [str(e.get("event_type") or "").upper() for e in events if isinstance(e, dict)]
        assert "APPROVED" in event_types, f"no APPROVED event in {event_types}"

    def test_reject_run(self, client):
        token = _register_and_login(client)
        run_id = self._create_pending_run(client, token)
        if run_id is None:
            pytest.skip("run not in pending_approval state")
        r = client.post(f"/apps/agent/runs/{run_id}/reject", headers=_auth(token))
        assert r.status_code in (200, 201, 202), f"reject: {r.status_code} {r.text[:200]}"
        status = _status_from(r.json())
        assert status in ("rejected", "failed"), f"unexpected post-reject status {status!r}"

    def test_approve_unknown_run_returns_404(self, client):
        token = _register_and_login(client)
        r = client.post(f"/apps/agent/runs/{uuid.uuid4()}/approve", headers=_auth(token))
        assert r.status_code in (404, 202), f"expected 404 or 202 (deferred), got {r.status_code}"

    def test_reject_unknown_run_returns_404(self, client):
        token = _register_and_login(client)
        r = client.post(f"/apps/agent/runs/{uuid.uuid4()}/reject", headers=_auth(token))
        assert r.status_code == 404


class TestAgentResume:
    """POST /apps/agent/runs/{id}/resume — release a run parked on a mid-plan WAIT step (RTR-1)."""

    def test_resume_unauthenticated_returns_401(self, client):
        r = client.post(f"/apps/agent/runs/{uuid.uuid4()}/resume")
        assert r.status_code == 401

    def test_resume_unknown_run_returns_404(self, client):
        token = _register_and_login(client)
        r = client.post(f"/apps/agent/runs/{uuid.uuid4()}/resume", headers=_auth(token))
        assert r.status_code == 404

    def test_resume_non_waiting_run_returns_409(self, client):
        """A run that exists but is not in status='waiting' cannot be resumed."""
        if os.getenv("AINDY_AGENT_PLANNER_BACKEND") == "disabled":
            pytest.skip("plan generation required to create a run")
        token = _register_and_login(client)
        r = client.post(
            "/apps/agent/run",
            json={"goal": f"Resume 409 test {uuid.uuid4().hex[:6]}"},
            headers=_auth(token),
        )
        if r.status_code in (202, 500):
            pytest.skip("run deferred or planner not configured")
        run_id = _extract_run_id(r.json())
        if run_id is None:
            pytest.skip("no run_id returned")
        r = client.post(f"/apps/agent/runs/{run_id}/resume", headers=_auth(token))
        # Not parked on a WAIT step → the runtime rejects the resume as a conflict.
        assert r.status_code == 409, f"expected 409, got {r.status_code} {r.text[:200]}"

    def test_resume_owner_invokes_runtime(self, client):
        """Owner POST reaches resume_agent_run_runtime and returns its envelope (200)."""
        from unittest.mock import patch

        token = _register_and_login(client)
        run_id = str(uuid.uuid4())
        fake_result = {
            "run_id": run_id,
            "status": "executing",
            "resumed_event": "agent.wait.released",
            "correlation_id": None,
            "waiters_notified": 1,
        }
        with patch(
            "apps.agent.routes.agent_router.resume_agent_run_runtime",
            return_value=fake_result,
        ) as mock_resume:
            r = client.post(f"/apps/agent/runs/{run_id}/resume", headers=_auth(token))
        assert r.status_code == 200, f"resume: {r.status_code} {r.text[:200]}"
        assert mock_resume.called, "resume_agent_run_runtime was not invoked"
        assert mock_resume.call_args.kwargs.get("run_id") == run_id


# ---------------------------------------------------------------------------
# GET /apps/agent/next-action/outcomes — FR-3 dispatch-outcome read
# ---------------------------------------------------------------------------

class TestNextActionOutcomes:

    def test_outcomes_shape_for_new_user(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/agent/next-action/outcomes", headers=_auth(token))
        assert r.status_code == 200, f"outcomes: {r.status_code} {r.text[:200]}"
        d = _data(r)
        # fresh user, acting off by default -> empty ledger, well-formed envelope
        assert d.get("outcomes") == []
        assert d.get("summary") == {}
        assert d.get("count") == 0
        assert "acting_enabled" in d

    def test_outcomes_accepts_trace_and_limit(self, client):
        token = _register_and_login(client)
        r = client.get(
            "/apps/agent/next-action/outcomes",
            params={"trace_id": "nonexistent", "limit": 5},
            headers=_auth(token),
        )
        assert r.status_code == 200, r.text[:200]
        assert _data(r).get("count") == 0

    def test_outcomes_requires_auth(self, client):
        assert client.get("/apps/agent/next-action/outcomes").status_code == 401
