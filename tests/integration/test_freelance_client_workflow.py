"""
Integration tests for the Phase 3 client-workflow endpoints.

    POST /apps/freelance/clients/onboard         — lead -> client + order -> dispatch
    POST /apps/freelance/orders/{id}/fulfill      — deliver order -> refresh metrics

Endpoint contracts only (a fresh user has no leads/orders), exercising the
idempotency-key gate, the 404 path when the referenced lead/order is absent, and auth.

Requires a live Postgres stack:
    docker compose -f docker-compose.test.yml up -d
    pytest -c pytest.integration.ini tests/integration/test_freelance_client_workflow.py -v
"""
from __future__ import annotations

import uuid

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.app_profile]


def _register_and_login(client) -> str:
    email = f"test-freelancecw-{uuid.uuid4().hex[:8]}@aindy.test"
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


class TestOnboardClient:

    def test_onboard_requires_idempotency_key(self, client):
        token = _register_and_login(client)
        r = client.post(
            "/apps/freelance/clients/onboard",
            json={"lead_id": 1, "client_email": "b@x.com", "service_type": "web"},
            headers=_auth(token),
        )
        assert r.status_code == 400

    def test_onboard_unknown_lead_returns_404(self, client):
        token = _register_and_login(client)
        r = client.post(
            "/apps/freelance/clients/onboard",
            json={"lead_id": 999999, "client_email": "b@x.com", "service_type": "web"},
            headers={**_auth(token), "Idempotency-Key": uuid.uuid4().hex},
        )
        assert r.status_code == 404, r.text[:300]

    def test_onboard_requires_auth(self, client):
        assert client.post(
            "/apps/freelance/clients/onboard",
            json={"lead_id": 1, "client_email": "b@x.com", "service_type": "web"},
        ).status_code == 401


class TestFulfillOrder:

    def test_fulfill_unknown_order_returns_404(self, client):
        token = _register_and_login(client)
        r = client.post(
            "/apps/freelance/orders/999999/fulfill",
            json={"ai_output": "done"},
            headers=_auth(token),
        )
        assert r.status_code == 404, r.text[:300]

    def test_fulfill_requires_auth(self, client):
        assert client.post(
            "/apps/freelance/orders/1/fulfill", json={"ai_output": "done"}
        ).status_code == 401
