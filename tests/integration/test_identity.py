"""
Integration tests for the identity domain.

Requires a live Postgres stack:
    docker compose -f docker-compose.test.yml up -d
    pytest -c pytest.integration.ini tests/integration/test_identity.py -v

Covers:
    GET  /identity/        — profile get (auto-creates blank on first access)
    PUT  /identity/        — explicit preference update + evolution log
    GET  /identity/evolution — change history
    GET  /identity/context   — LLM prompt context string
    GET  /identity/boot      — full boot context (memory, runs, flows, runtime)
"""
from __future__ import annotations

import uuid
import pytest


pytestmark = [pytest.mark.integration, pytest.mark.app_profile]


# ---------------------------------------------------------------------------
# Helpers (shared with test_tasks; kept local to avoid coupling)
# ---------------------------------------------------------------------------

def _register_and_login(client) -> str:
    email = f"test-identity-{uuid.uuid4().hex[:8]}@aindy.test"
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


# ---------------------------------------------------------------------------
# GET /identity/ — profile shape and auto-create
# ---------------------------------------------------------------------------

class TestGetIdentity:

    def test_returns_200(self, client):
        token = _register_and_login(client)
        r = client.get("/identity/", headers=_auth(token))
        assert r.status_code == 200, r.text[:300]

    def test_profile_has_required_sections(self, client):
        token = _register_and_login(client)
        r = client.get("/identity/", headers=_auth(token))
        d = _data(r)
        for section in ("communication", "tools", "decision_making", "learning", "evolution"):
            assert section in d, f"missing section '{section}' in profile: {list(d.keys())}"

    def test_blank_profile_for_new_user(self, client):
        """Fresh user gets auto-created blank profile — no preferences set."""
        token = _register_and_login(client)
        r = client.get("/identity/", headers=_auth(token))
        d = _data(r)
        assert d["communication"]["tone"] is None
        assert d["tools"]["preferred_languages"] == []
        assert d["tools"]["preferred_tools"] == []
        assert d["tools"]["avoided_tools"] == []
        assert d["decision_making"]["risk_tolerance"] is None
        assert d["evolution"]["change_count"] == 0

    def test_unauthenticated_returns_401(self, client):
        r = client.get("/identity/")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# PUT /identity/ — explicit preference update
# ---------------------------------------------------------------------------

class TestUpdateIdentity:

    def test_update_tone(self, client):
        token = _register_and_login(client)
        r = client.put("/identity/", json={"tone": "technical"}, headers=_auth(token))
        assert r.status_code in (200, 201), r.text[:300]
        d = _data(r)
        assert d.get("changes_recorded") == 1
        assert d["changes"][0]["dimension"] == "tone"
        assert d["changes"][0]["new_value"] == "technical"

    def test_update_preferred_languages(self, client):
        token = _register_and_login(client)
        langs = ["python", "typescript"]
        r = client.put("/identity/", json={"preferred_languages": langs}, headers=_auth(token))
        assert r.status_code in (200, 201)
        d = _data(r)
        assert d.get("changes_recorded", 0) >= 1
        profile = d.get("profile") or {}
        assert profile.get("tools", {}).get("preferred_languages") == langs

    def test_update_decision_making(self, client):
        token = _register_and_login(client)
        r = client.put(
            "/identity/",
            json={"risk_tolerance": "moderate", "speed_vs_quality": "quality"},
            headers=_auth(token),
        )
        assert r.status_code in (200, 201)
        d = _data(r)
        profile = d.get("profile") or {}
        assert profile["decision_making"]["risk_tolerance"] == "moderate"
        assert profile["decision_making"]["speed_vs_quality"] == "quality"

    def test_update_learning_preferences(self, client):
        token = _register_and_login(client)
        r = client.put(
            "/identity/",
            json={"learning_style": "examples", "detail_preference": "step_by_step"},
            headers=_auth(token),
        )
        assert r.status_code in (200, 201)
        d = _data(r)
        profile = d.get("profile") or {}
        assert profile["learning"]["style"] == "examples"
        assert profile["learning"]["detail_preference"] == "step_by_step"

    def test_invalid_tone_silently_ignored(self, client):
        """An unrecognised tone value must not be stored — VALID_TONES gate."""
        token = _register_and_login(client)
        r = client.put("/identity/", json={"tone": "NOTVALID"}, headers=_auth(token))
        assert r.status_code in (200, 201)
        d = _data(r)
        assert d.get("changes_recorded", 0) == 0

        r2 = client.get("/identity/", headers=_auth(token))
        assert _data(r2)["communication"]["tone"] is None

    def test_update_persists_across_requests(self, client):
        token = _register_and_login(client)
        client.put("/identity/", json={"tone": "concise"}, headers=_auth(token))
        r = client.get("/identity/", headers=_auth(token))
        assert _data(r)["communication"]["tone"] == "concise"

    def test_multiple_updates_accumulate(self, client):
        token = _register_and_login(client)
        client.put("/identity/", json={"tone": "formal"}, headers=_auth(token))
        client.put("/identity/", json={"risk_tolerance": "conservative"}, headers=_auth(token))
        r = client.get("/identity/", headers=_auth(token))
        d = _data(r)
        assert d["communication"]["tone"] == "formal"
        assert d["decision_making"]["risk_tolerance"] == "conservative"
        # evolution log should have at least 2 entries
        assert d["evolution"]["change_count"] >= 2


# ---------------------------------------------------------------------------
# GET /identity/evolution
# ---------------------------------------------------------------------------

class TestIdentityEvolution:

    def test_empty_evolution_for_new_user(self, client):
        token = _register_and_login(client)
        r = client.get("/identity/evolution", headers=_auth(token))
        assert r.status_code == 200
        d = _data(r)
        assert d.get("total_changes") == 0
        assert d.get("observation_count") == 0
        assert isinstance(d.get("dimensions_evolved"), list)
        assert len(d["dimensions_evolved"]) == 0

    def test_evolution_records_change_after_update(self, client):
        token = _register_and_login(client)
        client.put("/identity/", json={"tone": "detailed"}, headers=_auth(token))
        r = client.get("/identity/evolution", headers=_auth(token))
        d = _data(r)
        assert d["total_changes"] >= 1
        assert "tone" in d["dimensions_evolved"]
        assert d["most_changed_dimension"] == "tone"

    def test_evolution_arc_populated_after_change(self, client):
        token = _register_and_login(client)
        client.put("/identity/", json={"tone": "casual"}, headers=_auth(token))
        r = client.get("/identity/evolution", headers=_auth(token))
        d = _data(r)
        assert isinstance(d.get("evolution_arc"), str)
        assert len(d["evolution_arc"]) > 0

    def test_recent_changes_capped_at_five(self, client):
        token = _register_and_login(client)
        # generate 7 distinct changes (tone + 6 tool list changes)
        tones = ["formal", "casual", "concise", "detailed", "technical"]
        for tone in tones:
            client.put("/identity/", json={"tone": tone}, headers=_auth(token))
        client.put("/identity/", json={"preferred_languages": ["go"]}, headers=_auth(token))
        client.put("/identity/", json={"preferred_tools": ["neovim"]}, headers=_auth(token))

        r = client.get("/identity/evolution", headers=_auth(token))
        d = _data(r)
        assert len(d.get("recent_changes", [])) <= 5

    def test_unauthenticated_returns_401(self, client):
        r = client.get("/identity/evolution")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /identity/context
# ---------------------------------------------------------------------------

class TestIdentityContext:

    def test_context_empty_for_blank_profile(self, client):
        token = _register_and_login(client)
        r = client.get("/identity/context", headers=_auth(token))
        assert r.status_code == 200
        d = _data(r)
        assert d.get("is_empty") is True
        assert isinstance(d.get("context"), str)
        assert d["context"].strip() == ""

    def test_context_populated_after_tone_set(self, client):
        token = _register_and_login(client)
        client.put("/identity/", json={"tone": "technical"}, headers=_auth(token))
        r = client.get("/identity/context", headers=_auth(token))
        d = _data(r)
        assert d.get("is_empty") is False
        assert "technical" in d["context"].lower()

    def test_context_includes_languages(self, client):
        token = _register_and_login(client)
        client.put("/identity/", json={"preferred_languages": ["python", "rust"]}, headers=_auth(token))
        r = client.get("/identity/context", headers=_auth(token))
        d = _data(r)
        assert d.get("is_empty") is False
        assert "python" in d["context"].lower()

    def test_context_message_differs_by_state(self, client):
        token = _register_and_login(client)

        r = client.get("/identity/context", headers=_auth(token))
        empty_message = _data(r).get("message", "")
        assert empty_message  # some message is always present

        client.put("/identity/", json={"tone": "formal"}, headers=_auth(token))
        r = client.get("/identity/context", headers=_auth(token))
        populated_message = _data(r).get("message", "")
        # message text should change once context is non-empty
        assert populated_message != empty_message


# ---------------------------------------------------------------------------
# GET /identity/inference — evidence behind inferred dimensions
# ---------------------------------------------------------------------------

class TestIdentityInference:

    def test_inference_shape_for_new_user(self, client):
        token = _register_and_login(client)
        r = client.get("/identity/inference", headers=_auth(token))
        assert r.status_code == 200, r.text[:300]
        d = _data(r)
        assert isinstance(d.get("dimensions"), list)
        dims = {row["dimension"] for row in d["dimensions"]}
        assert {"speed_vs_quality", "risk_tolerance"} <= dims
        # a fresh user has no evidence -> nothing inferred, nothing committable
        for row in d["dimensions"]:
            assert row["inferred"] is None
            assert row["committable"] is False
        assert d["languages"]["current"] == []
        assert d["languages"]["evidence"] == {}

    def test_inference_requires_auth(self, client):
        assert client.get("/identity/inference").status_code == 401

    def test_boot_returns_200(self, client):
        token = _register_and_login(client)
        r = client.get("/identity/boot", headers=_auth(token))
        assert r.status_code == 200, r.text[:300]

    def test_boot_has_required_keys(self, client):
        token = _register_and_login(client)
        r = client.get("/identity/boot", headers=_auth(token))
        d = _data(r)
        for key in ("memory", "runs", "system_state", "flows", "runtime"):
            assert key in d, f"missing key '{key}' in boot response: {list(d.keys())}"

    def test_boot_memory_is_list(self, client):
        token = _register_and_login(client)
        r = client.get("/identity/boot", headers=_auth(token))
        assert isinstance(_data(r).get("memory"), list)

    def test_boot_system_state_has_score(self, client):
        token = _register_and_login(client)
        r = client.get("/identity/boot", headers=_auth(token))
        system_state = _data(r).get("system_state") or {}
        assert "score" in system_state, f"missing score in system_state: {system_state}"

    def test_boot_unauthenticated_returns_401(self, client):
        r = client.get("/identity/boot")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------

class TestIdentityIsolation:

    def test_profiles_isolated_per_user(self, client):
        """User B cannot see User A's identity preferences."""
        token_a = _register_and_login(client)
        token_b = _register_and_login(client)

        client.put("/identity/", json={"tone": "technical"}, headers=_auth(token_a))

        r = client.get("/identity/", headers=_auth(token_b))
        assert _data(r)["communication"]["tone"] is None
