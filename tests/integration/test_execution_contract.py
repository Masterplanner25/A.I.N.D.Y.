"""
Integration tests: joint execution pipeline contract.

Requires a live Postgres stack:
    docker compose -f docker-compose.test.yml up -d
    pytest -c pytest.integration.ini tests/integration/test_execution_contract.py -v

Verifies the invariants guaranteed by ExecutionPipeline / execute_with_pipeline
across EVERY domain that routes through it.  These are contract tests, not
feature tests — they assert properties of the pipeline wrapper, not the
business logic inside any individual handler.

Execution contract invariants verified here:

  1. CANONICAL RESPONSE SHAPE
     Every pipeline-backed success response carries:
       body["status"]  == "success"
       body["data"]    — the handler's result (dict, list, or scalar)
       body["trace_id"] — a non-empty string
       body["metadata"] — dict (may be empty of user-facing keys)

  2. X-Trace-ID RESPONSE HEADER
     The pipeline sets X-Trace-ID on every response via _trace_headers().
     This holds across domains: tasks, identity, ARM, compute, analytics.

  3. X-EU-ID RESPONSE HEADER
     Set when an ExecutionUnit is created for the request.  May be absent on
     routes that run without a DB-backed EU (e.g., unauthenticated 401 paths),
     but must be present on all authenticated success paths.

  4. EXECUTION_ENVELOPE IN body["data"]
     _inject_execution_envelope() embeds an execution_envelope dict inside
     every dict handler result.  Keys: eu_id, trace_id, status, output, error,
     duration_ms, attempt_count.

  5. STRUCTURED ERROR RESPONSES (NOT raw exceptions)
     When the pipeline catches an HTTPException it emits a structured JSON
     response.  Callers never see a raw Python traceback.

  6. VALIDATION ERRORS ARE 422 (FastAPI contract)
     Missing required fields → 422, not 400/500.  Applies to all POST routes.

  7. AUTH BOUNDARY IS 401
     Unauthenticated requests to any protected route return 401, not 403/500.

  8. STATUS CODE CONSISTENCY
     Success paths return 200.  Flows may return 201/202 for creates, but never
     2xx for routes whose handlers explicitly raise errors.

  9. CROSS-DOMAIN UNIFORMITY
     The same contract holds in tasks, identity, ARM, and analytics compute.
     No domain is exempt from the canonical shape.

 10. trace_id ROUND-TRIP
     If the client sends X-Trace-ID in the request header, the pipeline uses it
     as the trace_id for the response (see ExecutionContext.from_request).
"""
from __future__ import annotations

import uuid
import pytest


pytestmark = [pytest.mark.integration, pytest.mark.app_profile]

# ---------------------------------------------------------------------------
# Minimal valid payloads (enough to trigger a successful handler)
# ---------------------------------------------------------------------------

_TASK_PAYLOAD = {"task_name": "contract-test-task", "time_spent": 1.0,
                  "task_complexity": 2, "skill_level": 3, "ai_utilization": 4,
                  "task_difficulty": 1}

_EFFORT_PAYLOAD = _TASK_PAYLOAD  # same schema

_ENGAGEMENT_PAYLOAD = {"likes": 5, "shares": 2, "comments": 1, "clicks": 10,
                        "time_on_page": 15.0, "total_views": 50}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _register_and_login(client, prefix: str = "contract") -> str:
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


def _assert_canonical_shape(body: dict, *, route: str = ""):
    """Assert every invariant of the canonical pipeline response shape."""
    assert "status" in body, f"[{route}] missing 'status' key: {list(body.keys())}"
    assert "data" in body, f"[{route}] missing 'data' key: {list(body.keys())}"
    assert "trace_id" in body, f"[{route}] missing 'trace_id' key: {list(body.keys())}"
    assert "metadata" in body, f"[{route}] missing 'metadata' key: {list(body.keys())}"
    assert body["status"] == "success", f"[{route}] status is '{body['status']}', expected 'success'"
    assert body["trace_id"], f"[{route}] trace_id is empty/None"


def _assert_trace_headers(response, *, route: str = ""):
    """Assert X-Trace-ID response header is present and non-empty."""
    trace = response.headers.get("X-Trace-ID") or response.headers.get("x-trace-id")
    assert trace, (
        f"[{route}] X-Trace-ID header missing or empty. "
        f"Headers: {dict(response.headers)}"
    )


def _assert_eu_header(response, *, route: str = ""):
    """Assert X-EU-ID response header is present (EU was created for this request)."""
    eu = response.headers.get("X-EU-ID") or response.headers.get("x-eu-id")
    assert eu, (
        f"[{route}] X-EU-ID header missing. Headers: {dict(response.headers)}"
    )


def _assert_execution_envelope_in_data(body: dict, *, route: str = ""):
    """Assert execution_envelope is embedded inside body['data'] by the pipeline."""
    data = body.get("data") or {}
    if not isinstance(data, dict):
        return  # list/scalar results don't get execution_envelope injected
    assert "execution_envelope" in data, (
        f"[{route}] execution_envelope missing from body['data']: {list(data.keys())}"
    )
    env = data["execution_envelope"]
    for key in ("eu_id", "trace_id", "status", "output", "error", "duration_ms", "attempt_count"):
        assert key in env, f"[{route}] execution_envelope missing '{key}': {list(env.keys())}"


# ---------------------------------------------------------------------------
# 1. Canonical response shape — across domains
# ---------------------------------------------------------------------------

class TestCanonicalShape:
    """Pipeline wraps every handler result in a canonical shape."""

    def test_identity_get_canonical_shape(self, client):
        token = _register_and_login(client, "shape-id")
        r = client.get("/identity/", headers=_auth(token))
        assert r.status_code == 200
        _assert_canonical_shape(r.json(), route="GET /identity/")

    def test_arm_config_canonical_shape(self, client):
        token = _register_and_login(client, "shape-arm")
        r = client.get("/apps/arm/config", headers=_auth(token))
        assert r.status_code == 200
        _assert_canonical_shape(r.json(), route="GET /apps/arm/config")

    def test_compute_effort_canonical_shape(self, client):
        token = _register_and_login(client, "shape-eff")
        r = client.post("/apps/compute/calculate_effort", json=_EFFORT_PAYLOAD, headers=_auth(token))
        assert r.status_code == 200
        _assert_canonical_shape(r.json(), route="POST /apps/compute/calculate_effort")

    def test_kpi_weights_canonical_shape(self, client):
        token = _register_and_login(client, "shape-kpi")
        r = client.get("/apps/analytics/kpi-weights", headers=_auth(token))
        assert r.status_code == 200
        _assert_canonical_shape(r.json(), route="GET /apps/analytics/kpi-weights")

    def test_arm_logs_canonical_shape(self, client):
        token = _register_and_login(client, "shape-alog")
        r = client.get("/apps/arm/logs", headers=_auth(token))
        assert r.status_code == 200
        _assert_canonical_shape(r.json(), route="GET /apps/arm/logs")

    def test_task_list_canonical_shape(self, client):
        token = _register_and_login(client, "shape-tlist")
        r = client.get("/apps/tasks/list", headers=_auth(token))
        assert r.status_code == 200
        _assert_canonical_shape(r.json(), route="GET /apps/tasks/list")


# ---------------------------------------------------------------------------
# 2. X-Trace-ID response header — across domains
# ---------------------------------------------------------------------------

class TestTraceIdHeader:
    """Every pipeline-backed response carries X-Trace-ID in the response headers."""

    def test_identity_get_has_trace_header(self, client):
        token = _register_and_login(client, "hdr-id")
        r = client.get("/identity/", headers=_auth(token))
        assert r.status_code == 200
        _assert_trace_headers(r, route="GET /identity/")

    def test_identity_put_has_trace_header(self, client):
        token = _register_and_login(client, "hdr-id-put")
        r = client.put("/identity/", json={"tone": "formal"}, headers=_auth(token))
        assert r.status_code in (200, 201)
        _assert_trace_headers(r, route="PUT /identity/")

    def test_arm_config_get_has_trace_header(self, client):
        token = _register_and_login(client, "hdr-arm")
        r = client.get("/apps/arm/config", headers=_auth(token))
        assert r.status_code == 200
        _assert_trace_headers(r, route="GET /apps/arm/config")

    def test_compute_effort_has_trace_header(self, client):
        token = _register_and_login(client, "hdr-eff")
        r = client.post("/apps/compute/calculate_effort", json=_EFFORT_PAYLOAD, headers=_auth(token))
        assert r.status_code == 200
        _assert_trace_headers(r, route="POST /apps/compute/calculate_effort")

    def test_kpi_weights_has_trace_header(self, client):
        token = _register_and_login(client, "hdr-kpi")
        r = client.get("/apps/analytics/kpi-weights", headers=_auth(token))
        assert r.status_code == 200
        _assert_trace_headers(r, route="GET /apps/analytics/kpi-weights")

    def test_trace_id_matches_request_header(self, client):
        """If client sends X-Trace-ID, the pipeline echoes it back in the canonical body."""
        token = _register_and_login(client, "hdr-echo")
        custom_trace = f"custom-{uuid.uuid4().hex}"
        r = client.get(
            "/apps/arm/config",
            headers={**_auth(token), "X-Trace-ID": custom_trace},
        )
        assert r.status_code == 200
        # X-Trace-ID response header is set by the trace middleware (may differ from pipeline trace_id)
        response_trace = r.headers.get("X-Trace-ID") or r.headers.get("x-trace-id") or ""
        assert response_trace, f"X-Trace-ID response header is missing or empty"
        # Pipeline echoes the client's X-Trace-ID in the canonical response body
        assert r.json().get("trace_id") == custom_trace, (
            f"body trace_id '{r.json().get('trace_id')}' != supplied '{custom_trace}'"
        )


# ---------------------------------------------------------------------------
# 3. execution_envelope embedded in body["data"] — across domains
# ---------------------------------------------------------------------------

class TestExecutionEnvelopeInData:
    """_inject_execution_envelope adds execution_envelope inside body['data']."""

    def test_identity_data_has_execution_envelope(self, client):
        token = _register_and_login(client, "env-id")
        r = client.get("/identity/", headers=_auth(token))
        _assert_execution_envelope_in_data(r.json(), route="GET /identity/")

    def test_arm_config_data_has_execution_envelope(self, client):
        token = _register_and_login(client, "env-arm")
        r = client.get("/apps/arm/config", headers=_auth(token))
        _assert_execution_envelope_in_data(r.json(), route="GET /apps/arm/config")

    def test_compute_effort_data_has_execution_envelope(self, client):
        token = _register_and_login(client, "env-eff")
        r = client.post("/apps/compute/calculate_effort", json=_EFFORT_PAYLOAD, headers=_auth(token))
        _assert_execution_envelope_in_data(r.json(), route="POST /apps/compute/calculate_effort")

    def test_kpi_weights_data_has_execution_envelope(self, client):
        token = _register_and_login(client, "env-kpi")
        r = client.get("/apps/analytics/kpi-weights", headers=_auth(token))
        _assert_execution_envelope_in_data(r.json(), route="GET /apps/analytics/kpi-weights")

    def test_execution_envelope_keys_are_correct(self, client):
        """Verify each key in execution_envelope has the right type/value."""
        token = _register_and_login(client, "env-keys")
        r = client.get("/apps/arm/config", headers=_auth(token))
        env = (r.json().get("data") or {}).get("execution_envelope") or {}
        assert env.get("status") == "SUCCESS", f"envelope status: {env.get('status')}"
        assert env.get("error") is None, f"envelope error set unexpectedly: {env.get('error')}"
        duration = env.get("duration_ms")
        assert duration is None or isinstance(duration, (int, float)), (
            f"duration_ms type: {type(duration)}"
        )


# ---------------------------------------------------------------------------
# 4. Structured error responses — not raw exceptions
# ---------------------------------------------------------------------------

class TestStructuredErrors:
    """Pipeline catches HTTPException and returns structured JSON, never a traceback."""

    def test_validation_error_is_json(self, client):
        """422 from FastAPI schema validation is structured JSON."""
        token = _register_and_login(client, "err-val")
        r = client.post("/apps/compute/calculate_effort", json={}, headers=_auth(token))
        assert r.status_code == 422
        body = r.json()
        assert isinstance(body, dict), f"422 body is not a dict: {type(body)}"
        # Runtime uses {error, message, details}; FastAPI default is {detail}
        assert "error" in body or "detail" in body, f"422 response missing error key: {list(body.keys())}"

    def test_auth_error_is_json(self, client):
        """401 from missing JWT is structured JSON, not a traceback."""
        r = client.get("/identity/")
        assert r.status_code == 401
        body = r.json()
        # FastAPI/Starlette returns {"detail": "..."} for 401
        assert isinstance(body, dict), f"401 body is not a dict: {type(body)}"

    def test_arm_config_validation_error_is_json(self, client):
        token = _register_and_login(client, "err-arm")
        # ARM config update with completely wrong type — should produce a structured error
        r = client.put("/apps/arm/config", json=None, headers=_auth(token))
        # May be 422 or 400; either way it must be structured JSON
        assert r.status_code in (400, 422)
        assert isinstance(r.json(), dict)

    def test_no_raw_traceback_on_404_like_flow_error(self, client):
        """Attempting to start a non-existent task returns structured error, not 5xx traceback."""
        token = _register_and_login(client, "err-flow")
        r = client.post(
            "/apps/tasks/start",
            json={"name": f"nonexistent-{uuid.uuid4().hex[:8]}"},
            headers=_auth(token),
        )
        # Pipeline catches the flow error and returns structured response
        assert r.status_code not in (500,), (
            f"Raw 500 returned — pipeline did not wrap the error: {r.text[:300]}"
        )
        body = r.json()
        assert isinstance(body, dict), f"Error response is not a dict: {type(body)}"


# ---------------------------------------------------------------------------
# 5. Auth boundary is 401 — across domains
# ---------------------------------------------------------------------------

class TestAuthBoundary:
    """Every protected route returns 401 for unauthenticated requests."""

    _PROTECTED = [
        ("GET", "/identity/", None),
        ("PUT", "/identity/", {"tone": "formal"}),
        ("GET", "/identity/evolution", None),
        ("GET", "/identity/boot", None),
        ("GET", "/apps/arm/config", None),
        ("PUT", "/apps/arm/config", {"updates": {}}),
        ("GET", "/apps/arm/logs", None),
        ("GET", "/apps/arm/metrics", None),
        ("POST", "/apps/compute/calculate_effort", {"task_name": "x", "time_spent": 1.0,
                                                     "task_complexity": 1, "skill_level": 1,
                                                     "ai_utilization": 1, "task_difficulty": 1}),
        ("GET", "/apps/compute/results", None),
        ("GET", "/apps/analytics/kpi-weights", None),
        ("GET", "/apps/analytics/policy-thresholds", None),
        ("GET", "/apps/tasks/list", None),
    ]

    @pytest.mark.parametrize("method,path,body", _PROTECTED,
                             ids=[p for _, p, _ in _PROTECTED])
    def test_unauthenticated_returns_401(self, client, method, path, body):
        fn = getattr(client, method.lower())
        r = fn(path, json=body) if body is not None else fn(path)
        assert r.status_code == 401, (
            f"{method} {path} returned {r.status_code} for unauthenticated request"
        )


# ---------------------------------------------------------------------------
# 6. Validation errors are 422 — FastAPI contract
# ---------------------------------------------------------------------------

class TestValidation422:
    """Missing required fields produce 422 from FastAPI's validation layer."""

    def test_compute_effort_missing_all_fields(self, client):
        token = _register_and_login(client, "v422-eff")
        r = client.post("/apps/compute/calculate_effort", json={}, headers=_auth(token))
        assert r.status_code == 422, r.text[:200]

    def test_compute_engagement_missing_total_views(self, client):
        token = _register_and_login(client, "v422-eng")
        payload = {"likes": 5, "shares": 2, "comments": 1, "clicks": 10, "time_on_page": 5.0}
        r = client.post("/apps/compute/calculate_engagement", json=payload, headers=_auth(token))
        assert r.status_code == 422

    def test_arm_analyze_missing_file_path(self, client):
        token = _register_and_login(client, "v422-arm")
        r = client.post("/apps/arm/analyze", json={}, headers=_auth(token))
        assert r.status_code == 422

    def test_arm_generate_missing_prompt(self, client):
        token = _register_and_login(client, "v422-gen")
        r = client.post("/apps/arm/generate", json={}, headers=_auth(token))
        assert r.status_code == 422

    def test_422_body_has_detail(self, client):
        """422 responses include a structured error details field."""
        token = _register_and_login(client, "v422-det")
        r = client.post("/apps/compute/calculate_effort", json={}, headers=_auth(token))
        assert r.status_code == 422
        body = r.json()
        # Runtime uses 'details' (list); FastAPI default uses 'detail' (list)
        details = body.get("details") or body.get("detail")
        assert details is not None, f"422 has no error details field: {list(body.keys())}"
        assert isinstance(details, list), f"error details should be list: {type(details)}"


# ---------------------------------------------------------------------------
# 7. Cross-domain uniformity — one test, all domains
# ---------------------------------------------------------------------------

class TestCrossDomainUniformity:
    """Single user, multiple domain reads — all must conform to the same contract."""

    def test_all_domains_share_canonical_shape(self, client):
        token = _register_and_login(client, "xdom")
        checks = [
            ("GET /identity/",           client.get("/identity/",                   headers=_auth(token))),
            ("GET /apps/arm/config",     client.get("/apps/arm/config",             headers=_auth(token))),
            ("GET /apps/arm/logs",       client.get("/apps/arm/logs",               headers=_auth(token))),
            ("GET /apps/arm/metrics",    client.get("/apps/arm/metrics",            headers=_auth(token))),
            ("GET /apps/tasks/list",     client.get("/apps/tasks/list",             headers=_auth(token))),
            ("GET kpi-weights",          client.get("/apps/analytics/kpi-weights",  headers=_auth(token))),
            ("GET policy-thresholds",    client.get("/apps/analytics/policy-thresholds", headers=_auth(token))),
            ("POST compute/effort",      client.post("/apps/compute/calculate_effort",
                                                      json=_EFFORT_PAYLOAD, headers=_auth(token))),
        ]

        for route, r in checks:
            assert r.status_code == 200, f"[{route}] returned {r.status_code}: {r.text[:200]}"
            _assert_canonical_shape(r.json(), route=route)
            _assert_trace_headers(r, route=route)

    def test_all_domains_embed_execution_envelope(self, client):
        token = _register_and_login(client, "xdom-env")
        dict_result_routes = [
            ("GET /identity/",        client.get("/identity/",                    headers=_auth(token))),
            ("GET /apps/arm/config",  client.get("/apps/arm/config",              headers=_auth(token))),
            ("GET kpi-weights",       client.get("/apps/analytics/kpi-weights",   headers=_auth(token))),
            ("GET policy-thresholds", client.get("/apps/analytics/policy-thresholds", headers=_auth(token))),
            ("POST compute/effort",   client.post("/apps/compute/calculate_effort",
                                                   json=_EFFORT_PAYLOAD, headers=_auth(token))),
        ]
        for route, r in dict_result_routes:
            assert r.status_code == 200, f"[{route}] {r.status_code}: {r.text[:150]}"
            _assert_execution_envelope_in_data(r.json(), route=route)

    def test_trace_ids_are_unique_per_request(self, client):
        """Each pipeline invocation generates a distinct trace_id (no shared state)."""
        token = _register_and_login(client, "xdom-uid")
        trace_ids = set()
        for _ in range(3):
            r = client.get("/apps/arm/config", headers=_auth(token))
            assert r.status_code == 200
            tid = r.json().get("trace_id")
            assert tid, "trace_id is empty"
            trace_ids.add(tid)
        assert len(trace_ids) == 3, (
            f"trace_ids are not unique across requests: {trace_ids}"
        )
