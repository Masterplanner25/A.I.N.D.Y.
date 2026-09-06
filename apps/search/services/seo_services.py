from __future__ import annotations

from collections import Counter
import logging
import re

import nltk
import textstat

from AINDY.utils import normalize_encoding, sanitize_text

logger = logging.getLogger(__name__)

# ── Why this file no longer calls prepare_input_text ───────────────────────────────────
#
# `AINDY.utils.prepare_input_text(raw_text, limit=500, ...)` is normalize + sanitize +
# **enforce_word_limit**, and that third step defaults to a HARD 500-WORD CAP. `seo_analysis`
# called it with the default, so every article was silently truncated to ~500 words before a
# single metric was computed — and the truncated count was then reported as `word_count`, as
# though it described the whole piece.
#
# Measured 2026-09-06 on a 2760-word article: 495 words analysed (17.9%), reported as
# `word_count: 495`. A real ~4,000-word draft reported 507. Readability, keyword extraction
# and every density were computed on the opening pages and presented as facts about the
# article. That is worse than reporting nothing, because the numbers look authoritative.
#
# Analysis needs normalisation and sanitisation but must NOT be length-limited, so the two
# useful steps are called directly. A bound still exists (`_MAX_ANALYSIS_WORDS`) because an
# unbounded paste is a real cost — but it is ~100x larger and, crucially, is REPORTED when it
# bites (`truncated` / `analyzed_word_count`) instead of quietly changing the answer.
_MAX_ANALYSIS_WORDS = 50_000


def _prepare_for_analysis(text: str) -> tuple[str, int, bool]:
    """Normalise + sanitise without a word cap. Returns (text, full_word_count, truncated)."""
    cleaned = sanitize_text(normalize_encoding(text or ""))
    words = cleaned.split()
    full_count = len(words)
    if full_count <= _MAX_ANALYSIS_WORDS:
        return cleaned, full_count, False
    return " ".join(words[:_MAX_ANALYSIS_WORDS]), full_count, True
_TOKENIZER_AVAILABLE: bool | None = None


def _ensure_tokenizer() -> bool:
    global _TOKENIZER_AVAILABLE
    if _TOKENIZER_AVAILABLE is not None:
        return _TOKENIZER_AVAILABLE
    try:
        nltk.data.find("tokenizers/punkt")
        _TOKENIZER_AVAILABLE = True
    except LookupError:
        logger.warning("NLTK punkt tokenizer not available; using regex fallback for SEO tokenization")
        _TOKENIZER_AVAILABLE = False
    return _TOKENIZER_AVAILABLE


def _tokenize_words(text: str) -> list[str]:
    normalized = (text or "").strip()
    if not normalized:
        return []
    if _ensure_tokenizer():
        try:
            return list(nltk.word_tokenize(normalized))
        except LookupError:
            logger.warning("NLTK tokenizer lookup failed at runtime; falling back to regex tokenization")
        except Exception as exc:
            logger.warning("NLTK tokenization failed; falling back to regex tokenization: %s", exc)
    return re.findall(r"\b\w+\b", normalized)


# ── Stopwords ──────────────────────────────────────────────────────────────────────────
#
# `extract_keywords` was `Counter(words).most_common(n)` with NO stopword filtering, so for
# any English prose it returned the English language's most common words. A real scorecard
# from 2026-09-06:
#
#   Top Keywords: the, it, a, not, that, to, and, was, of, i
#   the: 6.52%   it: 2.96%   a: 2.57%
#
# That is a stopword frequency table, not a keyword list, and no amount of tuning changes it —
# the filtering step was simply absent.
#
# The list is inline rather than `nltk.corpus.stopwords` on purpose: NLTK's data is NOT
# downloaded in this deployment (`_ensure_tokenizer` already falls back to regex for exactly
# this reason), so an NLTK-backed filter would silently no-op in production and pass in any
# environment where a developer happened to have the corpus. An explicit list behaves the same
# everywhere and is testable.
_STOPWORDS = frozenset("""
a about above after again against all am an and any are aren as at
be because been before being below between both but by
can cant cannot could couldnt
did didnt do does doesnt doing dont down during
each few for from further
had hadnt has hasnt have havent having he hed hes her here hers herself him himself his how
i id ill im ive if in into is isnt it its itself
just
lets
me more most mustnt my myself
no nor not now
of off on once only or other ought our ours ourselves out over own
same shant she shed shes should shouldnt so some such
than that thats the their theirs them themselves then there theres these they theyd theyll
theyre theyve this those through to too
under until up
very
was wasnt we wed well were weve werent what whats when whens where wheres which while who
whos whom why whys with wont would wouldnt
you youd youll youre youve your yours yourself yourselves
""".split())


def extract_keywords(text: str, top_n: int = 10, *, include_stopwords: bool = False):
    """Most frequent meaningful terms. Stopwords are excluded unless explicitly requested."""
    words = _tokenize_words(text.lower())
    words = [word for word in words if word.isalnum()]
    if not include_stopwords:
        # Single characters go too: "i", "a" survive as tokens and carry no topical signal.
        words = [w for w in words if w not in _STOPWORDS and len(w) > 1]
    freq_dist = Counter(words)
    return freq_dist.most_common(top_n)


def keyword_density(text: str, keyword: str):
    words = [word for word in _tokenize_words(text.lower()) if word.isalnum()]
    if not words:
        return 0.0
    return round((words.count(keyword.lower()) / len(words)) * 100, 2)


# Thresholds for SEO improvement suggestions (Search v4 §3.1).
_MIN_WORD_COUNT = 300           # thin-content floor
_READABILITY_HARD = 30.0        # Flesch reading ease below this = very hard to read
_READABILITY_DIFFICULT = 50.0   # below this = fairly difficult
_KEYWORD_STUFFING_PCT = 4.0     # single-keyword density above this = stuffing risk
_WEAK_FOCUS_PCT = 0.5           # top keyword density below this = weak topical focus


def seo_improvement_suggestions(analysis: dict) -> list[dict]:
    """Actionable SEO improvement suggestions derived from a ``seo_analysis`` result.

    Deterministic heuristics over the computed metrics (no LLM, no network). Each
    item: ``{metric, issue, suggestion, severity}`` (severity: "warn" | "info").
    Returns a single "healthy" info item when nothing is flagged.
    """
    suggestions: list[dict] = []
    word_count = int(analysis.get("word_count") or 0)
    readability = analysis.get("readability")
    densities = analysis.get("keyword_densities") or {}
    top_keywords = analysis.get("top_keywords") or []

    if word_count < _MIN_WORD_COUNT:
        suggestions.append({
            "metric": "word_count",
            "issue": f"Thin content ({word_count} words).",
            "suggestion": f"Expand to at least {_MIN_WORD_COUNT} words — thin pages rank poorly.",
            "severity": "warn",
        })

    if isinstance(readability, (int, float)):
        if readability < _READABILITY_HARD:
            suggestions.append({
                "metric": "readability",
                "issue": f"Very hard to read (Flesch {round(readability, 1)}).",
                "suggestion": "Shorten sentences and simplify wording to lift readability.",
                "severity": "warn",
            })
        elif readability < _READABILITY_DIFFICULT:
            suggestions.append({
                "metric": "readability",
                "issue": f"Fairly difficult to read (Flesch {round(readability, 1)}).",
                "suggestion": "Consider simpler phrasing for a broader audience.",
                "severity": "info",
            })

    for keyword, density in densities.items():
        if isinstance(density, (int, float)) and density > _KEYWORD_STUFFING_PCT:
            suggestions.append({
                "metric": "keyword_density",
                "issue": f"'{keyword}' density is {density}%.",
                "suggestion": f"Reduce use of '{keyword}' — over {_KEYWORD_STUFFING_PCT}% risks keyword-stuffing penalties.",
                "severity": "warn",
            })

    if not top_keywords:
        suggestions.append({
            "metric": "keywords",
            "issue": "No substantive keywords detected.",
            "suggestion": "Add keyword-rich, topical content so search engines can classify the page.",
            "severity": "warn",
        })
    elif densities:
        max_density = max((d for d in densities.values() if isinstance(d, (int, float))), default=0.0)
        if max_density < _WEAK_FOCUS_PCT:
            suggestions.append({
                "metric": "keyword_focus",
                "issue": f"Weak primary-keyword focus (top density {max_density}%).",
                "suggestion": "Reinforce your main keyword so search engines can identify the topic.",
                "severity": "info",
            })

    if not suggestions:
        suggestions.append({
            "metric": "overall",
            "issue": "No issues detected.",
            "suggestion": "SEO signals look healthy — keep content fresh and on-topic.",
            "severity": "info",
        })
    return suggestions


def seo_analysis(text: str, top_n: int = 10):
    """Performs a basic SEO analysis on given text, with improvement suggestions.

    ★ Analyses the WHOLE article. This used to call `prepare_input_text`, whose `limit`
    defaults to 500 words, so every metric below described only the opening ~500 words while
    being reported as though it described the article. See the note at the top of this file.
    """
    prepared_text, full_word_count, truncated = _prepare_for_analysis(text)
    words = _tokenize_words(prepared_text)
    word_count = len(words)
    readability = textstat.flesch_reading_ease(prepared_text)
    keywords = extract_keywords(prepared_text, top_n)
    densities = {kw[0]: keyword_density(prepared_text, kw[0]) for kw in keywords}
    result = {
        # The article's real length, not the analysed slice. These differ only past
        # `_MAX_ANALYSIS_WORDS`, and when they do the caller is told rather than left to
        # believe a truncated figure.
        "word_count": word_count,
        "readability": readability,
        "top_keywords": [kw[0] for kw in keywords],
        "keyword_densities": densities,
    }
    if truncated:
        result["truncated"] = True
        result["submitted_word_count"] = full_word_count
        result["analyzed_word_count"] = word_count
    result["suggestions"] = seo_improvement_suggestions(result)
    return result


def generate_meta_description(text: str, limit: int = 160):
    """Generate a concise meta description trimmed to a CHARACTER budget.

    SERP meta descriptions are measured in characters (~155–160 before Google truncates), not
    words. This previously used ``enforce_word_limit``, which is a WORD limit — so ``limit=160``
    produced ~160 words (~900+ characters), far past the SERP cutoff. Trim to ``limit``
    characters instead, preferring a sentence boundary and falling back to a word boundary.
    """
    cleaned = " ".join((text or "").split())  # collapse whitespace/newlines
    if len(cleaned) <= limit:
        return cleaned

    window = cleaned[:limit]
    # Prefer ending on a sentence boundary, but only if it keeps a usable length (>= 60% budget).
    best_end = -1
    for match in re.finditer(r"[.!?](?:\s|$)", window):
        best_end = match.end()
    if best_end >= int(limit * 0.6):
        return window[:best_end].strip()

    # Otherwise cut at the last word boundary and mark the truncation.
    cut = window.rsplit(" ", 1)[0] if " " in window else window
    return f"{cut.rstrip()}…"

