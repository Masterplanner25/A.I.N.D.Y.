"""
Integration tests for the three-axis Infinity score endpoints (Phase A, observability).

    GET  /apps/analytics/three-axis          — Volume/Worth/Trajectory snapshot
    POST /apps/analytics/worth/declare        — declare worth (the Worth prior)
    GET  /apps/analytics/worth/declarations   — list declarations

Endpoint contracts end-to-end against a live Postgres stack:
    docker compose -f docker-compose.test.yml up -d
    pytest -c pytest.integration.ini tests/integration/test_three_axis.py -v
"""
from __future__ import annotations

import uuid

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.app_profile]


def _register_and_login(client) -> str:
    email = f"test-threeaxis-{uuid.uuid4().hex[:8]}@aindy.test"
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
    return body.get("data") if isinstance(body, dict) and "data" in body else body


class TestThreeAxis:

    def test_snapshot_shape_for_new_user(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/analytics/three-axis", headers=_auth(token))
        assert r.status_code == 200, r.text[:300]
        d = _data(r)
        assert {"volume", "worth", "trajectory"} <= set(d)
        assert d.get("observability_only") is True

    def test_declare_then_list_and_reflect_in_snapshot(self, client):
        token = _register_and_login(client)
        r = client.post(
            "/apps/analytics/worth/declare",
            json={"target_type": "project", "label": "Nodus", "declared_value": 80.0, "kind": "intrinsic"},
            headers=_auth(token),
        )
        assert r.status_code == 200, r.text[:300]
        assert _data(r).get("declared_value") == 80.0

        listed = _data(client.get("/apps/analytics/worth/declarations", headers=_auth(token)))
        assert listed.get("count") == 1

        snap = _data(client.get("/apps/analytics/three-axis", headers=_auth(token)))
        assert snap["worth"]["declared_total"] == pytest.approx(80.0)

    def test_declare_rejects_bad_kind(self, client):
        token = _register_and_login(client)
        r = client.post(
            "/apps/analytics/worth/declare",
            json={"target_type": "task", "declared_value": 1.0, "kind": "bogus"},
            headers=_auth(token),
        )
        assert r.status_code == 422, r.text[:300]

    def test_endpoints_require_auth(self, client):
        assert client.get("/apps/analytics/three-axis").status_code == 401
        assert client.get("/apps/analytics/worth/declarations").status_code == 401
        assert client.post(
            "/apps/analytics/worth/declare",
            json={"target_type": "task", "declared_value": 1.0},
        ).status_code == 401
