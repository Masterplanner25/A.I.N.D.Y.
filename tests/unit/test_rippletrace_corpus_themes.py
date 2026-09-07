"""Theme derivation must discount the vocabulary an author uses everywhere.

RippleTrace produced its first three strategies on 2026-09-07 and all three said the same
thing:

    Chatgpt Momentum Play  | Combine chatgpt focus with platform Substack within 25.2 day(s)
    Case Momentum Play     | Combine case  focus with platform Substack within 25.2 day(s)
    Series Momentum Play   | Combine series focus with platform Substack within 25.2 day(s)

`chatgpt`, `case` and `series` are the words shared by "2025 ChatGPT Case Study Series: …",
which prefixes most of the catalogue. Stopword filtering cannot help — these are real words.
What makes them useless is that they appear in *everything the author writes*, and that is
only visible from the corpus, not from one document.

**The threshold comes from the measured distribution, not intuition.** On the live 214-drop
corpus the document frequencies fall into two groups separated by a 5x gap:

    chatgpt 97.7%  case 67.3%  study 66.8%  duality 26.6%  progress 26.6%  series 25.7%
    ------------------------------- gap -------------------------------
    prompt 5.6%  productivity 5.1%  framework 4.2%  business 4.2%  search 3.7%

Everything above the gap is a naming convention; everything below is topical.

This fixes the DERIVED path only. For 168 of 214 drops the themes are publisher tags — labels
the author typed — which is declared intent rather than discovery. That larger question is
RIPPLETRACE-NO-CONTENT-1 and is deliberately not addressed here.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-required-length-1234567890")

pytestmark = pytest.mark.app_profile

content_ingest = pytest.importorskip("apps.rippletrace.services.content_ingest")
derive_themes = content_ingest.derive_themes


def _corpus(prefix: str, subjects: list[str]) -> tuple[dict[str, int], int]:
    """Document frequency for a set of titles sharing a prefix — the real shape."""
    titles = [f"{prefix} {subject}" for subject in subjects]
    frequency: dict[str, int] = {}
    for title in titles:
        seen = {
            word
            for word in title.lower().replace(":", " ").split()
            if len(word) >= 3 and word not in content_ingest._STOPWORDS
        }
        for word in seen:
            frequency[word] = frequency.get(word, 0) + 1
    return frequency, len(titles)


SUBJECTS = [
    "education system", "prompt engineering", "research execution", "learning strategies",
    "business growth", "chain of thought", "ai storytelling", "search frameworks",
    "ethics and trust", "proving the model", "the missing layer", "duality of progress",
    "vibe coding", "creative work", "systems thinking", "execution speed",
]
PREFIX = "2025 ChatGPT Case Study Series:"


# ── the defect ─────────────────────────────────────────────────────────────────────────

def test_template_words_are_dropped_from_a_repetitive_corpus():
    """The exact failure: a title template becoming the theme."""
    corpus_df, corpus_size = _corpus(PREFIX, SUBJECTS)
    themes = derive_themes(
        title=f"{PREFIX} education system",
        summary="",
        tags=[],
        corpus_df=corpus_df,
        corpus_size=corpus_size,
    )

    leaked = set(themes) & {"chatgpt", "case", "study", "series", "2025"}
    assert not leaked, f"title-template words survived as themes: {sorted(leaked)}"


def test_what_survives_actually_distinguishes_the_piece():
    """Removing noise is only useful if signal replaces it."""
    corpus_df, corpus_size = _corpus(PREFIX, SUBJECTS)
    themes = derive_themes(
        title=f"{PREFIX} education system",
        summary="",
        tags=[],
        corpus_df=corpus_df,
        corpus_size=corpus_size,
    )

    assert "education" in themes


def test_two_pieces_from_the_same_series_no_longer_share_every_theme():
    """This is what made three strategies say one thing.

    `influence_graph` links drops by `len(themes_a & themes_b)` and `causal_engine` reports
    `shared_themes` as a causal reason — so identical themes across a catalogue link
    everything to everything.
    """
    corpus_df, corpus_size = _corpus(PREFIX, SUBJECTS)
    kwargs = {"summary": "", "tags": [], "corpus_df": corpus_df, "corpus_size": corpus_size}

    a = set(derive_themes(title=f"{PREFIX} education system", **kwargs))
    b = set(derive_themes(title=f"{PREFIX} prompt engineering", **kwargs))

    assert not (a & b), f"unrelated pieces still share themes: {sorted(a & b)}"


# ── the guards that keep it honest ─────────────────────────────────────────────────────

def test_a_small_corpus_is_left_alone():
    """With few documents, "in 15% of them" means "in one" — which discounts everything."""
    corpus_df, corpus_size = _corpus(PREFIX, SUBJECTS[:4])
    assert corpus_size < content_ingest._MIN_CORPUS_FOR_DISCOUNT

    themes = derive_themes(
        title=f"{PREFIX} education system",
        summary="",
        tags=[],
        corpus_df=corpus_df,
        corpus_size=corpus_size,
    )
    # Unchanged from the no-corpus behaviour: better to report common words than nothing.
    assert themes == derive_themes(title=f"{PREFIX} education system", summary="", tags=[])


def test_no_corpus_behaves_exactly_as_before():
    """Every existing caller passes no corpus; none of them may change behaviour."""
    title = f"{PREFIX} education system"
    assert derive_themes(title=title, summary="", tags=[]) == derive_themes(
        title=title, summary="", tags=[], corpus_df=None, corpus_size=0
    )


def test_a_piece_entirely_on_the_authors_beat_still_gets_themes():
    """Never return nothing.

    An article whose every term is ubiquitous is genuinely on the main beat, and reporting
    its common terms beats reporting silence — an empty theme list would drop it out of the
    influence graph entirely.
    """
    corpus_df, corpus_size = _corpus(PREFIX, SUBJECTS)
    themes = derive_themes(
        title=PREFIX,  # nothing but template words
        summary="",
        tags=[],
        corpus_df=corpus_df,
        corpus_size=corpus_size,
    )
    assert themes, "a beat-only piece was left with no themes at all"


def test_tags_still_win_and_are_never_discounted():
    """Publisher tags bypass derivation entirely — the corpus must not touch them.

    Whether tags SHOULD win is RIPPLETRACE-NO-CONTENT-1's question; this pins that the
    change did not quietly answer it.
    """
    corpus_df, corpus_size = _corpus(PREFIX, SUBJECTS)
    themes = derive_themes(
        title=f"{PREFIX} education system",
        summary="",
        tags=["chatgpt", "case", "productivity"],
        corpus_df=corpus_df,
        corpus_size=corpus_size,
    )
    assert themes == ["chatgpt", "case", "productivity"]


def test_the_threshold_sits_inside_the_measured_gap():
    """Pinned so a retune is deliberate.

    The live corpus separates naming conventions (>= 25.7%) from topical terms (<= 5.6%).
    A threshold outside that band either keeps the template words or eats real themes.
    """
    assert 0.06 < content_ingest.UBIQUITOUS_TERM_RATIO < 0.25
