"""
Search domain smoke test.

Four routers registered under /apps/*:
  /apps/seo/*            -- SEORouter (raw_json_adapter)
  /apps/leadgen/*        -- LeadGenRouter (raw_json_adapter, return_result=True bypasses it)
  /apps/research/*       -- ResearchRouter (no adapter, return_result=True)
  /apps/search/*         -- SearchHistoryRouter (no adapter, return_result=True)

All routes require JWT auth.

Response shapes:
  POST /apps/seo/*             body = handler return dict (raw_json_adapter extracts canonical.data)
  GET  /apps/leadgen/          body = list (empty for fresh user)
  GET  /apps/research/         body = list (empty for fresh user)
  POST /apps/research/         body = {id, query, summary, ..., execution_envelope}  (201)
  GET  /apps/search/history    body = {count, items, execution_envelope}
  GET  /apps/search/history/{id}   body = {id, query, result, ..., execution_envelope}
  DELETE /apps/search/history/{id} body = {status, id, execution_envelope}

Routes tested:
  POST /apps/seo/analyze      -- SEO analysis (NLTK + textstat, no LLM)
  POST /apps/seo/meta         -- meta description (pure Python)
  POST /apps/seo/suggest      -- SEO improvement suggestions (pure Python)
  GET  /apps/leadgen/         -- list all leads (empty for fresh user, no LLM)
  GET  /apps/research/        -- list research results (empty for fresh user, no LLM)
  POST /apps/research/        -- create research result (DB write, no LLM)
  GET  /apps/search/history   -- list search history (populated by SEO steps above)
  GET  /apps/search/history/{id}   -- get specific history item
  DELETE /apps/search/history/{id} -- delete history item
  GET  /apps/search/history/{id}   -- verify 404 after delete

Routes skipped:
  POST /apps/leadgen/          -- requires GPT-4o-mini for lead scoring
  GET  /apps/leadgen/search    -- calls Perplexity API (external, may hang without key)
  POST /apps/research/query    -- requires web_search + GPT-4o

Note: POST /apps/seo/analyze and /seo/meta call execute_durable_search which persists
SearchHistory rows. These appear in GET /apps/search/history.

Usage:
  python scripts/smoke_search.py
  python scripts/smoke_search.py --base-url http://localhost:8000
"""

import argparse
import sys
import uuid

try:
    import requests
except ImportError:
    print("FATAL: 'requests' not installed. Run: pip install requests")
    sys.exit(1)


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


def _delete(session, base, path, label, expect=(200,)):
    r = session.delete(f"{base}{path}")
    if r.status_code not in expect:
        _fail(label, f"DELETE {path} -> {r.status_code}: {r.text[:300]}")
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
    email = f"smoke-srch-{uuid.uuid4().hex[:8]}@aindy.local"
    pw = "SmokeTest1!"

    # 202 from aindy-runtime >= 2.0.0: register no longer authenticates, it emails a
    # verification link. The login below is what yields the token.
    r = session.post(f"{base}/auth/register", json={"email": email, "password": pw})
    if r.status_code not in (200, 201, 202):
        _fail("register", f"{r.status_code}: {r.text[:200]}")
        results["auth"] = "FAIL"
        return None

    r = session.post(f"{base}/auth/login", json={"email": email, "password": pw})
    if r.status_code != 200:
        _fail("login", f"{r.status_code}: {r.text[:200]}")
        results["auth"] = "FAIL"
        return None

    body = r.json()
    token = body.get("access_token") or (body.get("data") or {}).get("access_token")
    if not token:
        _fail("login", f"no access_token in: {body}")
        results["auth"] = "FAIL"
        return None

    session.headers["Authorization"] = f"Bearer {token}"
    _ok("auth register + login", email)
    results["auth"] = "PASS"
    return token


def step_seo_analyze(session, base, results):
    """POST /apps/seo/analyze -- pure Python NLP; body = handler dict directly."""
    sample = (
        "The Infinity Algorithm is an advanced AI framework built to automate "
        "strategic business decisions. It combines symbolic reasoning, neural "
        "search optimization, and autonomous agent orchestration to help founders "
        "move faster and smarter."
    )
    body, ok = _post(
        session, base, "/apps/seo/analyze",
        {"text": sample, "top_n": 5},
        "SEO analyze",
    )
    if not ok:
        results["seo_analyze"] = "FAIL"
        return

    if not isinstance(body, dict):
        _fail("SEO analyze", f"expected dict, got {type(body).__name__}: {str(body)[:200]}")
        results["seo_analyze"] = "FAIL"
        return

    word_count = body.get("word_count")
    readability = body.get("readability")
    top_keywords = body.get("top_keywords")

    if word_count is None:
        _fail("SEO analyze", f"no 'word_count' in body: {list(body.keys())}")
        results["seo_analyze"] = "FAIL"
        return

    _ok("SEO analyze", f"word_count={word_count}  readability={readability}  keywords={top_keywords[:3] if isinstance(top_keywords, list) else top_keywords!r}")
    results["seo_analyze"] = "PASS"


def step_seo_meta(session, base, results):
    """POST /apps/seo/meta -- pure Python; body = {meta_description, ...}."""
    body, ok = _post(
        session, base, "/apps/seo/meta",
        {"text": "A.I.N.D.Y. is the world's first autonomous AI runtime for the Infinity Algorithm.", "limit": 160},
        "SEO meta",
    )
    if not ok:
        results["seo_meta"] = "FAIL"
        return

    if not isinstance(body, dict):
        _fail("SEO meta", f"expected dict, got {type(body).__name__}: {str(body)[:200]}")
        results["seo_meta"] = "FAIL"
        return

    meta_desc = body.get("meta_description")
    if meta_desc is None:
        _fail("SEO meta", f"no 'meta_description' in body: {list(body.keys())}")
        results["seo_meta"] = "FAIL"
        return

    _ok("SEO meta", f"meta_description len={len(meta_desc)!r}")
    results["seo_meta"] = "PASS"


def step_seo_suggest(session, base, results):
    """POST /apps/seo/suggest -- pure Python; body = {seo_suggestions, learning_context}."""
    body, ok = _post(
        session, base, "/apps/seo/suggest",
        {"text": "Build faster. Ship better. Win bigger. AI for founders.", "top_n": 5},
        "SEO suggest",
    )
    if not ok:
        results["seo_suggest"] = "FAIL"
        return

    if not isinstance(body, dict):
        _fail("SEO suggest", f"expected dict, got {type(body).__name__}: {str(body)[:200]}")
        results["seo_suggest"] = "FAIL"
        return

    suggestions = body.get("seo_suggestions")
    if suggestions is None:
        _fail("SEO suggest", f"no 'seo_suggestions' in body: {list(body.keys())}")
        results["seo_suggest"] = "FAIL"
        return

    _ok("SEO suggest", f"seo_suggestions len={len(suggestions)}")
    results["seo_suggest"] = "PASS"


def step_leadgen_list(session, base, results):
    """GET /apps/leadgen/ -- list leads; empty for fresh user; body = list."""
    body, ok = _get(session, base, "/apps/leadgen/", "list leads")
    if not ok:
        results["leadgen_list"] = "FAIL"
        return

    if not isinstance(body, list):
        _fail("list leads", f"expected list, got {type(body).__name__}: {str(body)[:200]}")
        results["leadgen_list"] = "FAIL"
        return

    _ok("list leads", f"count={len(body)}  (empty OK for fresh user)")
    results["leadgen_list"] = "PASS"


def step_research_list(session, base, results):
    """GET /apps/research/ -- list research results; empty for fresh user; body = list."""
    body, ok = _get(session, base, "/apps/research/", "list research results")
    if not ok:
        results["research_list"] = "FAIL"
        return

    if not isinstance(body, list):
        _fail("list research results", f"expected list, got {type(body).__name__}: {str(body)[:200]}")
        results["research_list"] = "FAIL"
        return

    _ok("list research results", f"count={len(body)}  (empty OK for fresh user)")
    results["research_list"] = "PASS"


def step_research_create(session, base, results):
    """POST /apps/research/ -- create research result (DB write, no LLM).
    Returns: {id, query, summary, source, data, created_at, search_score, execution_envelope} (HTTP 201)."""
    body, ok = _post(
        session, base, "/apps/research/",
        {"query": "Infinity Algorithm automation", "summary": "Smoke test research summary"},
        "create research result",
        expect=(200, 201),
    )
    if not ok:
        results["research_create"] = "FAIL"
        return

    if not isinstance(body, dict):
        _fail("create research result", f"expected dict, got {type(body).__name__}: {str(body)[:200]}")
        results["research_create"] = "FAIL"
        return

    record_id = body.get("id")
    query_val = body.get("query")

    if record_id is None:
        _fail("create research result", f"no 'id' in body: {list(body.keys())}")
        results["research_create"] = "FAIL"
        return

    _ok("create research result", f"id={record_id}  query={query_val!r}")
    results["research_create"] = "PASS"


def step_search_history_list(session, base, results):
    """GET /apps/search/history -- list search history.
    Body = {count, items, execution_envelope}.
    SEO analyze/meta steps above call execute_durable_search -> persist_search_result,
    so there should be at least 2 items in history by now."""
    body, ok = _get(session, base, "/apps/search/history", "list search history")
    if not ok:
        results["search_history_list"] = "FAIL"
        return None

    if not isinstance(body, dict):
        _fail("list search history", f"expected dict, got {type(body).__name__}: {str(body)[:200]}")
        results["search_history_list"] = "FAIL"
        return None

    count = body.get("count")
    items = body.get("items")

    if items is None:
        _fail("list search history", f"no 'items' in body: {list(body.keys())}")
        results["search_history_list"] = "FAIL"
        return None

    if not isinstance(items, list):
        _fail("list search history", f"'items' is {type(items).__name__}, expected list")
        results["search_history_list"] = "FAIL"
        return None

    _ok("list search history", f"count={count}  items_len={len(items)}")
    results["search_history_list"] = "PASS"

    # Return first history_id for use in next steps
    if items:
        return items[0].get("id")
    return None


def step_search_history_get(session, base, results, history_id):
    """GET /apps/search/history/{id} -- get specific history item.
    Body = {id, query, result, search_type, created_at, execution_envelope}."""
    body, ok = _get(session, base, f"/apps/search/history/{history_id}", "get search history item")
    if not ok:
        results["search_history_get"] = "FAIL"
        return

    if not isinstance(body, dict):
        _fail("get search history item", f"expected dict, got {type(body).__name__}: {str(body)[:200]}")
        results["search_history_get"] = "FAIL"
        return

    item_id = body.get("id")
    if item_id is None:
        _fail("get search history item", f"no 'id' in body: {list(body.keys())}")
        results["search_history_get"] = "FAIL"
        return

    _ok("get search history item", f"id={item_id}  query={body.get('query')!r}")
    results["search_history_get"] = "PASS"


def step_search_history_delete(session, base, results, history_id):
    """DELETE /apps/search/history/{id} -- delete history item.
    Body = {status: 'deleted', id, execution_envelope}."""
    body, ok = _delete(session, base, f"/apps/search/history/{history_id}", "delete search history item")
    if not ok:
        results["search_history_delete"] = "FAIL"
        return

    if not isinstance(body, dict):
        _fail("delete search history item", f"expected dict, got {type(body).__name__}: {str(body)[:200]}")
        results["search_history_delete"] = "FAIL"
        return

    status_val = body.get("status")
    if status_val != "deleted":
        _fail("delete search history item", f"expected status='deleted', got {status_val!r}: {list(body.keys())}")
        results["search_history_delete"] = "FAIL"
        return

    _ok("delete search history item", f"id={body.get('id')}  status={status_val!r}")
    results["search_history_delete"] = "PASS"


def step_search_history_get_404(session, base, results, history_id):
    """GET /apps/search/history/{id} after delete -- should 404."""
    body, ok = _get(
        session, base, f"/apps/search/history/{history_id}",
        "get deleted history item (expect 404)",
        expect=(404,),
    )
    if not ok:
        results["search_history_get_404"] = "FAIL"
        return

    _ok("get deleted history item", f"404 as expected for id={str(history_id)[:8]}...")
    results["search_history_get_404"] = "PASS"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Search domain smoke test")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Server base URL")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print("=" * 60)
    print("SEARCH DOMAIN SMOKE TEST")
    print(f"Target: {base}")
    print("Skipping: POST /leadgen/ (GPT-4o-mini), GET /leadgen/search (Perplexity), POST /research/query (LLM)")
    print("=" * 60)

    session = requests.Session()
    session.headers["Content-Type"] = "application/json"
    results = {}

    print("\n[1] Health")
    step_health(session, base, results)

    print("\n[2] Auth")
    token = step_auth(session, base, results)
    if not token:
        print("\nAuth failed -- cannot continue.")
        _print_summary(results)
        sys.exit(1)

    print("\n[3] SEO analyze (POST /apps/seo/analyze)")
    step_seo_analyze(session, base, results)

    print("\n[4] SEO meta (POST /apps/seo/meta)")
    step_seo_meta(session, base, results)

    print("\n[5] SEO suggestions (POST /apps/seo/suggest)")
    step_seo_suggest(session, base, results)

    print("\n[6] List leads (GET /apps/leadgen/)")
    step_leadgen_list(session, base, results)

    print("\n[7] List research results (GET /apps/research/)")
    step_research_list(session, base, results)

    print("\n[8] Create research result (POST /apps/research/)")
    step_research_create(session, base, results)

    print("\n[9] List search history (GET /apps/search/history)")
    history_id = step_search_history_list(session, base, results)

    if history_id:
        print(f"\n[10] Get history item (GET /apps/search/history/{{{history_id[:8]}...}})")
        step_search_history_get(session, base, results, history_id)

        print(f"\n[11] Delete history item (DELETE /apps/search/history/{{{history_id[:8]}...}})")
        step_search_history_delete(session, base, results, history_id)

        print(f"\n[12] Verify 404 after delete (GET /apps/search/history/{{{history_id[:8]}...}})")
        step_search_history_get_404(session, base, results, history_id)
    else:
        print("\n[10-12] Search history item steps SKIPPED -- no history items returned")
        results["search_history_get"] = "SKIP"
        results["search_history_delete"] = "SKIP"
        results["search_history_get_404"] = "SKIP"

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
        print("ALL TESTS PASSED -- search domain smoke OK")


if __name__ == "__main__":
    main()
