"""
Integration tests for the Freelance Revenue Intelligence endpoints.

    POST /apps/freelance/pricing/optimize         — recommend/apply (dry-run default)
    POST /apps/freelance/pricing/revert           — revert an applied recommendation
    GET  /apps/freelance/pricing/recommendations  — recommendation history
    GET  /apps/freelance/pricing                  — current default-price catalog

Endpoint contracts only: a fresh user has no orders, so the gate proposes nothing —
exercising the dry-run/apply/no-change/history/catalog/revert-not-found paths without
seeding.

Requires a live Postgres stack:
    docker compose -f docker-compose.test.yml up -d
    pytest -c pytest.integration.ini tests/integration/test_freelance_pricing.py -v
"""
from __future__ import annotations

import uuid

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.app_profile]


def _register_and_login(client) -> str:
    email = f"test-pricing-{uuid.uuid4().hex[:8]}@aindy.test"
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


class TestFreelancePricing:

    def test_optimize_dry_run_is_default(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/freelance/pricing/optimize", headers=_auth(token))
        assert r.status_code == 200, r.text[:300]
        d = _data(r)
        assert d.get("dry_run") is True
        assert isinstance(d.get("recommendations"), list)
        assert "would_change" in d

    def test_fresh_user_has_nothing_to_price(self, client):
        token = _register_and_login(client)
        d = _data(client.post("/apps/freelance/pricing/optimize", headers=_auth(token)))
        assert d.get("would_change") is False
        assert d.get("recommendations") == []

    def test_apply_on_fresh_user_is_no_change(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/freelance/pricing/optimize?apply=true", headers=_auth(token))
        assert r.status_code == 200, r.text[:300]
        assert _data(r).get("status") == "no_change"

    def test_catalog_starts_empty(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/freelance/pricing", headers=_auth(token))
        assert r.status_code == 200, r.text[:300]
        d = _data(r)
        assert d.get("prices") == []
        assert d.get("count") == 0

    def test_recommendations_history_starts_empty(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/freelance/pricing/recommendations", headers=_auth(token))
        assert r.status_code == 200, r.text[:300]
        d = _data(r)
        assert d.get("recommendations") == []
        assert d.get("count") == 0

    def test_revert_unknown_id_returns_not_found(self, client):
        token = _register_and_login(client)
        r = client.post(
            "/apps/freelance/pricing/revert",
            json={"recommendation_id": 999999},
            headers=_auth(token),
        )
        assert r.status_code == 200, r.text[:300]
        assert _data(r).get("status") == "not_found"

    def test_revert_requires_int_id(self, client):
        token = _register_and_login(client)
        r = client.post(
            "/apps/freelance/pricing/revert",
            json={"recommendation_id": "nope"},
            headers=_auth(token),
        )
        assert r.status_code == 422

    def test_unauthenticated_returns_401(self, client):
        assert client.post("/apps/freelance/pricing/optimize").status_code == 401
        assert client.get("/apps/freelance/pricing").status_code == 401
        assert client.get("/apps/freelance/pricing/recommendations").status_code == 401
        assert client.post(
            "/apps/freelance/pricing/revert", json={"recommendation_id": 1}
        ).status_code == 401
