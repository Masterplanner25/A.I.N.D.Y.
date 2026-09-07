"""Coverage against intent, and the repetition a writer cannot see in their own draft.

`SEO_EDITING_AID_SPEC` §2 and §3, both from the owner:

> *"We either need to put a field in for what we want the keywords to be… and a count of word
> density / repeated words — as that seems to be the bigger issue there (as far as a human
> needing assistance with AI-generated writing)."*

★ **Two rules are pinned in almost every test below**, because both are easy to lose slowly:

*Show the number.* Thresholds are claims about search engines this tool cannot verify, so every
verdict travels with the measurement AND the threshold applied to it. A verdict that hides the
density is the tool deciding for the writer.

*Point, never rewrite.* No suggested replacement text anywhere. The owner considered rewriting
and rejected it as defeating the purpose — and the slippage would be gradual, because a
"suggested phrasing" field looks like a helpful addition rather than a change of job.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-required-length-1234567890")

pytestmark = pytest.mark.app_profile

aid = pytest.importorskip("apps.search.services.editing_aid")
seo = pytest.importorskip("apps.search.services.seo_services")

keyword_coverage = aid.keyword_coverage
repetition_report = aid.repetition_report

ARTICLE = """# The Runtime Framework

It is a framework for runtimes. It turns out that the runtime framework matters.
That is the point. That is why the runtime framework exists.

## Why it matters

It is a framework for runtimes and it is worth saying again. The runtime framework
is what everything else is built on. That is the whole argument.
"""

FILLER = "Some ordinary prose about unrelated matters goes here for length. " * 60


# ── §2 the question changes when targets are supplied ─────────────────────────────────

def test_no_targets_means_no_coverage_report():
    """Absent, the tool behaves exactly as it did — discovered keywords only."""
    for empty in (None, [], ["", "   "]):
        assert keyword_coverage(ARTICLE, empty) == {"targets": [], "count": 0}


def test_a_target_that_is_absent_is_named_as_absent():
    report = keyword_coverage(ARTICLE, ["nodus"])["targets"][0]

    assert report["verdict"] == "absent"
    assert report["occurrences"] == 0


def test_a_phrase_is_matched_as_a_sequence_not_as_loose_words():
    """★ "runtime framework" is a different target from "runtime" and "framework".

    Counting the words separately would report coverage for a phrase the article never uses.
    """
    text = "The framework is good. The runtime is fast. " + FILLER

    assert keyword_coverage(text, ["runtime framework"])["targets"][0]["occurrences"] == 0
    assert keyword_coverage(text, ["runtime"])["targets"][0]["occurrences"] == 1


def test_a_phrase_is_not_found_inside_a_longer_word():
    """Token matching, not substring: "run time" must not match "runtime"."""
    assert keyword_coverage("runtimes everywhere. " + FILLER, ["run time"])["targets"][0][
        "occurrences"
    ] == 0


def test_density_counts_the_words_a_phrase_occupies():
    """★ Three uses of a three-word phrase is nine words of the article, not three.

    Reporting it any other way makes a phrase look three times thinner than a single word used
    equally often, and the writer would read that as needing more of it.
    """
    text = "alpha beta gamma " * 5 + FILLER
    report = keyword_coverage(text, ["alpha beta gamma"])["targets"][0]
    single = keyword_coverage(text, ["alpha"])["targets"][0]

    assert report["occurrences"] == single["occurrences"] == 5
    assert report["density"] == pytest.approx(single["density"] * 3, rel=0.01)


# ── the verdict never arrives without its number ──────────────────────────────────────

def test_every_target_carries_its_density_and_the_thresholds_applied():
    """★ A verdict that hides the number is the tool deciding for the writer."""
    report = keyword_coverage(ARTICLE, ["runtime framework"])["targets"][0]

    assert isinstance(report["density"], float)
    assert report["thresholds"] == {
        "thin_below": seo._WEAK_FOCUS_PCT,
        "overused_above": seo._KEYWORD_STUFFING_PCT,
    }


def test_the_verdicts_follow_the_thresholds_they_report():
    heavy = keyword_coverage("alpha " * 40 + "other words here", ["alpha"])["targets"][0]
    thin = keyword_coverage("alpha " + FILLER, ["alpha"])["targets"][0]

    assert heavy["verdict"] == "overused"
    assert heavy["density"] > heavy["thresholds"]["overused_above"]
    assert thin["verdict"] == "thin"
    assert thin["density"] < thin["thresholds"]["thin_below"]


# ── placement, which a count alone cannot express ─────────────────────────────────────

def test_placement_distinguishes_an_opening_use_from_a_late_one():
    """A term at 1.5% spread evenly is a different article from the same term in paragraph 40."""
    early = keyword_coverage("alpha appears immediately. " + FILLER, ["alpha"])["targets"][0]
    late = keyword_coverage(FILLER + " and finally alpha.", ["alpha"])["targets"][0]

    assert early["in_opening"] is True
    assert late["in_opening"] is False


def test_a_word_that_merely_appears_early_is_not_a_use_of_the_phrase():
    """`in_opening` is about the phrase, not about its component words."""
    text = "framework in the opening line. " + FILLER + " runtime framework at the end."
    report = keyword_coverage(text, ["runtime framework"])["targets"][0]

    assert report["occurrences"] == 1
    assert report["in_opening"] is False


def test_heading_presence_is_reported_when_there_are_headings():
    report = keyword_coverage(ARTICLE, ["runtime framework"])["targets"][0]
    assert report["in_heading"] is True


def test_heading_presence_is_unknown_rather_than_false_without_headings():
    """★ "We looked and it is not there" and "we could not look" are different answers.

    The parser reads markdown headings and deliberately nothing cleverer — a short line with no
    full stop is usually a heading and sometimes a list item or a signature. Returning False for
    an article whose headings it cannot see would be a confident wrong answer.
    """
    coverage = keyword_coverage("Plain prose with no headings. alpha. " + FILLER, ["alpha"])

    assert coverage["headings_found"] == 0
    assert coverage["targets"][0]["in_heading"] is None


def test_title_presence_is_unknown_when_no_title_was_supplied():
    assert keyword_coverage(ARTICLE, ["alpha"])["targets"][0]["in_title"] is None
    assert keyword_coverage(ARTICLE, ["runtime"], title="The Runtime Framework")["targets"][0][
        "in_title"
    ] is True


# ── §3 repetition ─────────────────────────────────────────────────────────────────────

def test_a_repeated_phrase_is_found_with_its_count():
    phrases = {p["phrase"]: p for p in repetition_report(ARTICLE)["repeated_phrases"]}

    assert "the runtime framework" in phrases
    assert phrases["the runtime framework"]["occurrences"] == 4


def test_one_tic_is_reported_once_not_as_every_overlapping_fragment():
    """★ The finding that made this worth writing carefully.

    "it is a framework for runtimes" yields "it is a framework", "is a framework for" and
    "a framework for runtimes" as three distinct 4-grams, none of which contains another. A
    naive n-gram count reports one habit as six findings and buries the real signal.
    """
    text = "It is a framework for runtimes. " * 3 + FILLER
    phrases = [p["phrase"] for p in repetition_report(text)["repeated_phrases"]]

    overlapping = [p for p in phrases if "framework" in p]
    assert len(overlapping) == 1, f"one repetition reported as {len(overlapping)}: {overlapping}"


def test_position_separates_a_tic_from_a_theme():
    """★ Three uses across 4,000 words is fine; three in one paragraph is a thing to fix.

    A count alone cannot tell them apart, which is why paragraphs are reported.
    """
    clustered = "The same phrase here. The same phrase here.\n\n" + FILLER
    spread = "The same phrase here.\n\n" + FILLER + "\n\nThe same phrase here."

    def _find(text):
        return next(
            p for p in repetition_report(text)["repeated_phrases"] if "same phrase" in p["phrase"]
        )

    assert _find(clustered)["clustered"] is True
    assert _find(spread)["clustered"] is False


def test_pure_stopword_phrases_are_grammar_not_a_tic():
    """"of the" repeating is English, not a habit worth reporting."""
    text = "Some of the things of the world of the sort. " * 4 + FILLER
    phrases = [p["phrase"] for p in repetition_report(text)["repeated_phrases"]]

    assert "of the" not in phrases


def test_a_phrase_used_once_is_not_repetition():
    assert repetition_report("A completely unique sentence. " + FILLER)["repeated_phrases"] == [] or all(
        p["occurrences"] >= aid.MIN_PHRASE_OCCURRENCES
        for p in repetition_report("A completely unique sentence. " + FILLER)["repeated_phrases"]
    )


def test_sentence_openers_are_counted_with_their_share():
    """The article that prompted this opens many consecutive sentences with "It" and "That"."""
    openers = {o["opener"]: o for o in repetition_report(ARTICLE)["sentence_openers"]}

    assert openers["that"]["count"] == 3
    assert 0 < openers["that"]["share"] <= 100


def test_a_rare_opener_is_not_reported():
    text = "Alpha begins. Beta begins. Gamma begins. Delta begins. Epsilon begins."
    assert repetition_report(text)["sentence_openers"] == []


def test_overuse_is_measured_against_the_article_not_a_fixed_count():
    """★ "Appears 8 times" is meaningless without the length.

    8 in 400 words is a tic; 8 in 8,000 is nothing. The comparison is against the median count
    among this article's own repeated content words — a threshold the article sets for itself.
    """
    short = "alpha " * 8 + "beta gamma delta epsilon zeta " * 4
    long = "alpha " * 8 + "beta gamma delta epsilon zeta " * 400

    short_words = {w["word"] for w in repetition_report(short)["overused_words"]}
    long_words = {w["word"] for w in repetition_report(long)["overused_words"]}

    assert "alpha" in short_words
    assert "alpha" not in long_words


def test_an_overused_word_shows_what_it_was_compared_against():
    """Not a bare verdict — the writer can see the article's own median and the ratio."""
    report = repetition_report("alpha " * 12 + "beta gamma delta epsilon " * 3)
    if report["overused_words"]:
        entry = report["overused_words"][0]
        assert {"occurrences", "density", "article_median", "times_median"} <= set(entry)


# ── it points, it does not rewrite ────────────────────────────────────────────────────

def test_nothing_in_the_report_is_replacement_text():
    """★ No "suggested phrasing" field, anywhere.

    The owner considered rewriting and rejected it. Slippage here would be gradual and would
    look like a helpful addition rather than a change of job, so this asserts the absence.
    """
    report = repetition_report(ARTICLE)
    coverage = keyword_coverage(ARTICLE, ["runtime framework"])

    forbidden = {"replacement", "suggested_phrase", "rewrite", "instead", "alternative"}
    for blob in (report, coverage):
        assert not (forbidden & set(blob))
        for item in blob.get("repeated_phrases", []) + blob.get("targets", []):
            assert not (forbidden & set(item))


def test_the_repetition_suggestions_point_rather_than_supply_wording():
    suggestions = seo._repetition_suggestions(repetition_report(ARTICLE))

    assert suggestions
    for item in suggestions:
        assert "instead of" not in item["suggestion"].lower()
        assert "try:" not in item["suggestion"].lower()


# ── the analysis wiring ───────────────────────────────────────────────────────────────

def test_repetition_is_always_computed_because_it_needs_no_new_input():
    result = seo.seo_analysis(ARTICLE, 5)

    assert "repetition" in result
    assert "keyword_coverage" not in result


def test_targets_add_coverage_and_its_suggestions():
    result = seo.seo_analysis(ARTICLE, 5, target_keywords=["runtime framework", "nodus"])

    assert result["keyword_coverage"]["count"] == 2
    metrics = {item["metric"] for item in result["suggestions"]}
    assert "target_coverage" in metrics


def test_a_coverage_suggestion_states_the_density_and_the_threshold():
    result = seo.seo_analysis(ARTICLE, 5, target_keywords=["runtime framework"])
    issue = next(
        item["issue"] for item in result["suggestions"] if item["metric"] == "target_coverage"
    )

    assert "%" in issue


def test_discovered_keywords_are_still_reported_alongside_targets():
    """Both questions are worth an answer.

    What the draft is *actually* about is still useful next to what it *aims* at — and the gap
    between the two is often the finding.
    """
    result = seo.seo_analysis(ARTICLE, 5, target_keywords=["nodus"])

    assert result["top_keywords"]
    assert result["keyword_coverage"]["targets"][0]["verdict"] == "absent"
