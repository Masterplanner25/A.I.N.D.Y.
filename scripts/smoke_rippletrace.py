"""
RippleTrace domain smoke test.

Tests the JWT-authenticated /apps/rippletrace/* surface only.
Skips the legacy API-key surface (/analyze_ripple/*, /dashboard, etc.)
which requires a separate API key credential.

Covers:
  POST /apps/rippletrace/drop_point     — create a drop point
  GET  /apps/rippletrace/drop_points    — list all drop points (body = JSON array)
  POST /apps/rippletrace/ping           — create a ping for the drop point
  GET  /apps/rippletrace/pings          — list all pings (body = JSON array)
  GET  /apps/rippletrace/ripples/{id}   — ripples for a specific drop point
  GET  /apps/rippletrace/recent         — recent ripple events (JSON array)
  POST /apps/rippletrace/event          — log a symbolic ripple event
  GET  /apps/rippletrace/causal/graph   — causal graph (empty OK, accept any 200)
  GET  /apps/rippletrace/narrative/summary  — narrative summary (empty OK)
  GET  /apps/rippletrace/predictions/summary — predictions summary (empty OK)
  GET  /apps/rippletrace/learning/stats     — learning stats (any 200)
  GET  /apps/rippletrace/strategies         — strategy list (empty OK)

Adapter: all routes use raw_json_adapter (prefix "rippletrace").
  body = jsonable_encoder(handler_return_value)
  List-returning handlers → bare JSON array in body.
  Single-object handlers → flat dict in body.

Usage:
  python scripts/smoke_rippletrace.py
  python scripts/smoke_rippletrace.py --base-url http://localhost:8000
"""

import argparse
import sys
import uuid

try:
    import requests
except ImportError:
    print("FATAL: 'requests' not installed. Run: pip install requests")
    sys.exit(1)


BASE = "/apps/rippletrace"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(label: str, detail: str = "") -> None:
    print(f"  OK  {label}" + (f" -- {detail}" if detail else ""))


def _fail(label: str, detail: str = "") -> None:
    print(f"  FAIL {label}" + (f" -- {detail}" if detail else ""))


def _get(session, base, path, label, expect=200):
    r = session.get(f"{base}{path}")
    if r.status_code != expect:
        _fail(label, f"GET {path} -> {r.status_code}: {r.text[:300]}")
        return None, False
    return r.json(), True


def _post(session, base, path, body, label, expect=(200, 201)):
    r = session.post(f"{base}{path}", json=body)
    if r.status_code not in expect:
        _fail(label, f"POST {path} -> {r.status_code}: {r.text[:300]}")
        return None, False
    return r.json(), True


# ---------------------------------------------------------------------------
# Test steps
# ---------------------------------------------------------------------------

def step_health(session, base, results):
    body, ok = _get(session, base, "/health", "health check")
    if ok:
        _ok("health check", f"status={body.get('status')}")
    results["health"] = "PASS" if ok else "FAIL"


def step_auth(session, base, results):
    email = f"smoke-rt-{uuid.uuid4().hex[:8]}@aindy.local"
    pw = "SmokeTest1!"

    # 202 from aindy-runtime >= 2.0.0: register no longer authenticates, it emails a
    # verification link. The login below is what yields the token.
    _, ok = _post(
        session, base, "/auth/register", {"email": email, "password": pw}, "register",
        expect=(200, 201, 202),
    )
    if not ok:
        results["auth"] = "FAIL"
        return None

    body, ok = _post(session, base, "/auth/login", {"email": email, "password": pw}, "login")
    if not ok:
        results["auth"] = "FAIL"
        return None

    token = body.get("access_token") or (body.get("data") or {}).get("access_token")
    if not token:
        _fail("login", f"no access_token in: {body}")
        results["auth"] = "FAIL"
        return None

    session.headers["Authorization"] = f"Bearer {token}"
    _ok("auth register + login", email)
    results["auth"] = "PASS"
    return token


def step_create_drop_point(session, base, results):
    """POST /apps/rippletrace/drop_point — body = flat drop-point dict."""
    dp_id = f"smoke-dp-{uuid.uuid4().hex[:8]}"
    payload = {
        "id": dp_id,
        "title": "Smoke Test Drop Point",
        "platform": "smoke",
        "url": None,
        "date_dropped": None,
        "core_themes": ["testing", "smoke"],
        "tagged_entities": ["aindy", "rippletrace"],
        "intent": "validate smoke test coverage",
    }
    body, ok = _post(session, base, f"{BASE}/drop_point", payload, "create drop point")
    if not ok:
        results["create_drop_point"] = "FAIL"
        return None

    # body = jsonable_encoder(DropPointDB) → flat dict or {"data": {...}}
    got_id = body.get("id") if isinstance(body, dict) else None
    if not got_id:
        _fail("create drop point", f"no 'id' in body: {list(body.keys()) if isinstance(body, dict) else type(body)}")
        results["create_drop_point"] = "FAIL"
        return None

    _ok("create drop point", f"id={got_id}  title={body.get('title')!r}")
    results["create_drop_point"] = "PASS"
    return got_id


def step_list_drop_points(session, base, dp_id, results):
    """GET /apps/rippletrace/drop_points — body = JSON array of drop-point dicts."""
    body, ok = _get(session, base, f"{BASE}/drop_points", "list drop points")
    if not ok:
        results["list_drop_points"] = "FAIL"
        return

    if not isinstance(body, list):
        _fail("list drop points", f"expected list, got {type(body).__name__}: {str(body)[:200]}")
        results["list_drop_points"] = "FAIL"
        return

    found = any(str(dp.get("id")) == dp_id for dp in body if isinstance(dp, dict))
    if not found:
        _fail("list drop points", f"created id={dp_id} not in {len(body)} drop points")
        results["list_drop_points"] = "FAIL"
        return

    _ok("list drop points", f"{len(body)} drop point(s), created one present")
    results["list_drop_points"] = "PASS"


def step_create_ping(session, base, dp_id, results):
    """POST /apps/rippletrace/ping — body = flat ping dict."""
    ping_id = f"smoke-pg-{uuid.uuid4().hex[:8]}"
    payload = {
        "id": ping_id,
        "drop_point_id": dp_id,
        "ping_type": "mention",
        "source_platform": "smoke_test",
        "date_detected": None,
        "connection_summary": "smoke test ping connection",
        "external_url": None,
        "reaction_notes": None,
        "strength": 1.0,
    }
    body, ok = _post(session, base, f"{BASE}/ping", payload, "create ping")
    if not ok:
        results["create_ping"] = "FAIL"
        return None

    got_id = body.get("id") if isinstance(body, dict) else None
    if not got_id:
        _fail("create ping", f"no 'id' in body: {list(body.keys()) if isinstance(body, dict) else type(body)}")
        results["create_ping"] = "FAIL"
        return None

    _ok("create ping", f"id={got_id}  drop_point_id={body.get('drop_point_id')}")
    results["create_ping"] = "PASS"
    return ping_id


def step_list_pings(session, base, ping_id, results):
    """GET /apps/rippletrace/pings — body = JSON array of ping dicts."""
    body, ok = _get(session, base, f"{BASE}/pings", "list pings")
    if not ok:
        results["list_pings"] = "FAIL"
        return

    if not isinstance(body, list):
        _fail("list pings", f"expected list, got {type(body).__name__}: {str(body)[:200]}")
        results["list_pings"] = "FAIL"
        return

    found = any(str(pg.get("id")) == ping_id for pg in body if isinstance(pg, dict))
    if not found:
        _fail("list pings", f"created ping_id={ping_id} not in {len(body)} pings")
        results["list_pings"] = "FAIL"
        return

    _ok("list pings", f"{len(body)} ping(s), created one present")
    results["list_pings"] = "PASS"


def step_ripples(session, base, dp_id, results):
    """GET /apps/rippletrace/ripples/{dp_id} — body = JSON array of pings for that drop point."""
    body, ok = _get(session, base, f"{BASE}/ripples/{dp_id}", "ripples for drop point")
    if not ok:
        results["ripples"] = "FAIL"
        return

    if not isinstance(body, list):
        _fail("ripples for drop point", f"expected list, got {type(body).__name__}: {str(body)[:200]}")
        results["ripples"] = "FAIL"
        return

    _ok("ripples for drop point", f"{len(body)} ping(s) for dp_id={dp_id}")
    results["ripples"] = "PASS"


def step_recent(session, base, results):
    """GET /apps/rippletrace/recent — body = JSON array of recent pings."""
    body, ok = _get(session, base, f"{BASE}/recent", "recent ripples")
    if not ok:
        results["recent"] = "FAIL"
        return

    if not isinstance(body, list):
        _fail("recent ripples", f"expected list, got {type(body).__name__}: {str(body)[:200]}")
        results["recent"] = "FAIL"
        return

    _ok("recent ripples", f"{len(body)} recent ping(s)")
    results["recent"] = "PASS"


def step_log_event(session, base, results):
    """POST /apps/rippletrace/event — log a symbolic ripple event."""
    payload = {
        "ping_type": "smoke_event",
        "source_platform": "smoke_test",
        "summary": "smoke test event log",
        "url": None,
        "notes": "automated smoke test",
        "drop_point_id": "bridge",
    }
    body, ok = _post(session, base, f"{BASE}/event", payload, "log ripple event")
    if not ok:
        results["log_event"] = "FAIL"
        return

    # Handler returns {"data": {"status": "logged", "event": {...}}, "execution_signals": {...}}
    # raw_json_adapter → body = that whole dict
    # The inner "data" key holds the actual result, or "status" may be at top level
    if isinstance(body, dict):
        logged_ok = (
            body.get("status") == "logged"
            or (body.get("data") or {}).get("status") == "logged"
        )
        _ok("log ripple event", f"logged_ok={logged_ok}  keys={list(body.keys())}")
    else:
        _ok("log ripple event", f"type={type(body).__name__}")
    results["log_event"] = "PASS"


def step_causal_graph(session, base, results):
    """GET /apps/rippletrace/causal/graph — accept any 200."""
    body, ok = _get(session, base, f"{BASE}/causal/graph", "causal graph")
    if not ok:
        results["causal_graph"] = "FAIL"
        return

    keys = list(body.keys()) if isinstance(body, dict) else f"list[{len(body)}]" if isinstance(body, list) else type(body).__name__
    _ok("causal graph", f"keys={keys}")
    results["causal_graph"] = "PASS"


def step_narrative_summary(session, base, results):
    """GET /apps/rippletrace/narrative/summary — accept any 200."""
    body, ok = _get(session, base, f"{BASE}/narrative/summary", "narrative summary")
    if not ok:
        results["narrative_summary"] = "FAIL"
        return

    keys = list(body.keys()) if isinstance(body, dict) else f"list[{len(body)}]" if isinstance(body, list) else type(body).__name__
    _ok("narrative summary", f"keys={keys}")
    results["narrative_summary"] = "PASS"


def step_predictions_summary(session, base, results):
    """GET /apps/rippletrace/predictions/summary — accept any 200."""
    body, ok = _get(session, base, f"{BASE}/predictions/summary", "predictions summary")
    if not ok:
        results["predictions_summary"] = "FAIL"
        return

    keys = list(body.keys()) if isinstance(body, dict) else f"list[{len(body)}]" if isinstance(body, list) else type(body).__name__
    _ok("predictions summary", f"keys={keys}")
    results["predictions_summary"] = "PASS"


def step_learning_stats(session, base, results):
    """GET /apps/rippletrace/learning/stats — accept any 200."""
    body, ok = _get(session, base, f"{BASE}/learning/stats", "learning stats")
    if not ok:
        results["learning_stats"] = "FAIL"
        return

    keys = list(body.keys()) if isinstance(body, dict) else f"list[{len(body)}]" if isinstance(body, list) else type(body).__name__
    _ok("learning stats", f"keys={keys}")
    results["learning_stats"] = "PASS"


def step_strategies_list(session, base, results):
    """GET /apps/rippletrace/strategies — accept any 200."""
    body, ok = _get(session, base, f"{BASE}/strategies", "strategies list")
    if not ok:
        results["strategies_list"] = "FAIL"
        return

    count = len(body) if isinstance(body, list) else (len(body.get("strategies") or []) if isinstance(body, dict) else "?")
    _ok("strategies list", f"count={count}")
    results["strategies_list"] = "PASS"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="RippleTrace domain smoke test")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Server base URL")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print("=" * 60)
    print("RIPPLETRACE DOMAIN SMOKE TEST")
    print(f"Target: {base}")
    print("Note: JWT surface only — legacy API-key routes not tested")
    print("=" * 60)

    session = requests.Session()
    session.headers["Content-Type"] = "application/json"
    results = {}

    print("\n[1] Health")
    step_health(session, base, results)

    print("\n[2] Auth")
    token = step_auth(session, base, results)
    if not token:
        print("\nAuth failed — cannot continue.")
        _print_summary(results)
        sys.exit(1)

    print("\n[3] Create drop point (POST /apps/rippletrace/drop_point)")
    dp_id = step_create_drop_point(session, base, results)

    print("\n[4] List drop points (GET /apps/rippletrace/drop_points)")
    if dp_id:
        step_list_drop_points(session, base, dp_id, results)
    else:
        results["list_drop_points"] = "SKIP"

    print("\n[5] Create ping (POST /apps/rippletrace/ping)")
    if dp_id:
        ping_id = step_create_ping(session, base, dp_id, results)
    else:
        ping_id = None
        results["create_ping"] = "SKIP"

    print("\n[6] List pings (GET /apps/rippletrace/pings)")
    if ping_id:
        step_list_pings(session, base, ping_id, results)
    else:
        results["list_pings"] = "SKIP"

    print("\n[7] Ripples for drop point (GET /apps/rippletrace/ripples/{id})")
    if dp_id:
        step_ripples(session, base, dp_id, results)
    else:
        results["ripples"] = "SKIP"

    print("\n[8] Recent ripples (GET /apps/rippletrace/recent)")
    step_recent(session, base, results)

    print("\n[9] Log ripple event (POST /apps/rippletrace/event)")
    step_log_event(session, base, results)

    print("\n[10] Causal graph (GET /apps/rippletrace/causal/graph)")
    step_causal_graph(session, base, results)

    print("\n[11] Narrative summary (GET /apps/rippletrace/narrative/summary)")
    step_narrative_summary(session, base, results)

    print("\n[12] Predictions summary (GET /apps/rippletrace/predictions/summary)")
    step_predictions_summary(session, base, results)

    print("\n[13] Learning stats (GET /apps/rippletrace/learning/stats)")
    step_learning_stats(session, base, results)

    print("\n[14] Strategies list (GET /apps/rippletrace/strategies)")
    step_strategies_list(session, base, results)

    _print_summary(results)

    failed = [k for k, v in results.items() if v == "FAIL"]
    sys.exit(1 if failed else 0)


def _print_summary(results):
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    icons = {"PASS": "OK", "FAIL": "FAIL", "SKIP": "--"}
    for name, result in results.items():
        icon = icons.get(result, "??")
        print(f"  {icon}  {name}: {result}")
    print()
    failed = [k for k, v in results.items() if v == "FAIL"]
    if failed:
        print(f"FAILED: {', '.join(failed)}")
    else:
        print("ALL TESTS PASSED -- rippletrace domain smoke OK")


if __name__ == "__main__":
    main()
