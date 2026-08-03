"""
Integration tests for the ARM (Autonomous Reasoning Module) domain.

Requires a live Postgres stack:
    docker compose -f docker-compose.test.yml up -d
    pytest -c pytest.integration.ini tests/integration/test_arm.py -v

LLM-dependent endpoints (POST /apps/arm/analyze, POST /apps/arm/generate) require
DeepSeek. These are covered here only for input validation; actual execution is not
tested (no valid DEEPSEEK_API_KEY in CI). All other endpoints are pure DB/flow and
are fully exercised.

Covers:
    GET /apps/arm/logs          — reasoning session logs (AnalysisResult + CodeGeneration)
    GET /apps/arm/config        — read current ARM config (returns DEFAULT_CONFIG if none set)
    PUT /apps/arm/config        — update ARM config parameters
    GET /apps/arm/metrics       — Thinking KPI report (ARMMetricsService)
    GET /apps/arm/config/suggest — config suggestions from metrics
    POST /apps/arm/analyze       — validation only (LLM call not exercised)
    POST /apps/arm/generate      — validation only (LLM call not exercised)
"""
from __future__ import annotations

import uuid
import pytest


pytestmark = [pytest.mark.integration, pytest.mark.app_profile]

# Expected config keys from DEFAULT_CONFIG
_CONFIG_KEYS = {
    "model",
    "analysis_model",
    "generation_model",
    "temperature",
    "generation_temperature",
    "max_chunk_tokens",
    "max_output_tokens",
    "retry_limit",
    "retry_delay_seconds",
    "max_file_size_bytes",
    "allowed_extensions",
    "task_complexity_default",
    "task_urgency_default",
    "resource_cost_default",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _register_and_login(client) -> str:
    email = f"test-arm-{uuid.uuid4().hex[:8]}@aindy.test"
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


# ---------------------------------------------------------------------------
# GET /apps/arm/logs
# ---------------------------------------------------------------------------

class TestArmLogs:

    def test_returns_200(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/arm/logs", headers=_auth(token))
        assert r.status_code == 200, r.text[:300]

    def test_empty_logs_for_new_user(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/arm/logs", headers=_auth(token))
        d = _data(r)
        assert isinstance(d.get("analyses"), list)
        assert isinstance(d.get("generations"), list)
        assert len(d["analyses"]) == 0
        assert len(d["generations"]) == 0

    def test_summary_structure(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/arm/logs", headers=_auth(token))
        d = _data(r)
        summary = d.get("summary") or {}
        assert "total_analyses" in summary
        assert "total_generations" in summary
        assert "total_tokens_used" in summary
        assert summary["total_analyses"] == 0
        assert summary["total_generations"] == 0
        assert summary["total_tokens_used"] == 0

    def test_limit_param_accepted(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/arm/logs?limit=5", headers=_auth(token))
        assert r.status_code == 200

    def test_unauthenticated_returns_401(self, client):
        r = client.get("/apps/arm/logs")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /apps/arm/config
# ---------------------------------------------------------------------------

class TestArmConfigGet:

    def test_returns_200(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/arm/config", headers=_auth(token))
        assert r.status_code == 200, r.text[:300]

    def test_has_all_default_config_keys(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/arm/config", headers=_auth(token))
        d = _data(r)
        missing = _CONFIG_KEYS - set(d.keys())
        assert not missing, f"missing config keys: {missing}"

    def test_default_temperature_is_float(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/arm/config", headers=_auth(token))
        d = _data(r)
        assert isinstance(d.get("temperature"), float)
        assert 0.0 <= d["temperature"] <= 1.0

    def test_default_allowed_extensions_is_list(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/arm/config", headers=_auth(token))
        d = _data(r)
        exts = d.get("allowed_extensions")
        assert isinstance(exts, list)
        assert ".py" in exts

    def test_unauthenticated_returns_401(self, client):
        r = client.get("/apps/arm/config")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# PUT /apps/arm/config
# ---------------------------------------------------------------------------

class TestArmConfigUpdate:

    def test_returns_200(self, client):
        token = _register_and_login(client)
        r = client.put(
            "/apps/arm/config",
            json={"updates": {"temperature": 0.3}},
            headers=_auth(token),
        )
        assert r.status_code == 200, r.text[:300]

    def test_update_temperature(self, client):
        token = _register_and_login(client)
        r = client.put(
            "/apps/arm/config",
            json={"updates": {"temperature": 0.5}},
            headers=_auth(token),
        )
        d = _data(r)
        assert d.get("status") == "updated"
        config = d.get("config") or {}
        assert config.get("temperature") == 0.5

    def test_update_persists(self, client):
        token = _register_and_login(client)
        client.put(
            "/apps/arm/config",
            json={"updates": {"retry_limit": 5}},
            headers=_auth(token),
        )
        r = client.get("/apps/arm/config", headers=_auth(token))
        d = _data(r)
        assert d.get("retry_limit") == 5

    def test_config_response_has_all_keys(self, client):
        token = _register_and_login(client)
        r = client.put(
            "/apps/arm/config",
            json={"updates": {"temperature": 0.25}},
            headers=_auth(token),
        )
        config = (_data(r) or {}).get("config") or {}
        missing = _CONFIG_KEYS - set(config.keys())
        assert not missing, f"missing config keys after update: {missing}"

    def test_unknown_key_silently_ignored(self, client):
        """Keys not in _UPDATABLE_KEYS are filtered — no error, no injection."""
        token = _register_and_login(client)
        r = client.put(
            "/apps/arm/config",
            json={"updates": {"injected_key": "malicious_value", "temperature": 0.2}},
            headers=_auth(token),
        )
        assert r.status_code == 200
        config = (_data(r) or {}).get("config") or {}
        assert "injected_key" not in config

    def test_empty_updates_is_no_op(self, client):
        """Empty updates dict returns the current config unchanged."""
        token = _register_and_login(client)
        r = client.put(
            "/apps/arm/config",
            json={"updates": {}},
            headers=_auth(token),
        )
        assert r.status_code == 200

    def test_unauthenticated_returns_401(self, client):
        r = client.put("/apps/arm/config", json={"updates": {}})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /apps/arm/metrics
# ---------------------------------------------------------------------------

class TestArmMetrics:

    def test_returns_200(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/arm/metrics", headers=_auth(token))
        assert r.status_code == 200, r.text[:300]

    def test_empty_metrics_for_new_user(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/arm/metrics", headers=_auth(token))
        d = _data(r)
        assert d.get("total_sessions") == 0

    def test_metrics_has_required_top_level_keys(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/arm/metrics", headers=_auth(token))
        d = _data(r)
        for key in ("total_sessions", "execution_speed", "decision_efficiency",
                    "ai_productivity_boost", "lost_potential", "learning_efficiency"):
            assert key in d, f"missing metric key '{key}': {list(d.keys())}"

    def test_execution_speed_is_dict(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/arm/metrics", headers=_auth(token))
        d = _data(r)
        speed = d.get("execution_speed") or {}
        assert isinstance(speed, dict)
        assert "unit" in speed, f"execution_speed missing 'unit': {speed}"

    def test_window_param_accepted(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/arm/metrics?window=7", headers=_auth(token))
        assert r.status_code == 200

    def test_unauthenticated_returns_401(self, client):
        r = client.get("/apps/arm/metrics")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /apps/arm/config/suggest
# ---------------------------------------------------------------------------

class TestArmConfigSuggest:

    def test_returns_200(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/arm/config/suggest", headers=_auth(token))
        assert r.status_code == 200, r.text[:300]

    def test_has_metrics_snapshot(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/arm/config/suggest", headers=_auth(token))
        d = _data(r)
        assert "metrics_snapshot" in d, f"missing metrics_snapshot: {list(d.keys())}"

    def test_metrics_snapshot_has_expected_fields(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/arm/config/suggest", headers=_auth(token))
        snapshot = (_data(r) or {}).get("metrics_snapshot") or {}
        for field in ("decision_efficiency", "execution_speed_avg",
                      "ai_productivity_ratio", "total_sessions"):
            assert field in snapshot, f"missing field '{field}' in metrics_snapshot: {list(snapshot.keys())}"

    def test_window_param_accepted(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/arm/config/suggest?window=14", headers=_auth(token))
        assert r.status_code == 200

    def test_unauthenticated_returns_401(self, client):
        r = client.get("/apps/arm/config/suggest")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /apps/arm/analyze — validation only (no DeepSeek call exercised)
# ---------------------------------------------------------------------------

class TestArmAnalyzeValidation:

    def test_missing_file_path_returns_422(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/arm/analyze", json={}, headers=_auth(token))
        assert r.status_code == 422

    def test_unauthenticated_returns_401(self, client):
        r = client.post("/apps/arm/analyze", json={"file_path": "test.py"})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /apps/arm/generate — validation only (no DeepSeek call exercised)
# ---------------------------------------------------------------------------

class TestArmGenerateValidation:

    def test_missing_prompt_returns_422(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/arm/generate", json={}, headers=_auth(token))
        assert r.status_code == 422

    def test_unauthenticated_returns_401(self, client):
        r = client.post("/apps/arm/generate", json={"prompt": "refactor this"})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /apps/arm/config/auto-tune  (+ /revert, /history)
# ---------------------------------------------------------------------------

class TestArmAutoTune:
    """The closed Reflect -> Adjust loop: gated, auditable, revertible."""

    def test_dry_run_is_default(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/arm/config/auto-tune", headers=_auth(token))
        assert r.status_code == 200, r.text[:300]
        d = _data(r)
        assert d.get("dry_run") is True
        assert isinstance(d.get("applied"), list)
        assert "would_change" in d

    def test_fresh_user_has_nothing_to_tune(self, client):
        """No ARM sessions -> min-sessions gate -> no change proposed."""
        token = _register_and_login(client)
        r = client.post("/apps/arm/config/auto-tune", headers=_auth(token))
        d = _data(r)
        assert d.get("would_change") is False
        assert d.get("applied") == []

    def test_apply_on_fresh_user_is_no_change(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/arm/config/auto-tune?apply=true", headers=_auth(token))
        assert r.status_code == 200, r.text[:300]
        d = _data(r)
        assert d.get("status") == "no_change"
        assert d.get("applied") == []

    def test_history_starts_empty(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/arm/config/auto-tune/history", headers=_auth(token))
        assert r.status_code == 200, r.text[:300]
        d = _data(r)
        assert d.get("runs") == []
        assert d.get("total") == 0

    def test_revert_unknown_id_returns_not_found(self, client):
        token = _register_and_login(client)
        r = client.post(
            "/apps/arm/config/auto-tune/revert",
            json={"log_id": str(uuid.uuid4())},
            headers=_auth(token),
        )
        assert r.status_code == 200, r.text[:300]
        assert _data(r).get("status") == "not_found"

    def test_revert_malformed_id_returns_not_found(self, client):
        token = _register_and_login(client)
        r = client.post(
            "/apps/arm/config/auto-tune/revert",
            json={"log_id": "not-a-uuid"},
            headers=_auth(token),
        )
        assert r.status_code == 200
        assert _data(r).get("status") == "not_found"

    def test_unauthenticated_returns_401(self, client):
        assert client.post("/apps/arm/config/auto-tune").status_code == 401
        assert client.get("/apps/arm/config/auto-tune/history").status_code == 401
        assert client.post(
            "/apps/arm/config/auto-tune/revert", json={"log_id": "x"}
        ).status_code == 401
