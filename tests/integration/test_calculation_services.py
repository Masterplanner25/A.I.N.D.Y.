"""
Integration tests for the analytics calculation domain.

Requires a live Postgres stack:
    docker compose -f docker-compose.test.yml up -d
    pytest -c pytest.integration.ini tests/integration/test_calculation_services.py -v

Response shape for ALL compute/analytics endpoints that go through execute_with_pipeline:
    {
        "status": "success",
        "data": {
            <handler result keys>,
            "execution_envelope": {...}
        },
        "trace_id": "...",
        "eu_id": "...",
        "memory_context_count": 0,
        "metadata": {...}
    }

Scores live under body["data"]["Score Key"], never at the response body top level.
_with_execution_envelope() in these routers passes JSONResponse objects through
unchanged (JSONResponse has both status_code and body attributes), so the pipeline's
canonical shape is preserved end-to-end.

Covers:
    POST /apps/compute/calculate_effort        — TaskInput → "Effort Score"
    POST /apps/compute/calculate_productivity  — TaskInput → "Productivity Score"
    POST /apps/compute/calculate_virality      — ViralityInput → "Virality Score"
    POST /apps/compute/calculate_engagement    — EngagementInput → "Engagement Score"
    POST /apps/compute/calculate_ai_efficiency — AIEfficiencyInput → "AI Efficiency Score"
    POST /apps/compute/calculate_impact_score  — ImpactInput → "Impact Score"
    POST /apps/compute/income_efficiency       — EfficiencyInput → "Income Efficiency"
    POST /apps/compute/revenue_scaling         — RevenueScalingInput → "Revenue Scaling"
    POST /apps/compute/execution_speed         — ExecutionSpeedInput → "Execution Speed"
    POST /apps/compute/attention_value         — AttentionValueInput → "Attention Value"
    POST /apps/compute/engagement_rate         — EngagementRateInput → "Engagement Rate"
    POST /apps/compute/business_growth         — BusinessGrowthInput → "Business Growth"
    POST /apps/compute/monetization_efficiency — MonetizationEfficiencyInput
    POST /apps/compute/ai_productivity_boost   — AIProductivityBoostInput
    POST /apps/compute/lost_potential          — LostPotentialInput → "Lost Potential"
    POST /apps/compute/decision_efficiency     — DecisionEfficiencyInput
    POST /apps/compute/batch_calculations      — BatchInput (empty batch valid)
    GET  /apps/compute/results                 — body["data"] = list
    GET  /apps/analytics/kpi-weights           — body["data"]["weights"]
    POST /apps/analytics/kpi-weights/adapt     — body["data"]["status"] == "insufficient_data"
    GET  /apps/analytics/policy-thresholds     — body["data"]["kpi_low"] + offsets
    POST /apps/analytics/policy-thresholds/adapt

Note: POST /apps/compute/calculate_twr excluded (requires Infinity orchestrator).
      Masterplan-dependent endpoints excluded (no masterplan record for fresh user).
"""
from __future__ import annotations

import uuid
import pytest


pytestmark = [pytest.mark.integration, pytest.mark.app_profile]

# ---------------------------------------------------------------------------
# Minimal valid payloads
# ---------------------------------------------------------------------------

_TASK = {
    "task_name": "integration-test-task",
    "time_spent": 2.0,
    "task_complexity": 3,
    "skill_level": 4,
    "ai_utilization": 5,
    "task_difficulty": 2,
}

_VIRALITY = {
    "share_rate": 0.1,
    "engagement_rate": 0.5,
    "conversion_rate": 0.2,
    "time_factor": 1.0,
}

_ENGAGEMENT = {
    "likes": 10,
    "shares": 5,
    "comments": 3,
    "clicks": 20,
    "time_on_page": 30.0,
    "total_views": 100,
}

_AI_EFFICIENCY = {
    "ai_contributions": 5,
    "human_contributions": 5,
    "total_tasks": 10,
}

_IMPACT = {
    "reach": 1000,
    "engagement": 100,
    "conversion": 10,
}

_EFFICIENCY = {
    "focused_effort": 8.0,
    "ai_utilization": 0.5,
    "time": 40.0,
    "capital": 1000.0,
}

_REVENUE_SCALING = {
    "ai_leverage": 0.8,
    "content_distribution": 0.5,
    "time": 10.0,
    "audience_engagement": 0.7,
}

_EXECUTION_SPEED = {
    "ai_automations": 5.0,
    "systemized_workflows": 3.0,
    "decision_lag": 1.0,
}

_ATTENTION_VALUE = {
    "content_output": 10.0,
    "platform_presence": 0.6,
    "time": 5.0,
}

_ENGAGEMENT_RATE = {
    "total_interactions": 50.0,
    "total_views": 200.0,
}

_BUSINESS_GROWTH = {
    "revenue": 10000.0,
    "expenses": 5000.0,
    "scaling_friction": 0.2,
}

_MONETIZATION_EFFICIENCY = {
    "total_revenue": 5000.0,
    "audience_size": 1000.0,
}

_AI_PRODUCTIVITY_BOOST = {
    "tasks_with_ai": 20.0,
    "tasks_without_ai": 10.0,
    "time_saved": 5.0,
}

_LOST_POTENTIAL = {
    "missed_opportunities": 3.0,
    "time_delayed": 2.0,
    "gains_from_action": 1000.0,
}

_DECISION_EFFICIENCY = {
    "automated_decisions": 8.0,
    "manual_decisions": 2.0,
    "processing_time": 1.0,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _register_and_login(client) -> str:
    email = f"test-calc-{uuid.uuid4().hex[:8]}@aindy.test"
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
    """Extract body['data'] from a pipeline-wrapped response."""
    return response.json().get("data") or {}


def _score(response, key: str) -> float:
    """Extract a numeric score from body['data'][key]."""
    val = _data(response).get(key)
    assert val is not None, (
        f"'{key}' missing from body['data']: {list(_data(response).keys())}"
    )
    return float(val)


# ---------------------------------------------------------------------------
# POST /apps/compute/calculate_effort
# ---------------------------------------------------------------------------

class TestCalculateEffort:

    def test_returns_200(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/calculate_effort", json=_TASK, headers=_auth(token))
        assert r.status_code == 200, r.text[:300]

    def test_effort_score_in_data(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/calculate_effort", json=_TASK, headers=_auth(token))
        assert "Effort Score" in _data(r), f"'Effort Score' missing from data: {list(_data(r).keys())}"
        assert isinstance(_score(r, "Effort Score"), float)

    def test_task_name_echoed(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/calculate_effort", json=_TASK, headers=_auth(token))
        assert _data(r).get("task_name") == _TASK["task_name"]

    def test_missing_task_name_returns_422(self, client):
        token = _register_and_login(client)
        payload = {k: v for k, v in _TASK.items() if k != "task_name"}
        r = client.post("/apps/compute/calculate_effort", json=payload, headers=_auth(token))
        assert r.status_code == 422

    def test_unauthenticated_returns_401(self, client):
        r = client.post("/apps/compute/calculate_effort", json=_TASK)
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /apps/compute/calculate_productivity
# ---------------------------------------------------------------------------

class TestCalculateProductivity:

    def test_returns_200(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/calculate_productivity", json=_TASK, headers=_auth(token))
        assert r.status_code == 200, r.text[:300]

    def test_productivity_score_in_data(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/calculate_productivity", json=_TASK, headers=_auth(token))
        assert "Productivity Score" in _data(r)
        assert isinstance(_score(r, "Productivity Score"), float)

    def test_unauthenticated_returns_401(self, client):
        r = client.post("/apps/compute/calculate_productivity", json=_TASK)
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /apps/compute/calculate_virality
# ---------------------------------------------------------------------------

class TestCalculateVirality:

    def test_returns_200(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/calculate_virality", json=_VIRALITY, headers=_auth(token))
        assert r.status_code == 200, r.text[:300]

    def test_virality_score_in_data(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/calculate_virality", json=_VIRALITY, headers=_auth(token))
        assert "Virality Score" in _data(r)
        assert isinstance(_score(r, "Virality Score"), float)

    def test_unauthenticated_returns_401(self, client):
        r = client.post("/apps/compute/calculate_virality", json=_VIRALITY)
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /apps/compute/calculate_engagement
# ---------------------------------------------------------------------------

class TestCalculateEngagement:

    def test_returns_200(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/calculate_engagement", json=_ENGAGEMENT, headers=_auth(token))
        assert r.status_code == 200, r.text[:300]

    def test_engagement_score_in_data(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/calculate_engagement", json=_ENGAGEMENT, headers=_auth(token))
        assert "Engagement Score" in _data(r)
        assert isinstance(_score(r, "Engagement Score"), float)

    def test_missing_total_views_returns_422(self, client):
        token = _register_and_login(client)
        payload = {k: v for k, v in _ENGAGEMENT.items() if k != "total_views"}
        r = client.post("/apps/compute/calculate_engagement", json=payload, headers=_auth(token))
        assert r.status_code == 422

    def test_unauthenticated_returns_401(self, client):
        r = client.post("/apps/compute/calculate_engagement", json=_ENGAGEMENT)
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /apps/compute/calculate_ai_efficiency
# ---------------------------------------------------------------------------

class TestCalculateAiEfficiency:

    def test_returns_200(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/calculate_ai_efficiency", json=_AI_EFFICIENCY, headers=_auth(token))
        assert r.status_code == 200, r.text[:300]

    def test_ai_efficiency_score_in_data(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/calculate_ai_efficiency", json=_AI_EFFICIENCY, headers=_auth(token))
        assert "AI Efficiency Score" in _data(r)
        assert isinstance(_score(r, "AI Efficiency Score"), float)

    def test_unauthenticated_returns_401(self, client):
        r = client.post("/apps/compute/calculate_ai_efficiency", json=_AI_EFFICIENCY)
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /apps/compute/calculate_impact_score
# ---------------------------------------------------------------------------

class TestCalculateImpactScore:

    def test_returns_200(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/calculate_impact_score", json=_IMPACT, headers=_auth(token))
        assert r.status_code == 200, r.text[:300]

    def test_impact_score_in_data(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/calculate_impact_score", json=_IMPACT, headers=_auth(token))
        assert "Impact Score" in _data(r)
        assert isinstance(_score(r, "Impact Score"), float)

    def test_unauthenticated_returns_401(self, client):
        r = client.post("/apps/compute/calculate_impact_score", json=_IMPACT)
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /apps/compute/income_efficiency
# ---------------------------------------------------------------------------

class TestIncomeEfficiency:

    def test_returns_200(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/income_efficiency", json=_EFFICIENCY, headers=_auth(token))
        assert r.status_code == 200, r.text[:300]

    def test_income_efficiency_in_data(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/income_efficiency", json=_EFFICIENCY, headers=_auth(token))
        assert "Income Efficiency" in _data(r)
        assert isinstance(_score(r, "Income Efficiency"), float)

    def test_unauthenticated_returns_401(self, client):
        r = client.post("/apps/compute/income_efficiency", json=_EFFICIENCY)
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /apps/compute/revenue_scaling
# ---------------------------------------------------------------------------

class TestRevenueScaling:

    def test_returns_200(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/revenue_scaling", json=_REVENUE_SCALING, headers=_auth(token))
        assert r.status_code == 200, r.text[:300]

    def test_revenue_scaling_in_data(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/revenue_scaling", json=_REVENUE_SCALING, headers=_auth(token))
        assert "Revenue Scaling" in _data(r)
        assert isinstance(_score(r, "Revenue Scaling"), float)

    def test_unauthenticated_returns_401(self, client):
        r = client.post("/apps/compute/revenue_scaling", json=_REVENUE_SCALING)
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /apps/compute/execution_speed
# ---------------------------------------------------------------------------

class TestExecutionSpeed:

    def test_returns_200(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/execution_speed", json=_EXECUTION_SPEED, headers=_auth(token))
        assert r.status_code == 200, r.text[:300]

    def test_execution_speed_in_data(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/execution_speed", json=_EXECUTION_SPEED, headers=_auth(token))
        assert "Execution Speed" in _data(r)
        assert isinstance(_score(r, "Execution Speed"), float)

    def test_unauthenticated_returns_401(self, client):
        r = client.post("/apps/compute/execution_speed", json=_EXECUTION_SPEED)
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /apps/compute/attention_value
# ---------------------------------------------------------------------------

class TestAttentionValue:

    def test_returns_200(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/attention_value", json=_ATTENTION_VALUE, headers=_auth(token))
        assert r.status_code == 200, r.text[:300]

    def test_attention_value_in_data(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/attention_value", json=_ATTENTION_VALUE, headers=_auth(token))
        assert "Attention Value" in _data(r)
        assert isinstance(_score(r, "Attention Value"), float)

    def test_unauthenticated_returns_401(self, client):
        r = client.post("/apps/compute/attention_value", json=_ATTENTION_VALUE)
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /apps/compute/engagement_rate
# ---------------------------------------------------------------------------

class TestEngagementRate:

    def test_returns_200(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/engagement_rate", json=_ENGAGEMENT_RATE, headers=_auth(token))
        assert r.status_code == 200, r.text[:300]

    def test_engagement_rate_in_data(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/engagement_rate", json=_ENGAGEMENT_RATE, headers=_auth(token))
        assert "Engagement Rate" in _data(r)
        assert isinstance(_score(r, "Engagement Rate"), float)

    def test_unauthenticated_returns_401(self, client):
        r = client.post("/apps/compute/engagement_rate", json=_ENGAGEMENT_RATE)
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /apps/compute/business_growth
# ---------------------------------------------------------------------------

class TestBusinessGrowth:

    def test_returns_200(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/business_growth", json=_BUSINESS_GROWTH, headers=_auth(token))
        assert r.status_code == 200, r.text[:300]

    def test_business_growth_in_data(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/business_growth", json=_BUSINESS_GROWTH, headers=_auth(token))
        assert "Business Growth" in _data(r)
        assert isinstance(_score(r, "Business Growth"), float)

    def test_unauthenticated_returns_401(self, client):
        r = client.post("/apps/compute/business_growth", json=_BUSINESS_GROWTH)
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /apps/compute/monetization_efficiency
# ---------------------------------------------------------------------------

class TestMonetizationEfficiency:

    def test_returns_200(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/monetization_efficiency", json=_MONETIZATION_EFFICIENCY, headers=_auth(token))
        assert r.status_code == 200, r.text[:300]

    def test_monetization_efficiency_in_data(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/monetization_efficiency", json=_MONETIZATION_EFFICIENCY, headers=_auth(token))
        assert "Monetization Efficiency" in _data(r)
        assert isinstance(_score(r, "Monetization Efficiency"), float)

    def test_unauthenticated_returns_401(self, client):
        r = client.post("/apps/compute/monetization_efficiency", json=_MONETIZATION_EFFICIENCY)
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /apps/compute/ai_productivity_boost
# ---------------------------------------------------------------------------

class TestAiProductivityBoost:

    def test_returns_200(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/ai_productivity_boost", json=_AI_PRODUCTIVITY_BOOST, headers=_auth(token))
        assert r.status_code == 200, r.text[:300]

    def test_ai_productivity_boost_in_data(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/ai_productivity_boost", json=_AI_PRODUCTIVITY_BOOST, headers=_auth(token))
        d = _data(r)
        assert "AI Productivity Boost" in d, f"key missing from data: {list(d.keys())}"
        val = d["AI Productivity Boost"]
        assert isinstance(val, (int, float)), f"unexpected type: {type(val)}"

    def test_unauthenticated_returns_401(self, client):
        r = client.post("/apps/compute/ai_productivity_boost", json=_AI_PRODUCTIVITY_BOOST)
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /apps/compute/lost_potential
# ---------------------------------------------------------------------------

class TestLostPotential:

    def test_returns_200(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/lost_potential", json=_LOST_POTENTIAL, headers=_auth(token))
        assert r.status_code == 200, r.text[:300]

    def test_lost_potential_in_data(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/lost_potential", json=_LOST_POTENTIAL, headers=_auth(token))
        assert "Lost Potential" in _data(r)
        assert isinstance(_score(r, "Lost Potential"), float)

    def test_unauthenticated_returns_401(self, client):
        r = client.post("/apps/compute/lost_potential", json=_LOST_POTENTIAL)
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /apps/compute/decision_efficiency
# ---------------------------------------------------------------------------

class TestDecisionEfficiency:

    def test_returns_200(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/decision_efficiency", json=_DECISION_EFFICIENCY, headers=_auth(token))
        assert r.status_code == 200, r.text[:300]

    def test_decision_efficiency_in_data(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/compute/decision_efficiency", json=_DECISION_EFFICIENCY, headers=_auth(token))
        assert "Decision Efficiency" in _data(r)
        assert isinstance(_score(r, "Decision Efficiency"), float)

    def test_unauthenticated_returns_401(self, client):
        r = client.post("/apps/compute/decision_efficiency", json=_DECISION_EFFICIENCY)
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /apps/compute/batch_calculations
# ---------------------------------------------------------------------------

class TestBatchCalculations:

    def test_empty_batch_returns_200(self, client):
        """Empty BatchInput is valid — all fields default to empty lists."""
        token = _register_and_login(client)
        r = client.post("/apps/compute/batch_calculations", json={}, headers=_auth(token))
        assert r.status_code == 200, r.text[:300]

    def test_batch_with_engagement_data(self, client):
        token = _register_and_login(client)
        payload = {"engagements": [_ENGAGEMENT]}
        r = client.post("/apps/compute/batch_calculations", json=payload, headers=_auth(token))
        assert r.status_code == 200, r.text[:300]
        d = _data(r)
        assert "Engagements" in d, f"'Engagements' key missing from data: {list(d.keys())}"
        assert isinstance(d["Engagements"], list)
        assert len(d["Engagements"]) == 1

    def test_batch_with_multiple_categories(self, client):
        token = _register_and_login(client)
        payload = {
            "engagements": [_ENGAGEMENT],
            "ai_efficiencies": [_AI_EFFICIENCY],
            "impacts": [_IMPACT],
        }
        r = client.post("/apps/compute/batch_calculations", json=payload, headers=_auth(token))
        assert r.status_code == 200, r.text[:300]
        d = _data(r)
        assert "Engagements" in d
        assert "AI Efficiencies" in d
        assert "Impacts" in d

    def test_unauthenticated_returns_401(self, client):
        r = client.post("/apps/compute/batch_calculations", json={})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /apps/compute/results
# ---------------------------------------------------------------------------

class TestComputeResults:

    def test_returns_200(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/compute/results", headers=_auth(token))
        assert r.status_code == 200, r.text[:300]

    def test_empty_for_new_user(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/compute/results", headers=_auth(token))
        items = _data(r) if isinstance(_data(r), list) else (r.json().get("data") or [])
        assert isinstance(items, list)
        assert len(items) == 0

    def test_populated_after_calculation(self, client):
        token = _register_and_login(client)
        client.post("/apps/compute/calculate_effort", json=_TASK, headers=_auth(token))
        r = client.get("/apps/compute/results", headers=_auth(token))
        items = r.json().get("data") or []
        assert len(items) >= 1

    def test_results_isolated_per_user(self, client):
        token_a = _register_and_login(client)
        token_b = _register_and_login(client)
        client.post("/apps/compute/calculate_effort", json=_TASK, headers=_auth(token_a))
        r = client.get("/apps/compute/results", headers=_auth(token_b))
        items = r.json().get("data") or []
        assert len(items) == 0

    def test_unauthenticated_returns_401(self, client):
        r = client.get("/apps/compute/results")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /apps/analytics/kpi-weights
# ---------------------------------------------------------------------------

class TestKpiWeights:

    def test_returns_200(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/analytics/kpi-weights", headers=_auth(token))
        assert r.status_code == 200, r.text[:300]

    def test_has_weights_dict(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/analytics/kpi-weights", headers=_auth(token))
        weights = _data(r).get("weights")
        assert isinstance(weights, dict), f"'weights' should be dict: {_data(r)}"

    def test_weights_has_expected_keys(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/analytics/kpi-weights", headers=_auth(token))
        weights = _data(r).get("weights") or {}
        for key in ("execution_speed", "decision_efficiency", "ai_productivity_boost"):
            assert key in weights, f"'{key}' missing from weights: {list(weights.keys())}"

    def test_default_not_personalized(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/analytics/kpi-weights", headers=_auth(token))
        d = _data(r)
        assert d.get("is_personalized") is False
        assert d.get("adapted_count") == 0

    def test_has_execution_envelope_in_data(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/analytics/kpi-weights", headers=_auth(token))
        assert "execution_envelope" in _data(r)

    def test_unauthenticated_returns_401(self, client):
        r = client.get("/apps/analytics/kpi-weights")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /apps/analytics/kpi-weights/adapt
# ---------------------------------------------------------------------------

class TestKpiWeightsAdapt:

    def test_returns_200(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/analytics/kpi-weights/adapt", json={}, headers=_auth(token))
        assert r.status_code == 200, r.text[:300]

    def test_insufficient_data_for_fresh_user(self, client):
        """Fresh user has no score history — adapt must report insufficient_data."""
        token = _register_and_login(client)
        r = client.post("/apps/analytics/kpi-weights/adapt", json={}, headers=_auth(token))
        d = _data(r)
        assert d.get("status") == "insufficient_data", (
            f"expected insufficient_data for fresh user, got: {d.get('status')}"
        )

    def test_fresh_user_has_zero_samples(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/analytics/kpi-weights/adapt", json={}, headers=_auth(token))
        assert _data(r).get("samples_found") == 0

    def test_unauthenticated_returns_401(self, client):
        r = client.post("/apps/analytics/kpi-weights/adapt", json={})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /apps/analytics/policy-thresholds
# ---------------------------------------------------------------------------

class TestPolicyThresholds:

    def test_returns_200(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/analytics/policy-thresholds", headers=_auth(token))
        assert r.status_code == 200, r.text[:300]

    def test_has_kpi_low_dict(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/analytics/policy-thresholds", headers=_auth(token))
        kpi_low = _data(r).get("kpi_low")
        assert isinstance(kpi_low, dict), f"'kpi_low' should be dict: {_data(r)}"

    def test_kpi_low_has_execution_speed(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/analytics/policy-thresholds", headers=_auth(token))
        kpi_low = _data(r).get("kpi_low") or {}
        assert "execution_speed" in kpi_low, f"missing execution_speed: {list(kpi_low.keys())}"
        assert isinstance(kpi_low["execution_speed"], (int, float))

    def test_has_offsets_dict(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/analytics/policy-thresholds", headers=_auth(token))
        assert isinstance(_data(r).get("offsets"), dict)

    def test_default_not_personalized(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/analytics/policy-thresholds", headers=_auth(token))
        d = _data(r)
        assert d.get("is_personalized") is False
        assert d.get("adapted_count") == 0
        assert d.get("last_adapted_at") is None

    def test_has_execution_envelope_in_data(self, client):
        token = _register_and_login(client)
        r = client.get("/apps/analytics/policy-thresholds", headers=_auth(token))
        assert "execution_envelope" in _data(r)

    def test_unauthenticated_returns_401(self, client):
        r = client.get("/apps/analytics/policy-thresholds")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /apps/analytics/policy-thresholds/adapt
# ---------------------------------------------------------------------------

class TestPolicyThresholdsAdapt:

    def test_returns_200(self, client):
        token = _register_and_login(client)
        r = client.post("/apps/analytics/policy-thresholds/adapt", json={}, headers=_auth(token))
        assert r.status_code == 200, r.text[:300]

    def test_unauthenticated_returns_401(self, client):
        r = client.post("/apps/analytics/policy-thresholds/adapt", json={})
        assert r.status_code == 401
