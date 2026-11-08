"""ARTICLE_ANSWERS_SPEC phase D1: What does this claim? (§4, decided 2026-11-08).

The model only points into lists it is given; these tests hold the module to keeping a pointer only when it is
real, and to the statuses decided: contradicts / confirmed / new for the writer's Works, sourced / unsourced
for everything else. Information only, and never a guess.
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

from apps.search.services import article_claims as ac

pytestmark = pytest.mark.app_profile

DRAFT = """# Where Does the Work Exist?

Nodus is part of A.I.N.D.Y. and was released in 2025.

Gartner found that 40% of agent projects fail ([report](https://gartner.example/agents)).

A.I.N.D.Y. runs on aindy-runtime.

Agents fail because nobody owns the loop.

I think most frameworks are overbuilt. See [my last piece](https://shawn.dev.example/last)."""

TRUTH = {
    "works": [
        {"name": "Nodus", "kind": "project",
         "facts": ["Nodus is a project.", "Nodus is the layer underneath aindy-runtime."],
         "denied": ["Nodus is part of A.I.N.D.Y."]},
        {"name": "A.I.N.D.Y.", "kind": "project",
         "facts": ["A.I.N.D.Y. is a project.", "A.I.N.D.Y. runs on aindy-runtime."], "denied": []},
    ],
    "own_hosts": ["shawn.dev.example"],
}
LINKS = ["https://gartner.example/agents", "https://shawn.dev.example/last"]


def _reply(*claims):
    return json.dumps({"claims": list(claims)})


def _claim(text, kind="named", work=None, fact=None, denied=None, source=None):
    return {"claim": text, "kind": kind, "work": work, "fact": fact, "denied": denied, "source": source}


def test_each_status_comes_from_a_real_pointer():
    result = ac.parse_response(_reply(
        _claim("Nodus is part of A.I.N.D.Y. and was released in 2025.", work="Nodus", denied="D1"),
        _claim("A.I.N.D.Y. runs on aindy-runtime.", work="A.I.N.D.Y.", fact="F2"),
        _claim("Gartner found that 40% of agent projects fail", "attribution", source="L1"),
        _claim("Agents fail because nobody owns the loop.", "cause_comparison"),
    ), DRAFT, TRUTH, LINKS)
    statuses = [c["status"] for c in result["claims"]]
    assert statuses == ["contradicts", "confirmed", "sourced", "unsourced"]
    assert result["claims"][0]["denied"] == "Nodus is part of A.I.N.D.Y."
    assert result["claims"][1]["fact"] == "A.I.N.D.Y. runs on aindy-runtime."
    assert result["claims"][2]["source"] == "https://gartner.example/agents"
    assert all(c["found"] for c in result["claims"])
    assert result["counts"] == {"contradicts": 1, "confirmed": 1, "new": 0, "sourced": 1, "unsourced": 1}


def test_a_pointer_into_another_works_list_or_past_the_end_is_dropped():
    result = ac.parse_response(_reply(
        # F2 exists for Nodus, but the claim names A.I.N.D.Y., whose F9 does not exist
        _claim("A.I.N.D.Y. runs on aindy-runtime.", work="A.I.N.D.Y.", fact="F9"),
        # a denial id for a Work with no denials
        _claim("A.I.N.D.Y. runs on aindy-runtime.", work="A.I.N.D.Y.", denied="D1"),
        # an unknown Work: treated as "anything else"; L7 is not in the draft
        _claim("Agents fail because nobody owns the loop.", work="Someone Else", source="L7"),
    ), DRAFT, TRUTH, LINKS)
    assert [c["status"] for c in result["claims"]] == ["new", "new", "unsourced"]
    assert result["claims"][2]["work"] is None and result["claims"][2]["source"] is None


def test_a_quote_not_in_the_text_is_marked_and_kinds_are_normalised():
    result = ac.parse_response(_reply(
        _claim("Nodus ships with forty plugins.", "Number", work="nodus"),
        _claim("Agents fail because nobody owns the loop.", "unknown kind"),
    ), DRAFT, TRUTH, LINKS)
    first, second = result["claims"]
    assert first["found"] is False and first["kind"] == "number" and first["work"] == "Nodus"
    assert second["kind"] == "named"


def test_sources_list_every_link_with_the_claims_on_it_and_mark_the_writers_own():
    result = ac.parse_response(_reply(
        _claim("Gartner found that 40% of agent projects fail", "attribution", source="L1"),
    ), DRAFT, TRUTH, LINKS)
    assert result["sources"] == [
        {"url": "https://gartner.example/agents", "own": False, "claims": [0]},
        {"url": "https://shawn.dev.example/last", "own": True, "claims": []},
    ]


def test_junk_gives_an_empty_list():
    for junk in ("", "not json", "[1, 2]", '{"claims": "x"}', '{"claims": [{"claim": ""}, 3]}'):
        assert ac.parse_response(junk, DRAFT, TRUTH, LINKS)["claims"] == []


def test_the_context_numbers_facts_denials_and_links():
    context = ac.build_context(TRUTH, LINKS)
    assert "WORK: Nodus (project)\nF1: Nodus is a project.\nF2: Nodus is the layer underneath aindy-runtime.\nD1: Nodus is part of A.I.N.D.Y." in context
    assert "L1: https://gartner.example/agents" in context and "L2: https://shawn.dev.example/last" in context
    assert "(none)" in ac.build_context({"works": [], "own_hosts": []}, [])


# ── the call ─────────────────────────────────────────────────────────────────────────────


def _fake(monkeypatch, content=None, error=None, truth=TRUTH):
    import AINDY.platform_layer.external_call_service as ecs

    seen = {}

    def fake(*, operation, model=None, **_kw):
        seen["model"] = model
        if error:
            raise error
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    monkeypatch.setattr(ecs, "perform_external_call", fake)
    monkeypatch.setattr(ac, "_owner_truth", lambda user_id, db: truth)
    return seen


def test_the_draft_is_read_and_checked(monkeypatch):
    monkeypatch.delenv("AINDY_CLAIMS_MODEL", raising=False)
    seen = _fake(monkeypatch, content=_reply(_claim("A.I.N.D.Y. runs on aindy-runtime.", work="A.I.N.D.Y.", fact="F2")))
    result = ac.article_claims(DRAFT, user_id=str(uuid.uuid4()))
    assert result["reason"] is None and result["model"] == "gpt-5.5" and seen["model"] == "gpt-5.5"
    assert result["works_checked"] == 2 and result["claims"][0]["status"] == "confirmed"


def test_a_failure_is_reported_never_guessed(monkeypatch):
    _fake(monkeypatch, error=RuntimeError("quota"))
    result = ac.article_claims(DRAFT, user_id=str(uuid.uuid4()))
    assert result["claims"] == [] and result["reason"] == "the claims service could not be reached"
    assert [s["url"] for s in result["sources"]] == LINKS  # the links are still the draft's own
    assert ac.article_claims("   ", user_id="u-1")["reason"] == "no article text supplied"


def test_unreadable_works_are_said_not_skipped(monkeypatch):
    _fake(monkeypatch, content=_reply())

    def boom(user_id, db):
        raise RuntimeError("syscall failed")

    monkeypatch.setattr(ac, "_owner_truth", boom)
    assert ac.article_claims(DRAFT, user_id=str(uuid.uuid4()))["reason"] == "your Works could not be read"


def test_the_route_returns_the_claims(app, client, monkeypatch):
    from AINDY.services.auth_service import get_current_user

    _fake(monkeypatch, content=_reply(_claim("Agents fail because nobody owns the loop.", "cause_comparison")))
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(uuid.uuid4()), "is_admin": False}
    response = client.post("/apps/seo/claims", json={"text": DRAFT, "title": "Where Does the Work Exist?"})
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    body = body.get("data", body)
    assert body["claims"][0]["status"] == "unsourced" and body["counts"]["unsourced"] == 1


# ── the syscall it reads the writer's Works through ──────────────────────────────────────


def test_the_claim_truth_syscall_declares_what_its_name_infers():
    from AINDY.kernel.syscall_dispatcher import _infer_dispatch_capability
    from AINDY.kernel.syscall_registry import SYSCALL_REGISTRY

    name = "sys.v1.work.get_claim_truth"
    entry = SYSCALL_REGISTRY[name]
    declared = getattr(entry, "capability", None) or (entry.get("capability") if isinstance(entry, dict) else None)
    assert declared == _infer_dispatch_capability(name) == "work.read"


def test_the_claim_truth_syscall_reads_only_the_callers_works(monkeypatch):
    from apps.masterplan.services import resolution_service
    from apps.masterplan.syscalls import syscall_handlers as handlers

    me = uuid.uuid4()
    seen = {}

    def fake_truth(db, uid):
        seen["uid"] = uid
        return {"entities": {"w1": {"name": "Nodus", "kind": "project", "summary": "A language.", "presence": [],
                                    "confirmed_claims": ["It is open source."], "denied_claims": ["Part of A.I.N.D.Y."]}},
                "links": [{"a": "w1", "b": "w2", "text": "Nodus underlies aindy-runtime"}], "own_hosts": ["x.example"]}

    monkeypatch.setattr(resolution_service, "ground_truth", fake_truth)
    ctx = SimpleNamespace(user_id=str(me), metadata={"_db": object()})
    out = handlers._handle_work_get_claim_truth({"user_id": str(uuid.uuid4())}, ctx)
    assert seen["uid"] == me  # the caller, never a payload id
    work = out["works"][0]
    assert work["denied"] == ["Part of A.I.N.D.Y."]
    assert "Confirmed by the owner: It is open source." in work["facts"]
    assert "Nodus underlies aindy-runtime" in work["facts"] and out["own_hosts"] == ["x.example"]


def test_a_quoted_sentence_is_found_through_its_link_markup():
    """`[found](url)` and `<a href>found</a>` read as "found"; a correct quote must match (phase A's answers too)."""
    claim = _claim("Gartner found that 40% of agent projects fail.", "attribution", source="L1")
    for article in ("Gartner [found](https://g.example/x) that **40%** of agent projects fail.",
                    'Gartner <a href="https://g.example/x">found</a> that 40% of agent projects fail.',
                    "![chart](https://i.example/c.png) Gartner found that 40% of agent projects fail."):
        result = ac.parse_response(_reply(claim), article, {"works": [], "own_hosts": []}, ["https://g.example/x"])
        assert result["claims"][0]["found"] is True, article
