"""
Integration tests: data ownership and cross-domain isolation.

Requires a live Postgres stack:
    docker compose -f docker-compose.test.yml up -d
    pytest -c pytest.integration.ini tests/integration/test_data_ownership.py -v

Verifies that the user-id ownership boundary is enforced across every domain
touched by the apps layer. Each test registers two independent users and asserts
that actions by User A are invisible and inaccessible to User B, and vice-versa.

Domains exercised (multi-domain ownership):
  - Tasks       /apps/tasks/…
  - Compute     /apps/compute/…
  - Identity    /identity/…
  - ARM         /apps/arm/…
  - Agents      agent domain
"""
from __future__ import annotations

import uuid
import pytest


pytestmark = [pytest.mark.integration, pytest.mark.app_profile]

# ---------------------------------------------------------------------------
# Minimal payloads
# ---------------------------------------------------------------------------

_TASK_PAYLOAD = {"name": "ownership-test-task", "category": "integration", "priority": "high"}

_CALC_PAYLOAD = {
    "task_name": "ownership-calc",
    "time_spent": 1.0,
    "task_complexity": 2,
    "skill_level": 3,
    "ai_utilization": 4,
    "task_difficulty": 1,
}

_ENGAGEMENT_PAYLOAD = {
    "likes": 5,
    "shares": 2,
    "comments": 1,
    "clicks": 10,
    "time_on_page": 15.0,
    "total_views": 50,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _register_and_login(client, *, prefix: str = "own") -> str:
    email = f"test-{prefix}-{uuid.uuid4().hex[:8]}@aindy.test"
    password = "IntegrationTest1!"
    r = client.post("/auth/register", json={"email": email, "password": password})
    assert r.status_code in (200, 201, 202), f"register: {r.status_code} {r.text[:200]}"
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login: {r.status_code} {r.text[:200]}"
    body = r.json()
    token = body.get("access_token") or (body.get("data") or {}).get("access_token")
    assert token, f"no access_token in: {body}"
    return token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _data(response) -> dict:
    body = response.json()
    return body.get("data") or {}


def _tasks(response) -> list:
    d = _data(response)
    tasks = d.get("tasks") if isinstance(d, dict) else None
    if isinstance(tasks, list):
        return tasks
    return d if isinstance(d, list) else []


def _calc_results(response) -> list:
    return (response.json().get("data") or [])


# ---------------------------------------------------------------------------
# Task ownership
# ---------------------------------------------------------------------------

class TestTaskOwnership:

    def test_user_b_cannot_see_user_a_tasks(self, client):
        token_a = _register_and_login(client, prefix="own-ta")
        token_b = _register_and_login(client, prefix="own-tb")

        client.post("/apps/tasks/create", json=_TASK_PAYLOAD, headers=_auth(token_a))

        r = client.get("/apps/tasks/list", headers=_auth(token_b))
        assert r.status_code == 200
        tasks = _tasks(r)
        names = [t.get("task_name") or t.get("name") for t in tasks]
        assert _TASK_PAYLOAD["name"] not in names, (
            f"User B can see User A's task — isolation broken: {names}"
        )

    def test_user_a_task_invisible_to_b_after_lifecycle(self, client):
        """User A progresses a task through its lifecycle; User B sees nothing."""
        token_a = _register_and_login(client, prefix="own-lc-a")
        token_b = _register_and_login(client, prefix="own-lc-b")
        name = f"lifecycle-{uuid.uuid4().hex[:6]}"

        client.post("/apps/tasks/create", json={"name": name}, headers=_auth(token_a))
        client.post("/apps/tasks/start", json={"name": name}, headers=_auth(token_a))
        client.post("/apps/tasks/complete", json={"name": name}, headers=_auth(token_a))

        r = client.get("/apps/tasks/list", headers=_auth(token_b))
        tasks_b = _tasks(r)
        found = [t for t in tasks_b if (t.get("task_name") or t.get("name")) == name]
        assert not found, f"User B sees User A's completed task: {found}"

    def test_user_b_action_on_user_a_task_fails(self, client):
        """User B calling start on a task that only User A owns must fail, not silently succeed."""
        token_a = _register_and_login(client, prefix="own-x-a")
        token_b = _register_and_login(client, prefix="own-x-b")
        name = f"exclusive-{uuid.uuid4().hex[:6]}"

        client.post("/apps/tasks/create", json={"name": name}, headers=_auth(token_a))

        r = client.post("/apps/tasks/start", json={"name": name}, headers=_auth(token_b))
        # task_start flow looks up by (name, user_id=B); no task found → flow error
        assert r.status_code not in (200, 201, 202), (
            f"User B was allowed to start User A's task (status {r.status_code})"
        )

    def test_user_b_complete_on_user_a_task_fails(self, client):
        token_a = _register_and_login(client, prefix="own-cp-a")
        token_b = _register_and_login(client, prefix="own-cp-b")
        name = f"complete-excl-{uuid.uuid4().hex[:6]}"

        client.post("/apps/tasks/create", json={"name": name}, headers=_auth(token_a))

        r = client.post("/apps/tasks/complete", json={"name": name}, headers=_auth(token_b))
        assert r.status_code not in (200, 201, 202), (
            f"User B was allowed to complete User A's task (status {r.status_code})"
        )

    def test_both_users_independent_task_lists(self, client):
        """Each user creates a differently-named task; each sees only their own."""
        token_a = _register_and_login(client, prefix="own-bi-a")
        token_b = _register_and_login(client, prefix="own-bi-b")
        name_a = f"task-a-{uuid.uuid4().hex[:6]}"
        name_b = f"task-b-{uuid.uuid4().hex[:6]}"

        client.post("/apps/tasks/create", json={"name": name_a}, headers=_auth(token_a))
        client.post("/apps/tasks/create", json={"name": name_b}, headers=_auth(token_b))

        tasks_a = _tasks(client.get("/apps/tasks/list", headers=_auth(token_a)))
        tasks_b = _tasks(client.get("/apps/tasks/list", headers=_auth(token_b)))

        names_a = {t.get("task_name") or t.get("name") for t in tasks_a}
        names_b = {t.get("task_name") or t.get("name") for t in tasks_b}

        assert name_a in names_a, "User A cannot see their own task"
        assert name_b not in names_a, "User A can see User B's task"
        assert name_b in names_b, "User B cannot see their own task"
        assert name_a not in names_b, "User B can see User A's task"


# ---------------------------------------------------------------------------
# Compute / calculation results ownership
# ---------------------------------------------------------------------------

class TestComputeOwnership:

    def test_user_b_results_empty_after_user_a_calculates(self, client):
        token_a = _register_and_login(client, prefix="own-ca")
        token_b = _register_and_login(client, prefix="own-cb")

        client.post("/apps/compute/calculate_effort", json=_CALC_PAYLOAD, headers=_auth(token_a))
        client.post("/apps/compute/calculate_engagement", json=_ENGAGEMENT_PAYLOAD, headers=_auth(token_a))

        r = client.get("/apps/compute/results", headers=_auth(token_b))
        results_b = _calc_results(r)
        assert len(results_b) == 0, (
            f"User B sees {len(results_b)} result(s) that belong to User A"
        )

    def test_user_a_results_unaffected_by_user_b_calculations(self, client):
        token_a = _register_and_login(client, prefix="own-ca2")
        token_b = _register_and_login(client, prefix="own-cb2")

        client.post("/apps/compute/calculate_effort", json=_CALC_PAYLOAD, headers=_auth(token_a))

        r_a_before = client.get("/apps/compute/results", headers=_auth(token_a))
        count_a_before = len(_calc_results(r_a_before))
        assert count_a_before >= 1

        client.post("/apps/compute/calculate_engagement", json=_ENGAGEMENT_PAYLOAD, headers=_auth(token_b))
        client.post("/apps/compute/calculate_effort", json=_CALC_PAYLOAD, headers=_auth(token_b))

        r_a_after = client.get("/apps/compute/results", headers=_auth(token_a))
        count_a_after = len(_calc_results(r_a_after))
        assert count_a_after == count_a_before, (
            f"User A's result count changed from {count_a_before} to {count_a_after} "
            "after User B ran calculations — namespace leak"
        )

    def test_kpi_weights_isolated(self, client):
        """POST adapt for User A does not change User B's adaptation state."""
        token_a = _register_and_login(client, prefix="own-kw-a")
        token_b = _register_and_login(client, prefix="own-kw-b")

        client.post("/apps/analytics/kpi-weights/adapt", json={}, headers=_auth(token_a))

        r = client.get("/apps/analytics/kpi-weights", headers=_auth(token_b))
        d = _data(r)
        assert d.get("adapted_count") == 0, (
            f"User B's adapted_count is {d.get('adapted_count')}, expected 0"
        )
        assert d.get("is_personalized") is False, (
            "User B's weights show as personalized after User A adapted"
        )


# ---------------------------------------------------------------------------
# Identity ownership
# ---------------------------------------------------------------------------

class TestIdentityOwnership:

    def test_user_b_profile_blank_after_user_a_updates(self, client):
        token_a = _register_and_login(client, prefix="own-id-a")
        token_b = _register_and_login(client, prefix="own-id-b")

        client.put(
            "/identity/",
            json={"tone": "technical", "risk_tolerance": "aggressive"},
            headers=_auth(token_a),
        )

        r = client.get("/identity/", headers=_auth(token_b))
        d = _data(r)
        assert d["communication"]["tone"] is None, (
            f"User B's tone is '{d['communication']['tone']}', expected None"
        )
        assert d["decision_making"]["risk_tolerance"] is None, (
            f"User B's risk_tolerance is '{d['decision_making']['risk_tolerance']}', expected None"
        )

    def test_user_a_profile_unaffected_by_user_b_updates(self, client):
        token_a = _register_and_login(client, prefix="own-id2-a")
        token_b = _register_and_login(client, prefix="own-id2-b")

        client.put("/identity/", json={"tone": "formal"}, headers=_auth(token_a))
        client.put("/identity/", json={"tone": "casual"}, headers=_auth(token_b))

        r = client.get("/identity/", headers=_auth(token_a))
        assert _data(r)["communication"]["tone"] == "formal", (
            "User A's tone was overwritten by User B's update"
        )

    def test_evolution_isolated(self, client):
        """User A's identity evolution log does not appear in User B's evolution."""
        token_a = _register_and_login(client, prefix="own-ev-a")
        token_b = _register_and_login(client, prefix="own-ev-b")

        client.put("/identity/", json={"tone": "concise"}, headers=_auth(token_a))
        client.put("/identity/", json={"risk_tolerance": "moderate"}, headers=_auth(token_a))

        r = client.get("/identity/evolution", headers=_auth(token_b))
        d = _data(r)
        assert d.get("total_changes") == 0, (
            f"User B's evolution shows {d.get('total_changes')} change(s) from User A"
        )


# ---------------------------------------------------------------------------
# ARM config ownership
# ---------------------------------------------------------------------------

class TestArmOwnership:

    def test_user_b_arm_config_unchanged_after_user_a_update(self, client):
        token_a = _register_and_login(client, prefix="own-arm-a")
        token_b = _register_and_login(client, prefix="own-arm-b")

        # Record User B's default temperature before any changes
        r = client.get("/apps/arm/config", headers=_auth(token_b))
        default_temp = _data(r).get("temperature")

        # User A changes their temperature to a distinct value
        client.put(
            "/apps/arm/config",
            json={"updates": {"temperature": 0.99}},
            headers=_auth(token_a),
        )

        # User B's temperature must still be the default
        r = client.get("/apps/arm/config", headers=_auth(token_b))
        temp_b = _data(r).get("temperature")
        assert temp_b == default_temp, (
            f"User B's temperature changed to {temp_b} after User A set 0.99 "
            f"(was {default_temp}) — ARM config namespace leak"
        )
        assert temp_b != 0.99, "User B inherited User A's temperature (0.99)"

    def test_arm_config_updates_independent(self, client):
        """Both users update different config keys; each sees only their own values."""
        token_a = _register_and_login(client, prefix="own-arm2-a")
        token_b = _register_and_login(client, prefix="own-arm2-b")

        client.put(
            "/apps/arm/config",
            json={"updates": {"retry_limit": 7}},
            headers=_auth(token_a),
        )
        client.put(
            "/apps/arm/config",
            json={"updates": {"retry_limit": 3}},
            headers=_auth(token_b),
        )

        r_a = client.get("/apps/arm/config", headers=_auth(token_a))
        r_b = client.get("/apps/arm/config", headers=_auth(token_b))

        assert _data(r_a).get("retry_limit") == 7, "User A's retry_limit was overwritten"
        assert _data(r_b).get("retry_limit") == 3, "User B's retry_limit was overwritten"

    def test_arm_logs_isolated(self, client):
        """New users each have zero ARM logs — no bleed from other sessions."""
        token_a = _register_and_login(client, prefix="own-armlog-a")
        token_b = _register_and_login(client, prefix="own-armlog-b")

        r_a = client.get("/apps/arm/logs", headers=_auth(token_a))
        r_b = client.get("/apps/arm/logs", headers=_auth(token_b))

        assert _data(r_a).get("summary", {}).get("total_analyses") == 0
        assert _data(r_b).get("summary", {}).get("total_analyses") == 0


# ---------------------------------------------------------------------------
# Multi-domain simultaneous ownership
# ---------------------------------------------------------------------------

class TestMultiDomainOwnership:

    def test_user_a_activity_does_not_pollute_user_b_across_all_domains(self, client):
        """
        User A is active across tasks, compute, identity, and ARM simultaneously.
        User B performs fresh reads in all four domains and must see empty/default state
        in every one.
        """
        token_a = _register_and_login(client, prefix="own-md-a")
        token_b = _register_and_login(client, prefix="own-md-b")

        task_name = f"multi-domain-{uuid.uuid4().hex[:6]}"

        # User A: tasks domain
        client.post("/apps/tasks/create", json={"name": task_name}, headers=_auth(token_a))
        client.post("/apps/tasks/start", json={"name": task_name}, headers=_auth(token_a))

        # User A: compute domain
        client.post("/apps/compute/calculate_effort", json=_CALC_PAYLOAD, headers=_auth(token_a))
        client.post("/apps/compute/calculate_engagement", json=_ENGAGEMENT_PAYLOAD, headers=_auth(token_a))

        # User A: identity domain
        client.put("/identity/", json={"tone": "technical", "risk_tolerance": "aggressive"}, headers=_auth(token_a))

        # User A: ARM config domain
        client.put("/apps/arm/config", json={"updates": {"temperature": 0.99}}, headers=_auth(token_a))

        # --- Now verify User B's state in all four domains ---

        # Tasks: User B sees no tasks
        r = client.get("/apps/tasks/list", headers=_auth(token_b))
        tasks_b = _tasks(r)
        b_task_names = {t.get("task_name") or t.get("name") for t in tasks_b}
        assert task_name not in b_task_names, (
            f"[tasks] User B can see User A's task '{task_name}'"
        )

        # Compute: User B's results are empty
        r = client.get("/apps/compute/results", headers=_auth(token_b))
        results_b = _calc_results(r)
        assert len(results_b) == 0, (
            f"[compute] User B sees {len(results_b)} result(s) from User A"
        )

        # Identity: User B's profile is blank
        r = client.get("/identity/", headers=_auth(token_b))
        d = _data(r)
        assert d["communication"]["tone"] is None, (
            f"[identity] User B's tone is '{d['communication']['tone']}', expected None"
        )
        assert d["decision_making"]["risk_tolerance"] is None, (
            f"[identity] User B's risk_tolerance is '{d['decision_making']['risk_tolerance']}', expected None"
        )

        # ARM: User B's temperature is NOT 0.99
        r = client.get("/apps/arm/config", headers=_auth(token_b))
        temp_b = _data(r).get("temperature")
        assert temp_b != 0.99, (
            f"[arm] User B's temperature is 0.99 — leaked from User A"
        )

    def test_concurrent_writes_no_cross_contamination(self, client):
        """
        Both users write to the same domains at the same time.
        Neither user's reads pick up the other's writes.
        """
        token_a = _register_and_login(client, prefix="own-cw-a")
        token_b = _register_and_login(client, prefix="own-cw-b")

        name_a = f"cw-task-a-{uuid.uuid4().hex[:6]}"
        name_b = f"cw-task-b-{uuid.uuid4().hex[:6]}"

        # Interleave writes from A and B
        client.post("/apps/tasks/create", json={"name": name_a}, headers=_auth(token_a))
        client.post("/apps/tasks/create", json={"name": name_b}, headers=_auth(token_b))
        client.put("/identity/", json={"tone": "formal"}, headers=_auth(token_a))
        client.put("/identity/", json={"tone": "casual"}, headers=_auth(token_b))
        client.post("/apps/compute/calculate_effort", json=_CALC_PAYLOAD, headers=_auth(token_a))
        client.post("/apps/compute/calculate_engagement", json=_ENGAGEMENT_PAYLOAD, headers=_auth(token_b))

        # Reads for A
        tasks_a = _tasks(client.get("/apps/tasks/list", headers=_auth(token_a)))
        names_a = {t.get("task_name") or t.get("name") for t in tasks_a}
        tone_a = _data(client.get("/identity/", headers=_auth(token_a)))["communication"]["tone"]
        results_a = _calc_results(client.get("/apps/compute/results", headers=_auth(token_a)))

        # Reads for B
        tasks_b = _tasks(client.get("/apps/tasks/list", headers=_auth(token_b)))
        names_b = {t.get("task_name") or t.get("name") for t in tasks_b}
        tone_b = _data(client.get("/identity/", headers=_auth(token_b)))["communication"]["tone"]
        results_b = _calc_results(client.get("/apps/compute/results", headers=_auth(token_b)))

        # Tasks isolation
        assert name_a in names_a, "User A cannot see their own task"
        assert name_b not in names_a, "User A sees User B's task"
        assert name_b in names_b, "User B cannot see their own task"
        assert name_a not in names_b, "User B sees User A's task"

        # Identity isolation
        assert tone_a == "formal", f"User A's tone is '{tone_a}', expected 'formal'"
        assert tone_b == "casual", f"User B's tone is '{tone_b}', expected 'casual'"

        # Compute isolation
        assert len(results_a) >= 1, "User A has no calculation results"
        assert len(results_b) >= 1, "User B has no calculation results"
        # Totals must not double (no shared namespace)
        assert len(results_a) == 1, (
            f"User A has {len(results_a)} results — possible namespace leak"
        )
        assert len(results_b) == 1, (
            f"User B has {len(results_b)} results — possible namespace leak"
        )
