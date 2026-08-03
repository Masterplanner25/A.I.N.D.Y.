"""
Integration tests for the Search Execution Layer endpoints.

    POST /apps/leadgen/execute         — act on scored leads (dry-run default)
    POST /apps/leadgen/execute/revert  — revert a lead action
    GET  /apps/leadgen/actions         — list lead actions

Endpoint contracts only: a fresh user has no leads, so the gate proposes nothing —
which exercises the dry-run/apply/no-action/history/revert-not-found paths without
needing to seed or make an LLM call.

Requires a live Postgres stack:
    docker compose -f docker-compose.test.yml up -d
    pytest -c pytest.integration.ini tests/integration/test_leadgen_execution.py -v
"""
from __future__ import annotations

import uuid

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.app_profile]


def _register_and_login(client) -> str:
    email = f"test-leadexec-{uuid.uuid4().hex[:8]}@aindy.test"
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


class TestLeadExecute:

    def test_dry_run_is_default(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/leadgen/execute", headers=_auth(token))
        assert r.status_code == 200, r.text[:300]
        d = _data(r)
        assert d.get("dry_run") is True
        assert isinstance(d.get("selected"), list)
        assert "would_act" in d

    def test_fresh_user_has_nothing_to_action(self, client):
        token = _register_and_login(client)
        d = _data(client.post("/apps/leadgen/execute", headers=_auth(token)))
        assert d.get("would_act") is False
        assert d.get("selected") == []

    def test_apply_on_fresh_user_is_no_action(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/leadgen/execute?apply=true", headers=_auth(token))
        assert r.status_code == 200, r.text[:300]
        assert _data(r).get("status") == "no_action"

    def test_actions_history_starts_empty(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/leadgen/actions", headers=_auth(token))
        assert r.status_code == 200, r.text[:300]
        d = _data(r)
        assert d.get("actions") == []
        assert d.get("count") == 0

    def test_revert_unknown_id_returns_not_found(self, client):
        token = _register_and_login(client)
        r = client.post(
            "/apps/leadgen/execute/revert", json={"action_id": 999999}, headers=_auth(token)
        )
        assert r.status_code == 200, r.text[:300]
        assert _data(r).get("status") == "not_found"

    def test_revert_requires_int_action_id(self, client):
        token = _register_and_login(client)
        r = client.post(
            "/apps/leadgen/execute/revert", json={"action_id": "nope"}, headers=_auth(token)
        )
        assert r.status_code == 422  # pydantic rejects non-int

    def test_unauthenticated_returns_401(self, client):
        assert client.post("/apps/leadgen/execute").status_code == 401
        assert client.get("/apps/leadgen/actions").status_code == 401
        assert client.post(
            "/apps/leadgen/execute/revert", json={"action_id": 1}
        ).status_code == 401
