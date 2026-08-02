"""
Integration tests for the actioned-lead consumption endpoints.

    GET  /apps/freelance/intake/actioned-leads  — leads Search drafted outreach for
    POST /apps/freelance/intake/from-action     — convert a Search-actioned lead

Endpoint contracts only (a fresh user has no actioned leads).

Requires a live Postgres stack:
    docker compose -f docker-compose.test.yml up -d
    pytest -c pytest.integration.ini tests/integration/test_freelance_intake_wiring.py -v
"""
from __future__ import annotations

import uuid

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.app_profile]


def _register_and_login(client) -> str:
    email = f"test-intakewire-{uuid.uuid4().hex[:8]}@aindy.test"
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


class TestActionedLeadEndpoints:

    def test_actioned_leads_empty_for_fresh_user(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/freelance/intake/actioned-leads", headers=_auth(token))
        assert r.status_code == 200, r.text[:300]
        d = _data(r)
        assert d.get("actioned_leads") == []
        assert d.get("count") == 0

    def test_from_action_requires_idempotency_key(self, client):
        token = _register_and_login(client)
        r = client.post(
            "/apps/freelance/intake/from-action",
            json={"action_id": 1, "client_email": "b@x.com", "service_type": "web"},
            headers=_auth(token),
        )
        assert r.status_code == 400

    def test_from_action_unknown_action_returns_404(self, client):
        token = _register_and_login(client)
        r = client.post(
            "/apps/freelance/intake/from-action",
            json={"action_id": 999999, "client_email": "b@x.com", "service_type": "web"},
            headers={**_auth(token), "Idempotency-Key": uuid.uuid4().hex},
        )
        assert r.status_code == 404, r.text[:300]

    def test_unauthenticated_returns_401(self, client):
        assert client.get("/apps/freelance/intake/actioned-leads").status_code == 401
        assert client.post(
            "/apps/freelance/intake/from-action",
            json={"action_id": 1, "client_email": "b@x.com", "service_type": "web"},
        ).status_code == 401
