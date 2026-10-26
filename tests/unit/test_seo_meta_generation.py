"""The meta description is written from the whole article's central point (owner, 2026-10-25).

Until then it was the article's first ~160 characters, cut at a sentence end: nothing read the
article. These pin what replaced it:

* the model sees the whole article, not its opening, and is told the writer's title as the
  framing to keep;
* the central point it took from the article comes back with the description, so a wrong
  reading is visible;
* over budget is kept and marked, never trimmed by the tool;
* it fails honestly: no opening-lines fallback dressed as a description.

No test here makes a network call; the model is stubbed at `perform_external_call`.
"""

from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-required-length-1234567890")

pytestmark = pytest.mark.app_profile

metagen = pytest.importorskip("apps.search.services.meta_generation")

OPENING = "The project began as a memory store for an agent. " * 60
LATE_POINT = "A version is a promise about behaviour, and the release notes must keep it."
ARTICLE = OPENING + LATE_POINT


class _Message:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Message(content)


class _Completion:
    def __init__(self, content):
        self.choices = [_Choice(content)]


@pytest.fixture
def model(monkeypatch):
    calls: list[dict] = []
    state = {
        "content": json.dumps({
            "central_point": "A version number is a promise the release has to keep.",
            "meta_description": "What a version promises: why a release number is a commitment about behaviour.",
        })
    }

    def _perform(**kwargs):
        calls.append(kwargs)
        if isinstance(state["content"], Exception):
            raise state["content"]
        return _Completion(state["content"])

    monkeypatch.setattr(metagen, "perform_external_call", _perform)
    return {"calls": calls, "state": state}


def test_the_description_comes_back_with_the_point_it_was_built_on(model):
    result = metagen.generate_meta_from_article(ARTICLE, title="What a version promises")

    assert result["meta_description"].startswith("What a version promises")
    assert result["central_point"] == "A version number is a promise the release has to keep."
    assert result["characters"] == len(result["meta_description"])
    assert result["budget"] == 160
    assert result["reason"] is None


def test_the_whole_article_is_sent_not_its_opening():
    """The old description was position, not reading. The late point must reach the model."""
    prompt = metagen._user_prompt(ARTICLE, title=None)

    assert len(ARTICLE) > 2_000
    assert LATE_POINT in prompt


def test_the_writers_title_is_sent_as_the_framing_to_keep():
    prompt = metagen._user_prompt(ARTICLE, title="2026 Agents Case Study Series: What a version promises")

    assert "What a version promises" in prompt
    assert "Keep that" in metagen.SYSTEM_PROMPT
    assert "framing" in metagen.SYSTEM_PROMPT


def test_the_prompt_asks_for_the_point_not_the_most_frequent_topic():
    assert "Not its most frequent topic" in metagen.SYSTEM_PROMPT
    assert "Do not introduce a claim" in metagen.SYSTEM_PROMPT


def test_over_budget_is_kept_and_marked_not_trimmed(model):
    long = "A description that keeps going well past the line a search result shows, " * 4
    model["state"]["content"] = json.dumps({"central_point": "p", "meta_description": long})

    result = metagen.generate_meta_from_article(ARTICLE)

    assert result["meta_description"] == " ".join(long.split())
    assert result["over_by"] == result["characters"] - 160 > 0
    assert result["truncated"] is True
    assert result["serp_preview"].endswith("…")


def test_a_failed_call_returns_nothing_and_says_why(model):
    model["state"]["content"] = RuntimeError("boom")

    result = metagen.generate_meta_from_article(ARTICLE)

    assert result["meta_description"] == ""
    assert result["reason"] == "the description service could not be reached"


def test_there_is_no_opening_lines_fallback(model):
    """An opening-lines description would look like one written from the whole piece."""
    model["state"]["content"] = RuntimeError("boom")

    result = metagen.generate_meta_from_article(ARTICLE)

    assert "memory store" not in json.dumps(result)


def test_unparseable_output_is_no_answer(model):
    model["state"]["content"] = "I think the article is about versions."

    result = metagen.generate_meta_from_article(ARTICLE)

    assert result["meta_description"] == ""
    assert result["reason"] == "no usable description was returned"


def test_an_empty_article_never_reaches_the_model(model):
    result = metagen.generate_meta_from_article("   ")

    assert model["calls"] == []
    assert "no article text" in result["reason"]


def test_the_route_wrapper_passes_the_title_and_budget(model):
    from apps.search.services.search_service import generate_meta

    result = generate_meta(ARTICLE, 150, title="What a version promises")

    assert result["budget"] == 150
    assert result["central_point"]
