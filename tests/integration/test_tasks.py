"""
Integration tests for the tasks domain.

Requires a live Postgres stack:
    docker compose -f docker-compose.test.yml up -d
    pytest -c pytest.integration.ini tests/integration/test_tasks.py -v

Exercises the full task lifecycle via the HTTP layer:
    create -> list -> start -> pause -> complete -> list (status checks)
    + recurrence check endpoint
    + syscall surface (sys.v1.task.create, sys.v1.task.complete)
"""
from __future__ import annotations

import uuid
import pytest


pytestmark = [pytest.mark.integration, pytest.mark.app_profile]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _register_and_login(client) -> str:
    """Register a fresh user and return a Bearer token."""
    email = f"test-tasks-{uuid.uuid4().hex[:8]}@aindy.test"
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


def _data(response) -> dict:
    body = response.json()
    return body.get("data") or {}


def _tasks_from(response) -> list:
    d = _data(response)
    if isinstance(d, dict):
        tasks = d.get("tasks")
        if isinstance(tasks, list):
            return tasks
    if isinstance(d, list):
        return d
    return []


def _find_task(tasks: list, name: str) -> dict | None:
    for t in tasks:
        if str(t.get("task_name") or "").lower() == name.lower():
            return t
    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTaskLifecycle:

    def test_create_task(self, client):
        token = _register_and_login(client)
        name = f"task-create-{uuid.uuid4().hex[:6]}"

        r = client.post(
            "/apps/tasks/create",
            json={"name": name, "category": "integration", "priority": "high"},
            headers=_auth(token),
        )
        assert r.status_code in (200, 201), f"create failed: {r.status_code} {r.text[:300]}"
        d = _data(r)
        assert d.get("task_id"), f"no task_id in response data: {d}"

    def test_list_tasks_initially_empty(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/tasks/list", headers=_auth(token))
        assert r.status_code == 200
        tasks = _tasks_from(r)
        assert isinstance(tasks, list)
        assert len(tasks) == 0, f"expected empty list for fresh user, got {len(tasks)}"

    def test_create_then_list(self, client):
        token = _register_and_login(client)
        name = f"task-list-{uuid.uuid4().hex[:6]}"

        r = client.post(
            "/apps/tasks/create",
            json={"name": name, "category": "integration", "priority": "medium"},
            headers=_auth(token),
        )
        assert r.status_code in (200, 201)

        r = client.get("/apps/tasks/list", headers=_auth(token))
        assert r.status_code == 200
        tasks = _tasks_from(r)
        task = _find_task(tasks, name)
        assert task is not None, f"created task '{name}' not found in list: {tasks}"
        assert task.get("status") == "pending"

    def test_full_lifecycle(self, client):
        """create -> start -> pause -> complete, verifying status at each step."""
        token = _register_and_login(client)
        name = f"task-lifecycle-{uuid.uuid4().hex[:6]}"

        # create
        r = client.post(
            "/apps/tasks/create",
            json={"name": name, "category": "integration", "priority": "high"},
            headers=_auth(token),
        )
        assert r.status_code in (200, 201), f"create: {r.status_code} {r.text[:200]}"

        # start
        r = client.post("/apps/tasks/start", json={"name": name}, headers=_auth(token))
        assert r.status_code in (200, 201, 202), f"start: {r.status_code} {r.text[:200]}"

        r = client.get("/apps/tasks/list", headers=_auth(token))
        task = _find_task(_tasks_from(r), name)
        assert task is not None
        assert task.get("status") == "in_progress", f"expected in_progress after start, got {task.get('status')}"

        # pause
        r = client.post("/apps/tasks/pause", json={"name": name}, headers=_auth(token))
        assert r.status_code in (200, 201, 202), f"pause: {r.status_code} {r.text[:200]}"

        r = client.get("/apps/tasks/list", headers=_auth(token))
        task = _find_task(_tasks_from(r), name)
        assert task is not None
        assert task.get("status") == "paused", f"expected paused, got {task.get('status')}"

        # complete
        r = client.post("/apps/tasks/complete", json={"name": name}, headers=_auth(token))
        assert r.status_code in (200, 201, 202), f"complete: {r.status_code} {r.text[:200]}"

        r = client.get("/apps/tasks/list", headers=_auth(token))
        task = _find_task(_tasks_from(r), name)
        assert task is not None
        assert task.get("status") == "completed", f"expected completed, got {task.get('status')}"

    def test_complete_response_shape(self, client):
        """task_completion flow returns task_result + orchestration keys."""
        token = _register_and_login(client)
        name = f"task-complete-shape-{uuid.uuid4().hex[:6]}"

        client.post(
            "/apps/tasks/create",
            json={"name": name},
            headers=_auth(token),
        )
        client.post("/apps/tasks/start", json={"name": name}, headers=_auth(token))

        r = client.post("/apps/tasks/complete", json={"name": name}, headers=_auth(token))
        assert r.status_code in (200, 201, 202)
        d = _data(r)
        # task_completion flow result: {task_result: ..., orchestration: ...}
        assert "task_result" in d or "execution_envelope" in d, (
            f"expected task_result or execution_envelope in complete response data: {list(d.keys())}"
        )

    def test_recurrence_check_endpoint(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/tasks/recurrence/check", json={}, headers=_auth(token))
        assert r.status_code in (200, 201, 202), f"recurrence check: {r.status_code} {r.text[:200]}"

    def test_unauthenticated_returns_401(self, client):
        r = client.get("/apps/tasks/list")
        assert r.status_code == 401

    def test_create_requires_name(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/tasks/create", json={}, headers=_auth(token))
        # missing name should return 422 (validation) or 400
        assert r.status_code in (400, 422), f"expected 400/422 for missing name, got {r.status_code}"

    def test_tasks_isolated_per_user(self, client):
        """Two users cannot see each other's tasks."""
        token_a = _register_and_login(client)
        token_b = _register_and_login(client)
        name = f"task-isolation-{uuid.uuid4().hex[:6]}"

        client.post(
            "/apps/tasks/create",
            json={"name": name},
            headers=_auth(token_a),
        )

        r = client.get("/apps/tasks/list", headers=_auth(token_b))
        tasks_b = _tasks_from(r)
        assert _find_task(tasks_b, name) is None, (
            f"user B can see user A's task '{name}' — isolation broken"
        )
