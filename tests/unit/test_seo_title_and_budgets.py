"""The SEO tool had no concept of a title, and no budget it could state in the right unit.

Two gaps, one cause. `seo_analysis` took a single blob of body text — there was no `title`
parameter anywhere in the tool — so it could report on a draft without ever looking at the
line a search result actually shows. And the only budget it did enforce, the meta
description's, had to be hand-rolled in characters because the repo's word-based limiter
lives in the runtime and counts the wrong thing (`TITLE_AS_CONTAINER_SPEC.md` §6 and §6a).

That unit confusion has already shipped once: `generate_meta_description` passed `limit=160`
into `enforce_word_limit` and produced ~160 *words* — roughly 900 characters, six times past
the SERP cutoff. So the tests below assert on characters explicitly, everywhere, and one of
them pins the budgets themselves so a retune is a deliberate act rather than a drift.

★ The other thing these pin is what the tool must NOT do. It is an editing aid
(`SEO_EDITING_AID_SPEC`): it measures and points, and it never rewrites the writer's title.
Every verdict must arrive with the number that produced it — a budget that hides the count is
the tool deciding for the writer.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-required-length-1234567890")

pytestmark = pytest.mark.app_profile

seo = pytest.importorskip("apps.search.services.seo_services")

analyze_title = seo.analyze_title
count_characters = seo.count_characters
seo_analysis = seo.seo_analysis
truncate_preview = seo.truncate_preview

BODY = "Frameworks and relationships shape how a runtime behaves in practice. " * 40


def _title(n: int) -> str:
    """A title of exactly `n` characters."""
    return "a" * n


# ── the unit ───────────────────────────────────────────────────────────────────────────

def test_the_budgets_are_characters_not_words():
    """★ The defect that has already shipped, pinned so it cannot come back.

    `generate_meta_description` once passed 160 into a WORD limiter and returned ~900
    characters. A title of 60 words is not a title of 60 characters, and nothing in the
    reported numbers should be countable in words.
    """
    title = "one two three four five six seven eight nine ten eleven twelve"
    report = analyze_title(title)

    assert report["characters"] == len(title)
    assert report["characters"] != report["words"]
    assert report["budget"] == seo.TITLE_CHAR_BUDGET


def test_the_budgets_are_pinned():
    """A retune should be visible in review, not arrive as drift.

    These are approximations of what a SERP renders — truncation is by pixel width, not
    character count — so they are stated as approximations and changed on purpose.
    """
    assert seo.TITLE_CHAR_BUDGET == 60
    assert seo.TITLE_CHAR_MIN == 30
    assert seo.META_CHAR_BUDGET == 160


def test_characters_are_counted_as_a_serp_would():
    """Collapsed whitespace, trimmed ends — what renders, not what was typed."""
    assert count_characters("  a   title  ") == len("a title")
    assert count_characters("") == 0
    assert count_characters(None) == 0


# ── the verdicts, each carrying its number ─────────────────────────────────────────────

def test_a_title_over_budget_says_by_how_much():
    report = analyze_title(_title(seo.TITLE_CHAR_BUDGET + 7))

    assert report["verdict"] == "long"
    assert report["over_by"] == 7


def test_a_title_within_budget_is_not_flagged():
    report = analyze_title(_title(seo.TITLE_CHAR_BUDGET))

    assert report["verdict"] == "healthy"
    assert report["over_by"] == 0
    assert report["truncated"] is False


def test_a_short_title_is_reported_as_room_not_as_an_error():
    """Under the floor is unused space, not a defect — hence `info`, not `warn`."""
    report = analyze_title(_title(seo.TITLE_CHAR_MIN - 5))
    assert report["verdict"] == "short"

    suggestions = seo._title_suggestions(report)
    length = [item for item in suggestions if item["metric"] == "title_length"]
    assert length and length[0]["severity"] == "info"


def test_every_length_verdict_carries_the_measurement():
    """★ A verdict that hides the number is the tool deciding for the writer."""
    for characters in (seo.TITLE_CHAR_MIN - 5, seo.TITLE_CHAR_BUDGET + 20):
        report = analyze_title(_title(characters))
        issue = next(
            item["issue"] for item in seo._title_suggestions(report)
            if item["metric"] == "title_length"
        )
        assert str(characters) in issue


# ── showing the truncation instead of describing it ────────────────────────────────────

def test_the_preview_shows_which_words_survive():
    long_title = "2025 ChatGPT Case Study Series: Ethics and Accountability in Modern Systems"
    report = analyze_title(long_title)

    assert report["truncated"] is True
    assert report["serp_preview"].endswith("…")
    # Cut at a word boundary — a preview that stops mid-word tells the writer nothing useful.
    assert not report["serp_preview"].rstrip("…").endswith(" ")
    assert long_title.startswith(report["serp_preview"].rstrip("…").rstrip())


def test_the_preview_never_exceeds_the_budget_it_previews():
    preview, truncated = truncate_preview("x" * 200, 60)
    assert truncated is True
    assert len(preview.rstrip("…")) <= 60


def test_a_title_that_fits_is_returned_whole():
    preview, truncated = truncate_preview("A short title", 60)
    assert (preview, truncated) == ("A short title", False)


# ── it must not rewrite ────────────────────────────────────────────────────────────────

def test_the_title_is_reported_back_unchanged():
    """★ The tool points; the writer decides.

    A "suggested title" field would be a rewrite with extra steps — the exact slippage
    `SEO_EDITING_AID_SPEC` §3 warns about. The only transformation permitted is whitespace
    normalisation, which is what a SERP does anyway.
    """
    original = "Ethics  and\n Accountability"
    report = analyze_title(original)

    assert report["title"] == "Ethics and Accountability"
    assert not any(key.startswith("suggested") for key in report)
    assert "rewrite" not in str(report).lower()


# ── the body relationship, stated as consistency rather than ranking ───────────────────

def test_shared_terms_between_title_and_body_are_reported():
    report = analyze_title(
        "How frameworks shape a runtime",
        body_keywords=["frameworks", "runtime", "relationships"],
    )
    assert set(report["shared_keywords"]) == {"frameworks", "runtime"}


def test_a_title_sharing_nothing_with_the_body_is_flagged_as_an_observation():
    """Not a ranking claim — the tool cannot verify one and must not imply it."""
    report = analyze_title("Completely unrelated words", body_keywords=["frameworks"])
    focus = next(
        item for item in seo._title_suggestions(report) if item["metric"] == "title_focus"
    )

    assert focus["severity"] == "info"
    assert "not a ranking claim" in focus["suggestion"]


# ── the optional-ness, which is the compatibility contract ─────────────────────────────

def test_omitting_the_title_leaves_the_analysis_exactly_as_it_was():
    """Every existing caller passes no title; none may see a changed response."""
    result = seo_analysis(BODY, 5)

    assert "title_analysis" not in result
    assert not any(
        item["metric"].startswith("title") for item in result["suggestions"]
    )


def test_a_blank_title_is_the_same_as_no_title():
    """The tool does not nag for a field the writer left empty."""
    for blank in ("", "   ", None):
        assert "title_analysis" not in seo_analysis(BODY, 5, title=blank)


def test_supplying_a_title_adds_the_analysis_and_its_suggestions():
    result = seo_analysis(BODY, 5, title="2025 ChatGPT Case Study Series: Ethics at Length Here")

    assert result["title_analysis"]["characters"] > 0
    assert any(item["metric"].startswith("title") for item in result["suggestions"])


def test_the_title_is_measured_against_the_bodys_own_keywords():
    """The keywords come from the analysis, not from a second pass over the text."""
    result = seo_analysis(BODY, 5, title="How frameworks shape a runtime")

    assert set(result["title_analysis"]["shared_keywords"]) <= set(result["top_keywords"])
    assert "frameworks" in result["title_analysis"]["shared_keywords"]


# ── the meta description now reports what it trimmed to ───────────────────────────────

def test_the_meta_result_reports_its_character_count():
    """★ The number the writer is handed is the point of the feature.

    A meta description is produced by trimming to a budget the writer cannot see. Returning
    the text alone is what let the word/character confusion survive as long as it did: in the
    UI a 900-character result and a 155-character one look identical.
    """
    from apps.search.services.search_service import generate_meta

    result = generate_meta("This is a sentence that will need trimming. " * 30, 160)

    assert result["budget"] == 160
    assert result["characters"] == count_characters(result["meta_description"])
    assert result["characters"] <= 161  # the budget, plus the one-character truncation mark


def test_a_short_meta_description_is_returned_whole_and_counted():
    from apps.search.services.search_service import generate_meta

    result = generate_meta("A short summary of the piece.", 160)

    assert result["meta_description"] == "A short summary of the piece."
    assert result["characters"] == 29
