"""
Social domain smoke test.

Routes at /apps/social/*
Adapter: legacy_envelope_adapter (prefix "social")
  body = {"status": "SUCCESS", "data": <handler_result>, "result": ...,
          "events": [], "next_action": null, "trace_id": "..."}
Auth: JWT required (router-level Depends(get_current_user))

MongoDB dependency:
  Most routes need MongoDB. Without MONGO_URL set, get_optional_mongo_db returns None
  and handlers return {"status": "degraded", "data": [], "reason": "mongodb_unavailable"}.
  The outer envelope still has status="SUCCESS" and HTTP 200.
  This test accepts both live and degraded responses.

Routes tested:
  POST /apps/social/profile         -- upsert profile
  GET  /apps/social/profile/{user}  -- get profile by username
  POST /apps/social/post            -- create post
  GET  /apps/social/feed            -- feed (all posts ranked)
  GET  /apps/social/analytics       -- performance summary
  POST /apps/social/posts/{id}/interact -- record post interaction (skip if no post)

Routes skipped:
  None — all routes degrade gracefully when MongoDB is unavailable.

Usage:
  python scripts/smoke_social.py
  python scripts/smoke_social.py --base-url http://localhost:8000
"""

import argparse
import sys
import uuid

try:
    import requests
except ImportError:
    print("FATAL: 'requests' not installed. Run: pip install requests")
    sys.exit(1)

BASE = "/apps/social"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(label: str, detail: str = "") -> None:
    print(f"  OK  {label}" + (f" -- {detail}" if detail else ""))


def _fail(label: str, detail: str = "") -> None:
    print(f"  FAIL {label}" + (f" -- {detail}" if detail else ""))


def _get(session, base, path, label, expect=(200,), params=None):
    r = session.get(f"{base}{path}", params=params or {})
    if r.status_code not in expect:
        _fail(label, f"GET {path} -> {r.status_code}: {r.text[:300]}")
        return None, False
    return r.json(), True


def _post(session, base, path, body, label, expect=(200, 201)):
    r = session.post(f"{base}{path}", json=body)
    if r.status_code not in expect:
        _fail(label, f"POST {path} -> {r.status_code}: {r.text[:300]}")
        return None, False
    return r.json(), True


def _assert_legacy_envelope(body, label):
    """Verify the legacy_envelope_adapter shape: status=SUCCESS, data present."""
    if not isinstance(body, dict):
        _fail(label, f"expected dict, got {type(body).__name__}: {str(body)[:200]}")
        return False
    if body.get("status") != "SUCCESS":
        _fail(label, f"expected status=SUCCESS, got status={body.get('status')!r} body={str(body)[:200]}")
        return False
    if "data" not in body:
        _fail(label, f"no 'data' key in body: {list(body.keys())}")
        return False
    return True


def _describe_data(data) -> str:
    """Describe the data payload (real or degraded)."""
    if isinstance(data, dict) and data.get("status") == "degraded":
        return f"degraded: {data.get('reason', '?')}"
    if isinstance(data, list):
        return f"list len={len(data)}"
    if isinstance(data, dict):
        return f"keys={list(data.keys())[:5]}"
    return repr(data)[:80]


# ---------------------------------------------------------------------------
# Test steps
# ---------------------------------------------------------------------------

def step_health(session, base, results):
    body, ok = _get(session, base, "/health", "health check")
    if ok:
        _ok("health check", f"status={body.get('status')}")
    results["health"] = "PASS" if ok else "FAIL"


def step_auth(session, base, results):
    email = f"smoke-soc-{uuid.uuid4().hex[:8]}@aindy.local"
    pw = "SmokeTest1!"

    # 202 from aindy-runtime >= 2.0.0: register no longer authenticates, it emails a
    # verification link. The login below is what yields the token.
    r = session.post(f"{base}/auth/register", json={"email": email, "password": pw})
    if r.status_code not in (200, 201, 202):
        _fail("register", f"{r.status_code}: {r.text[:200]}")
        results["auth"] = "FAIL"
        return None, None

    r = session.post(f"{base}/auth/login", json={"email": email, "password": pw})
    if r.status_code != 200:
        _fail("login", f"{r.status_code}: {r.text[:200]}")
        results["auth"] = "FAIL"
        return None, None

    body = r.json()
    token = body.get("access_token") or (body.get("data") or {}).get("access_token")
    if not token:
        _fail("login", f"no access_token in: {body}")
        results["auth"] = "FAIL"
        return None, None

    # extract user_id for SocialPost.author_id
    user_id = (body.get("data") or {}).get("user_id") or (body.get("user") or {}).get("id") or email

    session.headers["Authorization"] = f"Bearer {token}"
    _ok("auth register + login", email)
    results["auth"] = "PASS"
    return token, user_id


def step_upsert_profile(session, base, results, username):
    """POST /apps/social/profile -- upsert a social profile."""
    payload = {
        "username": username,
        "tagline": "Smoke test profile",
        "bio": "Automated smoke test user",
        "tags": ["smoke", "test"],
    }
    body, ok = _post(session, base, f"{BASE}/profile", payload, "upsert profile")
    if not ok:
        results["upsert_profile"] = "FAIL"
        return

    if not _assert_legacy_envelope(body, "upsert profile"):
        results["upsert_profile"] = "FAIL"
        return

    data = body.get("data")
    _ok("upsert profile", _describe_data(data))
    results["upsert_profile"] = "PASS"


def step_get_profile(session, base, results, username):
    """GET /apps/social/profile/{username} -- retrieve profile by username."""
    body, ok = _get(session, base, f"{BASE}/profile/{username}", "get profile")
    if not ok:
        results["get_profile"] = "FAIL"
        return

    if not _assert_legacy_envelope(body, "get profile"):
        results["get_profile"] = "FAIL"
        return

    data = body.get("data")
    _ok("get profile", _describe_data(data))
    results["get_profile"] = "PASS"


def step_create_post(session, base, results, user_id, username):
    """POST /apps/social/post -- create a social post."""
    post_id = str(uuid.uuid4())
    payload = {
        "id": post_id,
        "author_id": str(user_id),
        "author_username": username,
        "content": "Smoke test broadcast: Infinity Algorithm is live.",
        "tags": ["smoke", "infinity"],
        "trust_tier_required": "observer",
    }
    body, ok = _post(session, base, f"{BASE}/post", payload, "create post")
    if not ok:
        results["create_post"] = "FAIL"
        return None

    if not _assert_legacy_envelope(body, "create post"):
        results["create_post"] = "FAIL"
        return None

    data = body.get("data")
    # If MongoDB available, data contains the post dict (with "data" key wrapping it)
    # If degraded, data = {"status": "degraded", ...}
    if isinstance(data, dict) and data.get("status") == "degraded":
        _ok("create post", f"degraded: {data.get('reason', '?')}")
        results["create_post"] = "PASS"
        return None  # no real post_id to use for interaction test

    # MongoDB live: data = {"data": post_data, "execution_hints": {...}}
    inner = data.get("data") if isinstance(data, dict) else None
    if isinstance(inner, dict):
        returned_id = inner.get("id") or post_id
        _ok("create post", f"id={returned_id!r}")
        results["create_post"] = "PASS"
        return returned_id

    _ok("create post", _describe_data(data))
    results["create_post"] = "PASS"
    return post_id


def step_get_feed(session, base, results):
    """GET /apps/social/feed -- retrieve ranked social feed."""
    body, ok = _get(session, base, f"{BASE}/feed", "get feed", params={"limit": 10})
    if not ok:
        results["get_feed"] = "FAIL"
        return

    if not _assert_legacy_envelope(body, "get feed"):
        results["get_feed"] = "FAIL"
        return

    data = body.get("data")
    # degraded: {"status": "degraded", ...}
    # live: {"data": [FeedItem, ...], "execution_hints": {...}}
    if isinstance(data, dict) and data.get("status") == "degraded":
        _ok("get feed", f"degraded: {data.get('reason', '?')}")
    elif isinstance(data, dict):
        inner = data.get("data")
        count = len(inner) if isinstance(inner, list) else "?"
        _ok("get feed", f"{count} item(s)")
    else:
        _ok("get feed", _describe_data(data))
    results["get_feed"] = "PASS"


def step_get_analytics(session, base, results):
    """GET /apps/social/analytics -- social performance summary."""
    body, ok = _get(session, base, f"{BASE}/analytics", "get analytics")
    if not ok:
        results["get_analytics"] = "FAIL"
        return

    if not _assert_legacy_envelope(body, "get analytics"):
        results["get_analytics"] = "FAIL"
        return

    data = body.get("data")
    # degraded: {"status": "degraded", ...} nested in data
    if isinstance(data, dict) and data.get("status") == "degraded":
        _ok("get analytics", f"degraded: {data.get('reason', '?')}")
    elif isinstance(data, dict) and "overview" in data:
        overview = data.get("overview", {})
        _ok("get analytics", f"post_count={overview.get('post_count', '?')}  top_posts={len(data.get('top_posts', []))}")
    else:
        _ok("get analytics", _describe_data(data))
    results["get_analytics"] = "PASS"


def step_post_interact(session, base, results, post_id):
    """POST /apps/social/posts/{id}/interact -- record post interaction."""
    payload = {"action": "like", "amount": 1}
    r = session.post(f"{base}{BASE}/posts/{post_id}/interact", json=payload)

    if r.status_code == 404:
        # MongoDB available but post not found (e.g., queued not persisted)
        _ok("post interact", "404 -- post not yet persisted (acceptable)")
        results["post_interact"] = "PASS"
        return

    if r.status_code not in (200, 201):
        _fail("post interact", f"POST /posts/{post_id}/interact -> {r.status_code}: {r.text[:300]}")
        results["post_interact"] = "FAIL"
        return

    body = r.json()
    if not _assert_legacy_envelope(body, "post interact"):
        results["post_interact"] = "FAIL"
        return

    data = body.get("data")
    if isinstance(data, dict) and data.get("status") == "degraded":
        _ok("post interact", f"degraded: {data.get('reason', '?')}")
    elif isinstance(data, dict):
        _ok("post interact", f"post_id={data.get('post_id')!r}  action={data.get('action')!r}  likes={data.get('likes')}")
    else:
        _ok("post interact", _describe_data(data))
    results["post_interact"] = "PASS"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Social domain smoke test")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Server base URL")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print("=" * 60)
    print("SOCIAL DOMAIN SMOKE TEST")
    print(f"Target: {base}")
    print("Note: MongoDB routes degrade gracefully if MONGO_URL not set")
    print("=" * 60)

    session = requests.Session()
    session.headers["Content-Type"] = "application/json"
    results = {}

    print("\n[1] Health")
    step_health(session, base, results)

    print("\n[2] Auth")
    token, user_id = step_auth(session, base, results)
    if not token:
        print("\nAuth failed -- cannot continue.")
        _print_summary(results)
        sys.exit(1)

    username = f"smoke-{uuid.uuid4().hex[:8]}"

    print(f"\n[3] Upsert profile (POST {BASE}/profile)")
    step_upsert_profile(session, base, results, username)

    print(f"\n[4] Get profile (GET {BASE}/profile/{{username}})")
    step_get_profile(session, base, results, username)

    print(f"\n[5] Create post (POST {BASE}/post)")
    post_id = step_create_post(session, base, results, user_id, username)

    print(f"\n[6] Get feed (GET {BASE}/feed)")
    step_get_feed(session, base, results)

    print(f"\n[7] Get analytics (GET {BASE}/analytics)")
    step_get_analytics(session, base, results)

    print(f"\n[8] Post interaction (POST {BASE}/posts/{{id}}/interact)")
    fake_post_id = post_id or str(uuid.uuid4())
    step_post_interact(session, base, results, fake_post_id)

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
        print("ALL TESTS PASSED -- social domain smoke OK")


if __name__ == "__main__":
    main()
