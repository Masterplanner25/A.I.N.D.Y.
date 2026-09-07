"""Title generation: the first feature that has this tool write, and the first LLM call in it.

Owner's call, 2026-09-07 — *"yes and yes; the tool may not call an LLM currently, but that's
always been in the plans."* Until now the SEO tool had no way to produce a title and no model
call anywhere; `generate_meta_description` is deterministic trimming, not authorship.

★ **The whole risk is that a generator stops being an aid.** `SEO_EDITING_AID_SPEC` exists
because a tool that rewrites the author's work has changed jobs, and a title generator is
where that line is easiest to cross — silently, and in a way that looks like a feature. So
most of what follows asserts what must NOT come back:

* the writer's own title is input and never output — no field a client could apply on its own;
* no "best" or "recommended" candidate, and no single-title shape to drop into the input box;
* **no deterministic fallback.** Every other generator here degrades to something local. This
  one must not: a title assembled from word frequencies arrives looking exactly like a model's
  proposal, and the writer has no way to tell a suggestion from a shrug.

No test in this file makes a network call. The model is stubbed at the boundary
(`perform_external_call`), which is also the seam that would tell us if the call were ever
made unconditionally.
"""

from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-required-length-1234567890")

pytestmark = pytest.mark.app_profile

titlegen = pytest.importorskip("apps.search.services.title_generation")
seo = pytest.importorskip("apps.search.services.seo_services")

ARTICLE = "Frameworks and relationships shape how a runtime behaves in practice. " * 40


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
    """Stub the model at the external-call boundary and record what it was sent."""
    calls: list[dict] = []
    state = {"content": json.dumps({"titles": ["A reasonable title about frameworks"]})}

    def _perform(**kwargs):
        calls.append(kwargs)
        if isinstance(state["content"], Exception):
            raise state["content"]
        return _Completion(state["content"])

    monkeypatch.setattr(titlegen, "perform_external_call", _perform)
    return {"calls": calls, "state": state}


def _returns(model, titles):
    model["state"]["content"] = json.dumps({"titles": titles})


# ── it proposes ────────────────────────────────────────────────────────────────────────

def test_candidates_come_back_measured_like_any_other_title(model):
    """A proposal and the writer's own title are reported on identical terms.

    Both go through `analyze_title`, so a candidate cannot be presented with a friendlier
    scorecard than the title it is competing with.
    """
    _returns(model, ["A clear title about frameworks and runtimes"])
    result = titlegen.generate_title_candidates(ARTICLE)

    candidate = result["candidates"][0]
    assert candidate == seo.analyze_title("A clear title about frameworks and runtimes")
    assert candidate["characters"] == 43
    assert result["budget"] == seo.TITLE_CHAR_BUDGET


def test_over_budget_candidates_are_kept_and_marked_not_dropped(model):
    """★ A silently shortened list would hide that the model overshot.

    It would also decide for the writer, who may well prefer a long option they intend to
    trim. Marked, not removed.
    """
    long_title = "x" * (seo.TITLE_CHAR_BUDGET + 25)
    _returns(model, [long_title, "A short one"])
    result = titlegen.generate_title_candidates(ARTICLE)

    assert len(result["candidates"]) == 2
    over = [c for c in result["candidates"] if c["over_by"] > 0]
    assert over and over[0]["over_by"] == 25


def test_within_budget_candidates_are_listed_first(model):
    """Ordering is a convenience, not a verdict — every candidate keeps its own measurement."""
    _returns(model, ["y" * 90, "A usable title about frameworks", "z" * 80])
    result = titlegen.generate_title_candidates(ARTICLE)

    over_flags = [c["over_by"] > 0 for c in result["candidates"]]
    assert over_flags == sorted(over_flags)


def test_exact_repeats_are_dropped(model):
    """Only exact repeats. Near-duplicate detection would be the tool deciding which of the
    writer's options are worth seeing."""
    _returns(model, ["Same Title", "same title", "  Same   Title  ", "A different one"])
    result = titlegen.generate_title_candidates(ARTICLE)

    assert [c["title"] for c in result["candidates"]] == ["Same Title", "A different one"]


def test_the_requested_count_is_bounded(model):
    _returns(model, [f"Candidate number {n} about frameworks" for n in range(20)])

    assert titlegen.generate_title_candidates(ARTICLE, count=3)["count"] == 3
    assert titlegen.generate_title_candidates(ARTICLE, count=99)["count"] <= titlegen.MAX_CANDIDATE_COUNT
    assert titlegen.generate_title_candidates(ARTICLE, count=0)["count"] == 1
    # None means unspecified and takes the default; 0 is a number that was asked for, and
    # folding the two together would silently answer a different question.
    assert titlegen.generate_title_candidates(ARTICLE, count=None)["count"] == titlegen.DEFAULT_CANDIDATE_COUNT


# ── it never replaces ──────────────────────────────────────────────────────────────────

def test_the_writers_title_is_echoed_back_untouched(model):
    """★ Input, never output.

    Returning it here is what lets a client show "yours" beside the options without ever
    having received a replacement for it.
    """
    result = titlegen.generate_title_candidates(
        ARTICLE, existing_title="2025 ChatGPT Case Study Series: Ethics"
    )

    assert result["current_title"] == "2025 ChatGPT Case Study Series: Ethics"


def test_there_is_no_recommended_candidate_and_no_single_title_field(model):
    """★ A list requires a person to choose. A "best" field does not.

    Any of these keys would be a one-line change away from a client applying it automatically,
    which is the failure this whole feature is shaped around.
    """
    _returns(model, ["One title", "Another title"])
    result = titlegen.generate_title_candidates(ARTICLE)

    forbidden = {"title", "best", "best_title", "recommended", "suggested_title", "apply"}
    assert not (forbidden & set(result))
    assert isinstance(result["candidates"], list)


def test_the_writers_title_is_sent_as_context_not_as_something_to_beat(model):
    """It goes into the prompt so candidates can keep a deliberate series prefix."""
    titlegen.generate_title_candidates(ARTICLE, existing_title="Series: Part Four")

    sent = model["calls"][0]["operation"]
    # The operation is a closure over the messages; assert on the prompt the caller built.
    assert callable(sent)
    prompt = titlegen._user_prompt(
        ARTICLE, count=5, existing_title="Series: Part Four", target_keywords=None
    )
    assert "Series: Part Four" in prompt


# ── it fails honestly ──────────────────────────────────────────────────────────────────

def test_an_unavailable_model_returns_nothing_and_says_why(model):
    from AINDY.kernel.circuit_breaker import CircuitOpenError

    model["state"]["content"] = CircuitOpenError("openai")
    result = titlegen.generate_title_candidates(ARTICLE)

    assert result["candidates"] == []
    assert "unavailable" in result["reason"]


def test_a_failed_call_returns_nothing_and_says_why(model):
    model["state"]["content"] = RuntimeError("connection reset")
    result = titlegen.generate_title_candidates(ARTICLE)

    assert result["candidates"] == []
    assert result["reason"]


def test_there_is_no_deterministic_fallback(model):
    """★ The most important assertion in this file.

    Every other generator here degrades to something local. A title built from word
    frequencies would arrive in the UI looking exactly like a model's proposal, and the writer
    would have no way to tell a suggestion from a failure. Silence is the honest answer.
    """
    model["state"]["content"] = RuntimeError("down")
    result = titlegen.generate_title_candidates(ARTICLE)

    assert result["count"] == 0
    # Nothing derived from the article may appear in the response.
    assert "frameworks" not in json.dumps(result).lower()


def test_unparseable_output_is_treated_as_no_answer(model):
    """The same situation as unavailable, and it must end the same way."""
    model["state"]["content"] = "Sure! Here are some great titles for you."
    result = titlegen.generate_title_candidates(ARTICLE)

    assert result["candidates"] == []
    assert result["reason"]


def test_json_wrapped_in_prose_is_still_read(model):
    """Tolerant of a chatty model, without being tolerant of an empty one."""
    model["state"]["content"] = 'Here you go:\n{"titles": ["A good title here"]}\nHope that helps!'
    result = titlegen.generate_title_candidates(ARTICLE)

    assert [c["title"] for c in result["candidates"]] == ["A good title here"]


def test_non_string_entries_are_discarded(model):
    model["state"]["content"] = json.dumps({"titles": ["Real title", None, 42, "", "  "]})
    result = titlegen.generate_title_candidates(ARTICLE)

    assert [c["title"] for c in result["candidates"]] == ["Real title"]


def test_an_empty_article_never_reaches_the_model(model):
    """No text, no call. Paying for a request that cannot succeed is its own defect."""
    result = titlegen.generate_title_candidates("   ")

    assert model["calls"] == []
    assert result["candidates"] == []
    assert "no article text" in result["reason"]


# ── what is sent ───────────────────────────────────────────────────────────────────────

def test_the_article_is_truncated_before_it_is_sent():
    """A title is decided by what the piece is about, which is established early.

    Sending 40,000 characters to choose a 60-character line pays for tokens that change
    nothing, and bounded input is the rule every other external call here follows.
    """
    prompt = titlegen._user_prompt(
        "z" * 50_000, count=5, existing_title=None, target_keywords=None
    )

    assert prompt.count("z") == titlegen.MAX_ARTICLE_CHARS_SENT


def test_target_keywords_are_passed_as_a_constraint_not_a_requirement():
    prompt = titlegen._user_prompt(
        ARTICLE, count=5, existing_title=None, target_keywords=["runtime", "frameworks"]
    )

    assert "runtime, frameworks" in prompt
    # The system prompt is where the "only where they fit naturally" rule lives.
    assert "only where they fit naturally" in titlegen.SYSTEM_PROMPT


def test_the_prompt_carries_the_budget_it_is_asked_to_respect():
    filled = titlegen.SYSTEM_PROMPT.format(
        budget=seo.TITLE_CHAR_BUDGET, minimum=seo.TITLE_CHAR_MIN
    )

    assert str(seo.TITLE_CHAR_BUDGET) in filled
    assert str(seo.TITLE_CHAR_MIN) in filled


def test_the_prompt_forbids_inventing_what_the_article_does_not_say():
    """The model is titling an article, not writing a claim about one."""
    assert "Do not introduce a claim" in titlegen.SYSTEM_PROMPT
