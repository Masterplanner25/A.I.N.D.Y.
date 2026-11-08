"""ARTICLE_ANSWERS_SPEC phase D2: What's the structure? (§5, decided 2026-11-08).

The goal (owner): reveal that there is a structure. These tests hold the free pass to finding the skeleton and the
repeated openings a reader can see, folding the old repetition report in, and showing the series' shared shape beside
the draft, never as a score. The naming button keeps only patterns with two instances found in the text.
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

from apps.search.services import structure as st

pytestmark = pytest.mark.app_profile

DRAFT = """# Where Does the Work Exist?

Claude Code could do something different. It could inspect the actual files. It could search the repository.
It could run tests after each phase.

## The Memory Bridge

It wasn't simply a storage layer. It was supposed to be a memory orchestration system.

Phase 1 — Make It Real. Phase 2 — Make It Intelligent. Phase 3 — Make It Useful.

## What's Next?

Article 1 — I Created a Coding Language. Article 2 — I Built My Own n8n."""

FEED_STYLE = """Opening paragraph of a published piece, as the feed stores it.

Trust Accumulates

A paragraph under that heading, which the feed kept as plain text.

What's Next?

Article 1 — the first one. Article 2 — the second one."""


def test_the_skeleton_reads_markdown_html_and_feed_headings():
    sk = st.skeleton(DRAFT)
    assert [s["heading"] for s in sk["sections"]] == ["Where Does the Work Exist?", "The Memory Bridge", "What's Next?"]
    assert round(sum(s["share"] for s in sk["sections"])) == 100
    assert sk["opening"].startswith("Claude Code could do something different.")
    assert sk["closing"].startswith("Article 1") and sk["closing_heading"] == "What's Next?"

    html = "<h2>First</h2><p>One two three four.</p><h2>Second</h2><p>Five six.</p>"
    assert [s["heading"] for s in st.skeleton(html)["sections"]] == ["First", "Second"]

    feed = st.skeleton(FEED_STYLE)  # Medium and Substack drop heading markup
    assert [s["heading"] for s in feed["sections"]] == [None, "Trust Accumulates", "What's Next?"]


def test_a_short_sentence_is_not_mistaken_for_a_heading():
    assert st._looks_like_heading("What's Next?", 1)
    assert not st._looks_like_heading("And that mattered.", 1)
    assert not st._looks_like_heading("A line that runs on and on for far more than ten words in total", 1)


def test_repeated_openings_quote_every_instance_and_fold_digits():
    openings = st.structure_report(DRAFT)["openings"]
    by = {o["opening"]: o for o in openings}
    assert by["it could"]["count"] == 3
    assert by["it could"]["instances"][0] == "It could inspect the actual files."
    # "Phase 1 — Make…", "Phase 2 — Make…", "Phase 3 — Make…": digits fold, and the shared third word narrows it
    assert by["phase N make"]["count"] == 3
    assert by["article N i"]["count"] == 2
    assert all("_members" not in o for o in openings)


def test_a_three_word_opening_replaces_the_two_word_one_it_narrows():
    sentences = ["We built the runner first.", "We built the planner next.", "We built the bridge last."]
    openings = st.repeated_openings(sentences)
    assert [o["opening"] for o in openings] == ["we built the"]


def test_a_repeat_inside_one_pattern_is_folded_into_it_and_the_rest_stand_alone():
    sentences = ["It could run tests.", "It could run tests again.", "It could run tests once more.",
                 "The repository grew.", "Then the repository shrank."]
    openings = st.repeated_openings(sentences)
    repetition = {"repeated_phrases": [{"phrase": "run tests", "occurrences": 3},
                                       {"phrase": "the repository", "occurrences": 2}],
                  "overused_words": [{"word": "repository"}], "sentence_openers": [{"opener": "it", "count": 3}]}
    repeats = st.fold_repeats(repetition, openings, sentences)
    assert openings[0]["repeats"] == [{"phrase": "run tests", "occurrences": 3}]
    assert [p["phrase"] for p in repeats["phrases"]] == ["the repository"]
    assert repeats["overused_words"] and repeats["single_word_openers"]


def test_the_series_shape_shows_what_its_pieces_share_beside_the_draft():
    pieces = [{"text": FEED_STYLE}, {"text": FEED_STYLE.replace("Trust Accumulates", "Mapping the Repository")},
              {"text": "Only one paragraph, no headings at all, in this piece."}]
    shape = st.series_shape(pieces, st.skeleton(DRAFT))
    assert shape["pieces"] == 3
    assert shape["headings"] == [{"heading": "What's Next?", "pieces": 2, "in_draft": True}]
    assert shape["closing_heading"] == {"heading": "What's Next?", "pieces": 2, "in_draft": True}
    assert shape["closings"][0]["starts"] == "article N the" and shape["closings"][0]["pieces"] == 2
    assert st.series_shape([{"text": FEED_STYLE}], st.skeleton(DRAFT))["headings"] == []  # one piece is no shape


# ── the series, from RippleTrace ────────────────────────────────────────────────────────


def test_the_series_comes_from_the_title_or_the_writers_choice():
    from apps.rippletrace.services.series_text import pick_series

    names = {"2026 agents case study series": "2026 Agents Case Study Series",
             "2026 agents": "2026 Agents"}
    assert pick_series(names, title="2026 Agents Case Study Series: Where Does the Work Exist?", series=None) == \
        "2026 Agents Case Study Series"  # the longest name the title starts with
    assert pick_series(names, title="Something else", series=None) is None
    assert pick_series(names, title="Something else", series="2026 agents") == "2026 Agents"
    assert pick_series(names, title=None, series="Not a series") is None


def test_series_pieces_reads_only_the_callers_confirmed_series(db_session):
    from apps.rippletrace.container import ContainerDB
    from apps.rippletrace.models import DropPointDB
    from apps.rippletrace.services.series_text import series_pieces

    me, other = uuid.uuid4(), uuid.uuid4()
    name = f"Case Study Series {uuid.uuid4().hex[:6]}"
    db_session.add(ContainerDB(user_id=me, name=name, normalized=name.lower(), status="confirmed"))

    def drop(owner, title, text, entities=name):
        db_session.add(DropPointDB(id=f"dp-{uuid.uuid4().hex[:10]}", title=title, platform="medium.com",
                                   core_themes="", tagged_entities=entities, intent="published", user_id=owner,
                                   content_text=text))

    drop(me, f"{name}: One", "short copy")
    drop(me, f"{name}: One", "the longer copy of the same piece")  # a cross-post: the longest copy wins
    drop(me, f"{name}: Two", "piece two")
    drop(me, "Unrelated", "not in the series", entities="Something Else")
    drop(other, f"{name}: Theirs", "another user's piece")
    db_session.commit()

    found = series_pieces(db_session, me, title=f"{name}: Draft", exclude_title=f"{name}: Two")
    assert found["series"] == name and name in found["options"]
    assert [p["text"] for p in found["pieces"]] == ["the longer copy of the same piece"]
    assert series_pieces(db_session, other, title=f"{name}: Draft")["series"] is None


# ── naming the patterns ─────────────────────────────────────────────────────────────────


def _reply(*patterns):
    return json.dumps({"patterns": list(patterns)})


def test_a_pattern_needs_two_instances_found_in_the_text():
    patterns = st.parse_patterns(_reply(
        {"name": "the 'It could' run", "kind": "List",
         "instances": ["It could inspect the actual files.", "It could search the repository.", "It could fly."]},
        {"name": "a turn", "kind": "contrast",
         "instances": ["It wasn't simply a storage layer.", "Invented sentence that is not there."]},
        {"name": "", "kind": "refrain", "instances": ["It could inspect the actual files.", "It could search the repository."]},
    ), DRAFT)
    assert len(patterns) == 1
    assert patterns[0]["kind"] == "list" and patterns[0]["dropped_instances"] == 1
    assert patterns[0]["instances"] == ["It could inspect the actual files.", "It could search the repository."]
    assert st.parse_patterns("not json", DRAFT) == []


def _fake(monkeypatch, content=None, error=None):
    import AINDY.platform_layer.external_call_service as ecs

    def fake(*, operation, model=None, **_kw):
        if error:
            raise error
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    monkeypatch.setattr(ecs, "perform_external_call", fake)


def test_the_patterns_are_named_or_the_failure_is_said(monkeypatch):
    _fake(monkeypatch, content=_reply({"name": "phases", "kind": "naming_sequence",
                                       "instances": ["Phase 1 — Make It Real.", "Phase 2 — Make It Intelligent."]}))
    result = st.name_patterns(DRAFT, user_id=str(uuid.uuid4()))
    assert result["reason"] is None and result["patterns"][0]["name"] == "phases"
    _fake(monkeypatch, error=RuntimeError("quota"))
    assert st.name_patterns(DRAFT, user_id=str(uuid.uuid4()))["reason"] == "the structure service could not be reached"
    assert st.name_patterns("  ", user_id="u-1")["reason"] == "no article text supplied"


def test_the_routes(app, client, monkeypatch):
    from AINDY.services.auth_service import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {"sub": str(uuid.uuid4()), "is_admin": False}
    response = client.post("/apps/seo/structure", json={"text": DRAFT, "title": "Where Does the Work Exist?"})
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    body = body.get("data", body)
    assert body["skeleton"]["sections"] and body["openings"]
    assert body["series"]["name"] is None and body["series"]["shape"] is None

    _fake(monkeypatch, content=_reply({"name": "the 'It could' run", "kind": "list",
                                       "instances": ["It could inspect the actual files.", "It could search the repository."]}))
    response = client.post("/apps/seo/structure/patterns", json={"text": DRAFT})
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    body = body.get("data", body)
    assert body["patterns"][0]["kind"] == "list"


def test_an_empty_result_says_which_kind_of_empty_it_was():
    assert st.empty_reason("") == "the model returned nothing; press again"
    assert st.empty_reason("Sorry, here are some thoughts") == "the model's answer could not be read; press again"
    assert st.empty_reason('{"patterns": []}') == "the model found no repeated patterns"
    assert st.empty_reason(_reply({"name": "x", "kind": "list", "instances": ["not there", "nor this"]})) ==         "no pattern had two instances found word for word in the text"

