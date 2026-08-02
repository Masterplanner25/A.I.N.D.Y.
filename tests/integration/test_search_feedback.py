"""
Integration tests for the Search feedback endpoints (Search v4 outcome signal).

    POST /apps/search/feedback          — record implicit/explicit result feedback
    GET  /apps/search/feedback/weights  — read the blended per-query outcome weights

Endpoint contracts end-to-end against a live Postgres stack: capture round-trips into
the aggregated weight, an explicit flip replaces the opposing vote, an unknown signal is
rejected, and both routes require auth.

    docker compose -f docker-compose.test.yml up -d
    pytest -c pytest.integration.ini tests/integration/test_search_feedback.py -v
"""
from __future__ import annotations

import uuid

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.app_profile]


def _register_and_login(client) -> str:
    email = f"test-searchfb-{uuid.uuid4().hex[:8]}@aindy.test"
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


class TestSearchFeedback:

    def test_record_implicit_click(self, client):
        token = _register_and_login(client)
        r = client.post(
            "/apps/search/feedback",
            json={"query": "ai crm", "result_ref": "r1", "signal": "click"},
            headers=_auth(token),
        )
        assert r.status_code == 200, r.text[:300]
        d = _data(r)
        assert d.get("recorded") is True
        assert d.get("kind") == "implicit"
        assert d.get("weight") == 0.3

    def test_capture_round_trips_into_weights(self, client):
        token = _register_and_login(client)
        client.post(
            "/apps/search/feedback",
            json={"query": "q", "result_ref": "r1", "signal": "click"},
            headers=_auth(token),
        )
        client.post(
            "/apps/search/feedback",
            json={"query": "q", "result_ref": "r1", "signal": "thumbs_up"},
            headers=_auth(token),
        )
        r = client.get("/apps/search/feedback/weights", params={"query": "q"}, headers=_auth(token))
        assert r.status_code == 200, r.text[:300]
        d = _data(r)
        assert d.get("weights", {}).get("r1") == pytest.approx(1.3)
        assert d.get("count") == 1

    def test_explicit_flip_replaces_opposing_vote(self, client):
        token = _register_and_login(client)
        for signal in ("thumbs_up", "thumbs_down"):
            client.post(
                "/apps/search/feedback",
                json={"query": "q", "result_ref": "r1", "signal": signal},
                headers=_auth(token),
            )
        d = _data(client.get("/apps/search/feedback/weights", params={"query": "q"}, headers=_auth(token)))
        assert d.get("weights", {}).get("r1") == pytest.approx(-1.0)

    def test_unknown_signal_rejected(self, client):
        token = _register_and_login(client)
        r = client.post(
            "/apps/search/feedback",
            json={"query": "q", "result_ref": "r1", "signal": "nope"},
            headers=_auth(token),
        )
        assert r.status_code == 422, r.text[:300]

    def test_weights_empty_for_unknown_query(self, client):
        token = _register_and_login(client)
        d = _data(client.get("/apps/search/feedback/weights", params={"query": "never-searched"}, headers=_auth(token)))
        assert d.get("weights") == {}
        assert d.get("count") == 0

    def test_endpoints_require_auth(self, client):
        assert client.post(
            "/apps/search/feedback",
            json={"query": "q", "result_ref": "r1", "signal": "click"},
        ).status_code == 401
        assert client.get(
            "/apps/search/feedback/weights", params={"query": "q"}
        ).status_code == 401
