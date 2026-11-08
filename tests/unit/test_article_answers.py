"""ARTICLE_ANSWERS_SPEC phase A: what an article answers (§2) and links to the owner's own pieces (§3)."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

from apps.rippletrace.models import DropPointDB
from apps.rippletrace.services import own_links
from apps.rippletrace.services import article_answers as aa

pytestmark = pytest.mark.app_profile

ARTICLE = """# Where Does the Work Exist?

An agent is a loop that plans, acts and checks its own results.

Why does persistence matter? Because a run that cannot survive a restart is a demo, not a system.

Next time: how the planner decides what to remember."""


# ── §2: answers ───────────────────────────────────────────────────────────────────────


def test_passages_are_checked_against_the_article():
    content = json.dumps({
        "answers": [
            {"question": "What is an agent?", "passage": "An agent is a loop that plans, acts and checks its own results.",
             "kind": "what_is"},
            {"question": "Why does persistence matter?", "passage": "a run that cannot survive a restart is a DEMO",
             "kind": "why"},
            {"question": "Is it fast?", "passage": "It is the fastest agent ever built.", "kind": "other"},
            {"question": "", "passage": "dropped: no question"},
        ],
        "raised": [{"question": "How does the planner decide what to remember?",
                    "passage": "Next time: how the planner decides what to remember."}],
    })
    result = aa.parse_response(content, ARTICLE)

    found = {a["question"]: a["passage_found"] for a in result["answers"]}
    assert found == {"What is an agent?": True, "Why does persistence matter?": True, "Is it fast?": False}
    assert result["raised"][0]["passage_found"] is True
    assert result["range"]["what_is"] == 1 and result["range"]["why"] == 1 and result["range"]["other"] == 1


def test_unknown_kinds_and_junk_are_handled():
    result = aa.parse_response('Sure! {"answers": [{"question": "Q", "passage": "x", "kind": "Compared With"},'
                               ' {"question": "R", "passage": "y", "kind": "nonsense"}], "raised": "no"}', ARTICLE)
    assert [a["kind"] for a in result["answers"]] == ["compared_with", "other"]
    assert result["raised"] == []
    assert aa.parse_response("not json at all", ARTICLE)["answers"] == []


def test_reasoning_models_get_their_own_sampling(monkeypatch):
    monkeypatch.delenv("AINDY_ANSWERS_REASONING_EFFORT", raising=False)
    assert aa._sampling("gpt-5.5") == {"max_completion_tokens": aa.REASONING_MAX_TOKENS, "reasoning_effort": "low"}
    assert "temperature" in aa._sampling("gpt-4o-mini")
    monkeypatch.setenv("AINDY_ANSWERS_MODEL", "gpt-4o-mini")
    assert aa._model() == "gpt-4o-mini"


def _fake_call(monkeypatch, content=None, error=None):
    import AINDY.platform_layer.external_call_service as ecs

    seen = {}

    def fake(*, operation, model=None, **_kw):
        seen["model"] = model
        if error:
            raise error
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    monkeypatch.setattr(ecs, "perform_external_call", fake)
    return seen


def test_a_failed_call_is_reported_never_guessed(monkeypatch):
    _fake_call(monkeypatch, error=RuntimeError("quota"))
    result = aa.article_answers(ARTICLE)
    assert result["answers"] == [] and result["reason"] == "the answers service could not be reached"
    assert aa.article_answers("   ")["reason"] == "no article text supplied"


def test_the_route_returns_checked_answers(app, client, monkeypatch):
    from AINDY.services.auth_service import get_current_user

    monkeypatch.delenv("AINDY_ANSWERS_MODEL", raising=False)
    seen = _fake_call(monkeypatch, content=json.dumps({
        "answers": [{"question": "What is an agent?", "passage": "An agent is a loop", "kind": "what_is"}],
        "raised": [],
    }))
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(uuid.uuid4()), "is_admin": False}

    response = client.post("/apps/seo/answers", json={"text": ARTICLE, "title": "Where Does the Work Exist?"})
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    body = body.get("data", body)
    assert body["answers"][0]["passage_found"] is True
    assert body["reason"] is None and body["model"] == "gpt-5.5" and seen["model"] == "gpt-5.5"


# ── §3: links to the owner's own pieces ───────────────────────────────────────────────


def test_links_are_found_in_markdown_html_and_bare_text():
    text = ('See [part one](https://dev.to/me/part-one-1a2b). Also <a href="https://me.substack.com/p/two">two</a>, '
            "and https://medium.com/@me/three-c3d4?source=rss----x---4. Then https://dev.to/me/part-one-1a2b again.")
    assert own_links.extract_links(text) == [
        "https://dev.to/me/part-one-1a2b",
        "https://me.substack.com/p/two",
        "https://medium.com/@me/three-c3d4?source=rss----x---4",
    ]


def _piece(db, owner, title, platform, url):
    row = DropPointDB(id=f"dp-{uuid.uuid4().hex[:10]}", title=title, platform=platform, url=url,
                      core_themes="", tagged_entities="", intent="published", user_id=owner)
    db.add(row)
    db.commit()
    return row


def test_any_copy_counts_and_other_links_are_listed(db_session, monkeypatch):
    owner = uuid.uuid4()
    _piece(db_session, owner, "Part One", "DEV", "https://dev.to/me/part-one-1a2b")
    medium = _piece(db_session, owner, "Part One", "Medium", "https://medium.com/@me/part-one-9z")
    _piece(db_session, owner, "Part Two", "DEV", "https://dev.to/me/part-two-5e6f")
    _piece(db_session, uuid.uuid4(), "Their Piece", "DEV", "https://dev.to/them/theirs")  # someone else's
    monkeypatch.setattr(own_links, "_similar_chunks", lambda db, owner, parts: ([], None))

    text = (f"I wrote about this in [part one]({medium.url}?source=rss----abc---4). "
            "Compare https://dev.to/them/theirs and https://example.com/x.")
    result = own_links.own_piece_links(db_session, user_id=owner, text=text)

    assert [p["title"] for p in result["linked"]] == ["Part One"]
    assert len(result["linked"][0]["copies"]) == 2  # the DEV and Medium copies are one piece
    # Another user's piece is not "yours": it is an outside link like any other.
    assert result["other_links"] == ["https://dev.to/them/theirs", "https://example.com/x"]
    assert result["pieces_known"] == 2


def test_missing_pieces_are_ranked_and_exclude_linked_and_itself(db_session, monkeypatch):
    owner = uuid.uuid4()
    one = _piece(db_session, owner, "Part One", "DEV", "https://dev.to/me/part-one")
    two = _piece(db_session, owner, "Part Two", "DEV", "https://dev.to/me/part-two")
    three = _piece(db_session, owner, "Part Three", "DEV", "https://dev.to/me/part-three")
    draft = _piece(db_session, owner, "The Draft", "DEV", "https://dev.to/me/the-draft")

    def chunk(drop, similarity, body):
        return {"source": "published_work", "similarity": similarity,
                "content": f"{drop.title} (DEV, 2026-11-01; part 1 of 1)\n\n{body}",
                "extra": {"drop_point_id": drop.id}}

    chunks = [chunk(two, 0.71, "Two is relevant."), chunk(three, 0.83, "Three is more relevant."),
              chunk(two, 0.77, "Two's best passage."), chunk(one, 0.95, "Already linked."),
              chunk(draft, 0.99, "This is the draft itself."),
              {"source": "other_memory", "similarity": 0.99, "content": "x", "extra": {"drop_point_id": two.id}}]
    monkeypatch.setattr(own_links, "_similar_chunks", lambda db, owner, parts: (chunks, None))

    result = own_links.own_piece_links(db_session, user_id=owner, text=f"See {one.url}.", title="The Draft")
    assert [(m["title"], m["similarity"]) for m in result["missing"]] == [("Part Three", 0.83), ("Part Two", 0.77)]
    assert result["missing"][1]["passage"] == "Two's best passage."


def test_recall_reads_only_the_callers_published_work(db_session, monkeypatch):
    import AINDY.db.dao.memory_node_dao as dao_module
    import AINDY.memory.embedding_service as embedding_service

    calls = []

    class FakeDAO:
        def __init__(self, db):
            pass

        def find_similar(self, embedding, limit, user_id, node_type):
            calls.append((user_id, node_type))
            return [{"source": "published_work", "similarity": 0.5, "content": "t\n\nx", "extra": {}},
                    {"source": "agent_memory", "similarity": 0.9, "content": "y", "extra": {}}]

    monkeypatch.setattr(dao_module, "MemoryNodeDAO", FakeDAO)
    monkeypatch.setattr(embedding_service, "generate_query_embedding", lambda text: [0.1, 0.2])
    owner = uuid.uuid4()
    chunks, reason = own_links._similar_chunks(db_session, owner, ["part one", "part two"])
    assert reason is None
    assert calls == [(str(owner), "insight"), (str(owner), "insight")]
    assert [c["source"] for c in chunks] == ["published_work", "published_work"]


def test_the_own_links_route_reads_the_callers_pieces(app, client, monkeypatch):
    from AINDY.services.auth_service import get_current_user

    seen = {}

    def fake(db, *, user_id, text, title=None, exclude_url=None, missing_limit=8):
        seen.update(user_id=user_id, limit=missing_limit)
        return {"linked": [], "missing": [], "other_links": [], "pieces_known": 0, "reason": None}

    monkeypatch.setattr(own_links, "own_piece_links", fake)
    caller = uuid.uuid4()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(caller), "is_admin": False}

    response = client.post("/apps/seo/own_links", json={"text": "draft", "limit": 999})
    assert response.status_code == 200, response.text[:300]
    assert seen == {"user_id": str(caller), "limit": 20}
