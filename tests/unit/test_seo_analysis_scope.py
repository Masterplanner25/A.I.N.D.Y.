"""SEO analysis must read the whole article, and must not report stopwords as keywords.

Two defects found 2026-09-06 while the owner was using the tool on a real ~4,000-word draft.
The scorecard it produced:

    Word Count: 507
    Top Keywords: the, it, a, not, that, to, and, was, of, i
    the: 6.52%   it: 2.96%   a: 2.57%

**1. It analysed ~500 words and reported that as the article's length.** `seo_analysis` called
`AINDY.utils.prepare_input_text(text)`, whose signature is
`prepare_input_text(raw_text, limit=500, ...)` — normalize + sanitize + a HARD 500-word cap.
So readability, keyword extraction and every density described the opening pages while being
presented as facts about the whole piece. 507 was the truncation point, not the article.

That is worse than reporting nothing: the numbers look authoritative and there is no signal
that most of the text was never read.

**2. The keyword list had no stopword filter at all.** `extract_keywords` was
`Counter(words).most_common(n)`, which for any English prose returns the English language's
most common words. Not a tuning problem — the step was absent.

These tests pin the observed failures as the specification.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-required-length-1234567890")

pytestmark = pytest.mark.app_profile

seo = pytest.importorskip("apps.search.services.seo_services")

# ~2,700 words — comfortably past the old 500-word cap, comparable to a real article.
_PARAGRAPH = (
    "The conversation became a runtime. Frameworks identify the relevant parts of a system "
    "and establish relationships between them. A formula expresses those relationships in a "
    "repeatable form. An algorithm orders the logic into a process. Code makes that process "
    "precise enough for a machine to execute. "
)
LONG_ARTICLE = _PARAGRAPH * 60


# ── the article must be read in full ───────────────────────────────────────────────────

def test_word_count_is_the_article_not_the_truncation_point():
    """The headline number must describe the submitted text.

    Fails on the old code with ~495 — the cap, reported as the article's length.
    """
    submitted = len(LONG_ARTICLE.split())
    assert submitted > 2000, "fixture too short to exercise the cap"

    result = seo.seo_analysis(LONG_ARTICLE)

    # Tokenisation differs slightly from a naive split, so allow a small margin — but the
    # figure must be the article's order of magnitude, not 500.
    assert result["word_count"] > submitted * 0.9
    assert result["word_count"] > 2000


def test_metrics_reflect_the_whole_article_not_just_the_opening():
    """A term that appears ONLY after the old cap must still be visible to the analysis."""
    marker = "zzmarkerterm"
    article = LONG_ARTICLE + (f" {marker}" * 40)

    keywords = seo.extract_keywords(article, top_n=25)
    terms = [term for term, _ in keywords]

    # The marker sits ~2,700 words in — past the old 500-word cut, so it was previously
    # invisible no matter how often it occurred.
    assert marker in terms


def test_a_short_article_is_unaffected():
    """The fix must not change behaviour for text that was never truncated."""
    short = _PARAGRAPH * 3
    result = seo.seo_analysis(short)

    assert result["word_count"] == pytest.approx(len(short.split()), rel=0.1)
    assert "truncated" not in result


def test_an_enormous_paste_is_bounded_but_says_so():
    """A bound still exists — but it is reported, never silent.

    The original defect was not the cap, it was that the cap was invisible and the truncated
    count was presented as the article's length.
    """
    huge = _PARAGRAPH * (seo._MAX_ANALYSIS_WORDS // 10)
    assert len(huge.split()) > seo._MAX_ANALYSIS_WORDS

    result = seo.seo_analysis(huge)

    assert result["truncated"] is True
    assert result["submitted_word_count"] > seo._MAX_ANALYSIS_WORDS
    assert result["analyzed_word_count"] <= seo._MAX_ANALYSIS_WORDS
    # And the caller can tell how much was actually read.
    assert result["submitted_word_count"] > result["analyzed_word_count"]


def test_the_bound_is_far_above_any_real_article():
    """A cap that a normal article can reach is the bug again with a bigger number."""
    assert seo._MAX_ANALYSIS_WORDS >= 20_000


# ── keywords must be keywords ──────────────────────────────────────────────────────────

def test_stopwords_are_not_reported_as_keywords():
    """The exact failure from the owner's scorecard: 'the', 'it', 'a', 'to', 'and', 'of'."""
    keywords = seo.extract_keywords(LONG_ARTICLE, top_n=10)
    terms = {term for term, _ in keywords}

    leaked = terms & {"the", "it", "a", "not", "that", "to", "and", "was", "of", "i"}
    assert not leaked, f"stopwords reported as keywords: {sorted(leaked)}"


def test_content_words_surface_instead():
    """Removing stopwords is only useful if what replaces them is meaningful."""
    terms = [term for term, _ in seo.extract_keywords(LONG_ARTICLE, top_n=10)]

    assert any(t in terms for t in ("frameworks", "relationships", "process", "runtime")), (
        f"no topical terms in {terms}"
    )


def test_single_characters_are_dropped():
    """'i' and 'a' survive tokenisation and carry no topical signal."""
    terms = [term for term, _ in seo.extract_keywords("I a b c framework framework framework")]
    assert "i" not in terms and "a" not in terms
    assert "framework" in terms


def test_stopwords_can_still_be_requested_explicitly():
    """The filter is a default, not a capability removal — density checks may want them."""
    terms = [term for term, _ in seo.extract_keywords(LONG_ARTICLE, top_n=5, include_stopwords=True)]
    assert "the" in terms


def test_the_top_keyword_density_is_no_longer_dominated_by_stopwords():
    """'the: 6.52%' as the headline density is what made the scorecard unusable."""
    result = seo.seo_analysis(LONG_ARTICLE)
    densities = result["keyword_densities"]

    assert densities, "no densities computed"
    assert "the" not in densities
    # Real content terms sit at low single-digit percentages; a 6%+ headline density is the
    # signature of a stopword having won.
    assert max(densities.values()) < 6.0
