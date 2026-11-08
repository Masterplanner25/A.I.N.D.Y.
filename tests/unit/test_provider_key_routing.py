"""Whose key pays for every paid call in apps/ (FR-59 phase 3; runtime 2.32.0, DEC-121).

Three things are checked:

1. **No paid call bypasses `apps/_shared/provider_keys.py`.** A call site that builds the server's
   client or reads a provider key from the environment would keep spending the operator's key after
   `AINDY_PROVIDER_KEYS=per_user` is turned on, and nothing would say so.
2. **The helper:** server mode returns exactly the old client; a missing paying user is an error,
   never a silent server spend; a key problem is a 402 with a sentence, found anywhere in the chain.
3. **Each call site, in per-user mode, for a user with no key, stops with that 402 before any
   network call**, including the ones that catch every model error and fall back to a default.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest

from apps._shared import provider_keys as pk

pytestmark = pytest.mark.app_profile

APPS = Path(__file__).resolve().parents[2] / "apps"

# Each remaining direct use is the server's path, chosen deliberately, behind a user-key check.
ALLOWED_DIRECT = {
    # the server path after the run's user had no key of their own
    ("agent/agents/planner_anthropic.py", "ANTHROPIC_API_KEY"),
    ("agent/agents/planner_anthropic.py", "get_llm_client("),
    # startup configuration checks, no call
    ("arm/bootstrap.py", "OPENAI_API_KEY"),
    ("arm/bootstrap.py", "DEEPSEEK_API_KEY"),
    # ARM's own server client, used only when the user has no key of their own
    ("arm/services/deepseek/deepseek_code_analyzer.py", "DEEPSEEK_API_KEY"),
    ("arm/services/deepseek/deepseek_code_analyzer.py", "get_deepseek_client("),
    # `is_configured()`, the server-key gate on the (retired, flag-off) all-owner sweep; the search
    # itself resolves the piece owner's key
    ("rippletrace/services/mention_search.py", "PERPLEXITY_API_KEY"),
    # the owner-notices probe watches the operator's own balance (system=True)
    ("automation/services/owner_notices.py", "OPENAI_API_KEY"),
    # the helper itself
    ("_shared/provider_keys.py", "get_llm_client("),
}
DIRECT = re.compile(
    r"get_openai_client\(|get_deepseek_client\(|get_anthropic_client\(|get_llm_client\("
    r"|(OPENAI|DEEPSEEK|PERPLEXITY|ANTHROPIC)_API_KEY"
)


def test_no_paid_call_bypasses_the_helper():
    found = set()
    for path in APPS.rglob("*.py"):
        rel = path.relative_to(APPS).as_posix()
        if "/tests/" in f"/{rel}":
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith(('"', "'", "`")):
                continue
            for match in DIRECT.finditer(line):
                token = match.group(0)
                key = token if token.endswith("(") else f"{match.group(1)}_API_KEY"
                found.add((rel, key))
    unexpected = sorted(found - ALLOWED_DIRECT)
    assert unexpected == [], (
        "A paid call builds the server's client or reads a provider key directly. Route it through "
        f"apps/_shared/provider_keys.py (llm_client / provider_key): {unexpected}"
    )


# ── the helper ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def per_user(monkeypatch):
    from AINDY.config import settings

    monkeypatch.setattr(settings, "AINDY_PROVIDER_KEYS", "per_user", raising=False)
    return "per_user"


@pytest.fixture
def stranger():
    """A user id that is no operator and has no stored key (fresh, so no operator cache entry)."""
    return str(uuid.uuid4())


def test_server_mode_returns_the_same_client_as_before():
    from AINDY.platform_layer.openai_client import get_openai_client

    assert pk.llm_client(str(uuid.uuid4())) is get_openai_client()


def test_a_paid_call_without_a_paying_user_is_refused():
    with pytest.raises(ValueError, match="needs the user"):
        pk.llm_client(None)
    with pytest.raises(ValueError):
        pk.provider_key("  ", "perplexity")
    assert pk.llm_client(None, system=True) is not None  # the operator's own call


def test_per_user_mode_without_a_key_is_a_402_sentence(per_user, stranger, db_session):
    with pytest.raises(pk.ProviderKeyProblem) as raised:
        pk.llm_client(stranger, db=db_session)
    problem = raised.value
    assert problem.status_code == 402 and problem.kind == pk.REQUIRED
    assert problem.detail == "This needs your own OpenAI API key. Add it in Settings."
    assert str(problem).startswith("HTTP_402:")  # a flow node's error string keeps the status
    assert pk.can_pay(stranger, db=db_session) is False


def test_can_pay_in_server_mode(stranger, db_session):
    assert pk.can_pay(stranger, db=db_session) is True
    assert pk.can_pay(None) is False


def test_key_problem_is_found_in_a_cyclic_chain():
    from AINDY.platform_layer.llm_client import LLMCallError
    from AINDY.platform_layer.provider_keys import ProviderKeyRejected

    rejected = ProviderKeyRejected("openai", "abcd")
    wrapper = LLMCallError("openai call failed")
    wrapper.__cause__ = rejected
    rejected.__cause__ = wrapper  # what the runtime's chat_completion hands back
    problem = pk.key_problem(wrapper)
    assert problem is not None and problem.kind == pk.REJECTED
    assert problem.detail == "OpenAI refused your API key (ending abcd). Replace it in Settings."
    assert pk.key_problem(RuntimeError("timeout")) is None


def test_a_refused_user_key_is_the_users_but_a_refused_server_key_is_not():
    from AINDY.platform_layer.provider_keys import ResolvedKey

    user = ResolvedKey(provider="perplexity", value="k", source="user", fingerprint="f", key_hint="wxyz")
    server = ResolvedKey(provider="perplexity", value="k", source="server", fingerprint="f")
    with pytest.raises(pk.ProviderKeyProblem) as raised:
        pk.refused(user, 401)
    assert raised.value.kind == pk.REJECTED
    pk.refused(server, 401)  # the operator's problem, the call site's ordinary failure
    pk.refused(user, 500)


def test_a_users_own_key_gets_its_own_client(monkeypatch, stranger):
    from AINDY.platform_layer import provider_keys as runtime_keys
    from AINDY.platform_layer.provider_keys import ResolvedKey

    resolved = ResolvedKey(provider="openai", value="sk-user-test", source="user", fingerprint="fp-test",
                           key_hint="test")
    monkeypatch.setattr(runtime_keys, "resolve_provider_key", lambda provider, user_id, db=None: resolved)
    client = pk.llm_client(stranger)
    assert getattr(client, "key_source", None) == "user"
    sentinel = object()
    assert pk.client_for_resolved(resolved, sentinel) is not sentinel
    assert pk.client_for_resolved(ResolvedKey("openai", "s", "server", "f"), sentinel) is sentinel


# ── each call site, per-user mode, a user without a key ────────────────────────────────────


def _no_network(monkeypatch):
    """Any outbound call is a test failure: the 402 must come first."""
    import requests

    def _boom(*args, **kwargs):
        raise AssertionError("a paid call went out for a user with no key")

    monkeypatch.setattr(requests, "post", _boom)
    from AINDY.platform_layer import external_call_service

    monkeypatch.setattr(external_call_service, "perform_external_call", _boom)


def _sites(uid, db):
    from apps.agent.agents import planner_anthropic
    from apps.masterplan.services import draft_service, genesis_ai, resolution_engines
    from apps.rippletrace.services import article_answers, mention_search, share_drafts
    from apps.search.services import (
        article_claims,
        leadgen_service,
        meta_generation,
        research_engine,
        segment_search,
        structure,
        title_generation,
    )

    return {
        "article_answers": lambda: article_answers.article_answers("Some text.", user_id=uid, db=db),
        "article_claims": lambda: article_claims.article_claims("Some text.", user_id=uid, db=db),
        "structure_patterns": lambda: structure.name_patterns("Some text.", user_id=uid, db=db),
        "meta_generation": lambda: meta_generation.generate_meta_from_article("Some text.", user_id=uid, db=db),
        "title_generation": lambda: title_generation.generate_title_candidates("Some text.", user_id=uid, db=db),
        "score_lead": lambda: leadgen_service.score_lead(
            {"company": "C", "url": "https://c.example", "context": "x"}, user_id=uid, db=db),
        "web_search": lambda: research_engine.web_search_results("q", user_id=uid, db=db),
        "ai_analyze": lambda: research_engine.ai_analyze("text", user_id=uid, db=db),
        "segment_judge": lambda: segment_search.judge_result(
            {"title": "t", "url": "u", "snippet": "s"}, {"name": "s", "buyer": "b"}, user_id=uid, db=db),
        "resolution_perplexity": lambda: resolution_engines.ask_perplexity("q", user_id=uid, db=db),
        "resolution_openai": lambda: resolution_engines.ask_openai("q", user_id=uid, db=db),
        "resolution_claude": lambda: resolution_engines.ask_claude("q", user_id=uid, db=db),
        "mention_search": lambda: mention_search.search(["q"], user_id=uid, db=db),
        "content_draft": lambda: draft_service._complete("brief", "sources", user_id=uid, db=db),
        "share_drafts": lambda: share_drafts._complete("prompt", db=db, user_id=uid),
        "genesis_import": lambda: genesis_ai.call_genesis_import_llm("My plan.", user_id=uid, db=db),
        "anthropic_planner": lambda: planner_anthropic._make_client(user_id=uid, db=db),
    }


SITE_NAMES = sorted(_sites("x", None))


@pytest.mark.parametrize("site", SITE_NAMES)
def test_each_site_stops_with_a_402_before_any_call(site, per_user, stranger, db_session, monkeypatch):
    _no_network(monkeypatch)
    with pytest.raises(pk.ProviderKeyProblem) as raised:
        _sites(stranger, db_session)[site]()
    assert raised.value.status_code == 402


def test_arm_stops_with_a_402_before_any_call(per_user, stranger, db_session, monkeypatch):
    from apps.arm.services.deepseek.deepseek_code_analyzer import DeepSeekCodeAnalyzer

    _no_network(monkeypatch)
    analyzer = DeepSeekCodeAnalyzer()
    with pytest.raises(pk.ProviderKeyProblem) as raised:
        analyzer._call_openai("system", "user", db_session, stranger)
    assert raised.value.provider == "deepseek"


def test_piece_answers_job_skips_an_owner_without_a_key(per_user, db_session, monkeypatch):
    """A scheduled job asks before starting a user's work: skipped quietly, the piece stays due."""
    from apps.rippletrace.models import DropPointDB
    from apps.rippletrace.services import answers_nodus

    owner = uuid.uuid4()
    drop = DropPointDB(id=f"drop-{uuid.uuid4().hex[:8]}", title="A piece", platform="notes.example.com",
                       core_themes="t", tagged_entities="e", intent="published", user_id=owner,
                       content_text="Text.", content_hash="h" * 16)
    db_session.add(drop)
    db_session.commit()

    class _Session:
        def __init__(self):
            self._db = db_session

        def __getattr__(self, name):
            return getattr(self._db, name)

        def close(self):
            pass

    import AINDY.db.database as database

    monkeypatch.setattr(database, "SessionLocal", _Session)
    monkeypatch.setattr(answers_nodus, "answers_owner",
                        lambda db, owner: pytest.fail("work started for an owner with no key"))
    summary = answers_nodus.write_piece_answers()
    assert summary["no_key"] >= 1
    db_session.refresh(drop)
    assert drop.answers is None


# ── what the person sees over HTTP ─────────────────────────────────────────────────────────


def _as(app, uid):
    from AINDY.services.auth_service import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {"sub": uid, "is_admin": False}


def _message(response) -> str:
    body = response.json()
    return str(body)


def test_a_route_answers_402_with_the_sentence(app, client, per_user, stranger, monkeypatch):
    _no_network(monkeypatch)
    _as(app, stranger)
    response = client.post("/apps/seo/answers", json={"text": "Some article text.", "title": "T"})
    assert response.status_code == 402, response.text[:300]
    assert "Add it in Settings" in _message(response)


def test_genesis_through_its_syscall_answers_402(app, client, per_user, stranger, monkeypatch):
    _no_network(monkeypatch)
    _as(app, stranger)
    created = client.post("/apps/genesis/session")
    assert created.status_code in (200, 201), created.text[:300]
    body = created.json()
    body = body.get("data", body)
    session_id = body.get("session_id") or (body.get("result") or {}).get("session_id")
    assert session_id, body
    response = client.post("/apps/genesis/message", json={"session_id": session_id, "message": "Hello"})
    assert response.status_code == 402, response.text[:400]
    assert "Add it in Settings" in _message(response)


@pytest.mark.parametrize("module", [
    "apps.automation.flows.flow_definitions",
    "apps.automation.flows.system_flows",
    "apps.tasks.flows.tasks_flows",
])
def test_a_flow_node_fails_a_key_problem_instead_of_retrying_it(module, monkeypatch):
    """Runtime 2.34.0 handoff §4: `_syscall_node` turned every syscall error into RETRY, so a refused key was
    tried three times. A key problem is FAILURE (one attempt); anything else still retries."""
    import importlib

    import AINDY.kernel.syscall_dispatcher as dispatcher_module

    errors = iter([
        "HTTP_402:OpenAI refused your API key (ending abcd). Replace it in Settings.",
        "connection reset",
    ])

    class _Dispatcher:
        def dispatch(self, name, payload, ctx):
            return {"status": "error", "error": next(errors)}

    monkeypatch.setattr(dispatcher_module, "get_dispatcher", lambda: _Dispatcher())
    node = importlib.import_module(module)._syscall_node
    context = {"user_id": str(uuid.uuid4()), "trace_id": "t", "execution_unit_id": "eu"}
    first = node("sys.v1.example.write", {}, context, "example.write")
    assert first["status"] == "FAILURE" and first["error"].startswith("HTTP_402:")
    assert node("sys.v1.example.write", {}, context, "example.write")["status"] == "RETRY"
