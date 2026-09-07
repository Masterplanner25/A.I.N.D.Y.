"""Coverage against intent, and the repetition a writer cannot see in their own draft.

Two features from `docs/specs/SEO_EDITING_AID_SPEC.md`, §2 and §3, both from the owner:

> *"We either need to put a field in for what we want the keywords to be… and a count of word
> density / repeated words — as that seems to be the bigger issue there (as far as a human
> needing assistance with AI-generated writing)."*

**§2 changes the question the tool asks.** Today it answers *"what words appear most often in
this text?"* — which for English prose has a known and useless answer, and only slightly less
useless once stopwords are removed. With target terms supplied it answers *"am I actually
covering what I am trying to rank for?"*, which is the question an SEO editing aid exists for.

**§3 is the feature with the clearest use.** AI-assisted prose has a repetition signature — the
same connective phrasing, the same sentence openers, a favourite noun every few paragraphs —
and it is nearly invisible to the person who just wrote it. Surfacing it is the tool doing
something a writer genuinely cannot do for themselves by re-reading.

★ **Two rules run through every function here.**

*Show the number.* Thresholds are claims about search engines this tool cannot verify. Every
verdict is reported alongside the measurement and the threshold that produced it — a verdict
that hides the density is the tool deciding for the writer (§2).

*Point, never rewrite.* No suggested replacement text, anywhere. The owner considered rewriting
and rejected it as defeating the purpose, and slippage here would be gradual: a "suggested
phrasing" field is a rewrite with extra steps (§3).
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections import Counter

from apps.search.services.seo_services import (
    _KEYWORD_STUFFING_PCT,
    _STOPWORDS,
    _WEAK_FOCUS_PCT,
    _tokenize_words,
)

# How much of the article counts as "the opening". A term at 1.5% spread evenly through the
# body is a different article from the same term appearing only in paragraph 40, and the writer
# can act on the difference (§2).
OPENING_WORDS = 100

# ── Repetition tuning ─────────────────────────────────────────────────────────────────
#
# ★ Relative to the article's own distribution, not to an absolute count. "Appears 8 times" is
# meaningless without knowing the length: 8 in 400 words is a tic, 8 in 8,000 is nothing. So a
# word is overused when it stands out against the article's OWN typical repeated-word count.
MIN_REPEATS_CONSIDERED = 3      # below this there is no pattern to see
# Twice the median, measured 2026-09-07 rather than guessed. At 2.5 a flat distribution hides
# its own outlier: an article with five words used 4 times each and one used 8 has a median of
# 4 and a cutoff of 10, so the word that is plainly twice as common as everything else is not
# reported. 2.0 catches it, and the long-article case still stays quiet because the median
# rises with the article.
OVERUSE_RATIO = 2.0             # times the median count among repeated content words

# 2–4 words is where the AI-writing signature actually lives. Single-word repetition is often
# legitimate topical focus, which is why it is measured separately and against a ratio.
MIN_PHRASE_WORDS = 2
MAX_PHRASE_WORDS = 4
MIN_PHRASE_OCCURRENCES = 2

# How many sentences must share an opener before it is worth mentioning, and the share of the
# article at which it becomes a pattern rather than a coincidence.
MIN_OPENER_REPEATS = 3

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])[\s—]+")
_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")
_MARKDOWN_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$", re.MULTILINE)


def _content_words(tokens: list[str]) -> list[str]:
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 1]


def _phrase_tokens(phrase: str) -> list[str]:
    return [t for t in _tokenize_words(phrase.lower()) if t.isalnum()]


def _count_sequence(tokens: list[str], needle: list[str]) -> list[int]:
    """Index of every position where `needle` occurs in `tokens`.

    Sequence matching, not substring matching: "run time" must not match "runtime", and
    "the runtime" must not be found inside "in the runtimes of". Positions are returned rather
    than a count because §2 and §3 both need to say *where*, not only *how many*.
    """
    if not needle or len(needle) > len(tokens):
        return []
    width = len(needle)
    first = needle[0]
    return [
        index
        for index, token in enumerate(tokens)
        if token == first and tokens[index:index + width] == needle
    ]


def headings(text: str) -> list[str]:
    """Markdown headings only, and deliberately nothing cleverer.

    ★ A short line with no full stop is *usually* a heading and sometimes a line of dialogue,
    a list item or a signature. Guessing produces a confident "not in any heading" for an
    article that has headings the parser did not recognise, which is worse than saying nothing.
    Callers report `headings_found` so the writer can tell an answer from an absence.
    """
    return [match.strip() for match in _MARKDOWN_HEADING.findall(text or "")]


# ── §2 Coverage against intent ────────────────────────────────────────────────────────

def keyword_coverage(
    text: str, targets: list[str] | None, *, title: str | None = None
) -> dict:
    """How well the draft covers the terms the writer is aiming at.

    Density for a multi-word phrase counts the words the phrase occupies — three uses of a
    three-word phrase is nine words of the article, not three. Reporting it any other way makes
    a phrase look nine times thinner than a single word used equally often.
    """
    cleaned_targets = [t.strip() for t in (targets or []) if t and t.strip()]
    if not cleaned_targets:
        return {"targets": [], "count": 0}

    tokens = [t for t in _tokenize_words((text or "").lower()) if t.isalnum()]
    total = len(tokens)
    heading_text = " ".join(headings(text)).lower()
    heading_count = len(headings(text))
    title_lower = (title or "").lower()

    reports = []
    for target in cleaned_targets:
        needle = _phrase_tokens(target)
        positions = _count_sequence(tokens, needle)
        occurrences = len(positions)
        words_used = occurrences * max(1, len(needle))
        density = round((words_used / total) * 100, 2) if total else 0.0

        if occurrences == 0:
            verdict = "absent"
        elif density > _KEYWORD_STUFFING_PCT:
            verdict = "overused"
        elif density < _WEAK_FOCUS_PCT:
            verdict = "thin"
        else:
            verdict = "healthy"

        reports.append({
            "term": target.strip(),
            "occurrences": occurrences,
            "density": density,
            "verdict": verdict,
            # ★ Shipped with the verdict, never instead of it. A reader who disagrees with the
            # threshold can see the number it was applied to and decide for themselves.
            "thresholds": {"thin_below": _WEAK_FOCUS_PCT, "overused_above": _KEYWORD_STUFFING_PCT},
            # The first occurrence, not "any word of the phrase appears early" — a term whose
            # component words happen to show up in the opening has not been used there.
            "in_opening": bool(positions) and positions[0] < OPENING_WORDS,
            # None, not False, when the article has no headings this parser can see: "we looked
            # and it is not there" and "we could not look" are different answers.
            "in_heading": (all(word in heading_text for word in needle)
                           if heading_count else None),
            "in_title": (all(word in title_lower for word in needle)
                         if title_lower else None),
        })

    return {
        "targets": reports,
        "count": len(reports),
        "headings_found": heading_count,
        "opening_words": OPENING_WORDS,
    }


# ── §3 Repetition ─────────────────────────────────────────────────────────────────────

def _paragraph_index(offsets: list[int], position: int) -> int:
    """Which paragraph a token position falls in, given each paragraph's start offset.

    `bisect` rather than a scan with `.index()`: consecutive empty paragraphs produce repeated
    offsets, and `.index()` returns the first match for all of them, so several paragraphs
    would collapse into one and `clustered` would read as true when it is not.
    """
    return max(0, bisect_right(offsets, position) - 1)


def repetition_report(text: str) -> dict:
    """Repeated phrasing, sentence openers and overused words — with positions.

    ★ Position is why this is not just a word counter. Three uses spread across 4,000 words is
    fine; three in one paragraph is a thing to fix, and a count alone cannot tell them apart.
    """
    body = text or ""
    paragraphs = [p for p in _PARAGRAPH_SPLIT.split(body) if p.strip()]
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(body) if s.strip()]

    tokens = [t for t in _tokenize_words(body.lower()) if t.isalnum()]
    # Token offset at which each paragraph starts, so a phrase position maps to a paragraph.
    offsets: list[int] = []
    running = 0
    for paragraph in paragraphs:
        offsets.append(running)
        running += len([t for t in _tokenize_words(paragraph.lower()) if t.isalnum()])

    return {
        "repeated_phrases": _repeated_phrases(tokens, offsets),
        "sentence_openers": _sentence_openers(sentences),
        "overused_words": _overused_words(tokens),
        "sentence_count": len(sentences),
        "paragraph_count": len(paragraphs),
    }


def _repeated_phrases(tokens: list[str], offsets: list[int]) -> list[dict]:
    """2–4 word sequences used more than once, longest first.

    A longer phrase contains shorter ones, so "the whole thing is" would also report "the
    whole", "whole thing", "the whole thing" and so on. Only the longest phrase at each start
    position is kept — otherwise one tic is reported as six findings.
    """
    found: dict[tuple[str, ...], list[int]] = {}
    # ★ Token positions already claimed by an accepted phrase. Without this, one tic is
    # reported as several findings: "it is a framework for runtimes" yields "it is a framework",
    # "is a framework for" and "a framework for runtimes" as three separate 4-grams, none of
    # which contains another. Claiming spans widest-first keeps the longest form and drops the
    # overlapping fragments of the same repetition.
    covered: set[int] = set()

    for width in range(MAX_PHRASE_WORDS, MIN_PHRASE_WORDS - 1, -1):
        counts: dict[tuple[str, ...], list[int]] = {}
        for index in range(len(tokens) - width + 1):
            counts.setdefault(tuple(tokens[index:index + width]), []).append(index)
        # Most-repeated first, so the strongest pattern claims its span before its neighbours.
        for phrase, positions in sorted(counts.items(), key=lambda kv: -len(kv[1])):
            if len(positions) < MIN_PHRASE_OCCURRENCES:
                continue
            # A phrase made only of stopwords is grammar, not a tic.
            if all(word in _STOPWORDS for word in phrase):
                continue
            fresh = [
                start for start in positions
                if not covered & set(range(start, start + width))
            ]
            if len(fresh) < MIN_PHRASE_OCCURRENCES:
                continue
            found[phrase] = fresh
            covered |= _expand(fresh, width)

    reports = []
    for phrase, positions in found.items():
        paragraph_indices = sorted({_paragraph_index(offsets, p) for p in positions})
        reports.append({
            "phrase": " ".join(phrase),
            "words": len(phrase),
            "occurrences": len(positions),
            "paragraphs": paragraph_indices,
            # ★ Two uses in the same paragraph read as a tic; two chapters apart do not.
            "clustered": len(paragraph_indices) < len(positions),
        })
    reports.sort(key=lambda item: (-item["occurrences"], -item["words"], item["phrase"]))
    return reports


def _expand(positions: list[int], width: int) -> set[int]:
    return {p + offset for p in positions for offset in range(width)}


def _sentence_openers(sentences: list[str]) -> list[dict]:
    """How many sentences begin the same way.

    The article that prompted this spec opens many consecutive sentences with "It" and "That"
    — a pattern the writer cannot see because each sentence reads fine on its own.
    """
    openers = Counter()
    for sentence in sentences:
        words = _tokenize_words(sentence)
        if words:
            openers[words[0].lower()] += 1

    total = len(sentences) or 1
    return sorted(
        (
            {
                "opener": opener,
                "count": count,
                "share": round(count / total * 100, 1),
            }
            for opener, count in openers.items()
            if count >= MIN_OPENER_REPEATS
        ),
        key=lambda item: -item["count"],
    )


def _overused_words(tokens: list[str]) -> list[dict]:
    """Content words standing out against the article's own repetition, not a fixed count.

    "Appears 8 times" says nothing without the length: 8 in 400 words is a tic, 8 in 8,000 is
    nothing. So the comparison is against the median count among this article's own repeated
    content words — a threshold the article sets for itself.
    """
    counts = Counter(_content_words(tokens))
    repeated = sorted(c for c in counts.values() if c >= MIN_REPEATS_CONSIDERED)
    if not repeated:
        return []

    median = repeated[len(repeated) // 2]
    cutoff = max(MIN_REPEATS_CONSIDERED, median * OVERUSE_RATIO)
    total = len(tokens) or 1

    return sorted(
        (
            {
                "word": word,
                "occurrences": count,
                "density": round(count / total * 100, 2),
                # Shown so the writer can see what the word is being compared against, rather
                # than being handed a verdict from a number they cannot inspect.
                "article_median": median,
                "times_median": round(count / median, 1) if median else 0.0,
            }
            for word, count in counts.items()
            if count >= cutoff
        ),
        key=lambda item: -item["occurrences"],
    )
