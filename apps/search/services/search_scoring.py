from __future__ import annotations

import logging
import math
import os
import re
from collections.abc import Callable
from typing import Optional

logger = logging.getLogger(__name__)

# Small stop-word set so common glue words don't inflate query/result overlap.
_STOPWORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "for", "to", "of", "in", "on", "with",
        "is", "are", "be", "by", "at", "as", "it", "this", "that", "from",
        "we", "our", "your", "their", "you", "they",
    }
)
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def tokenize(text: str) -> list[str]:
    """Lowercase word/number tokens, dropping stop-words and single chars."""
    return [
        tok
        for tok in _TOKEN_RE.findall((text or "").lower())
        if len(tok) >= 2 and tok not in _STOPWORDS
    ]


def lexical_relevance(query: str, text: str) -> float:
    """Query↔text relevance on 0..1 from token overlap + term frequency.

    Combines *coverage* (how many distinct query terms appear in the text) with
    a saturating *term-frequency* signal (how densely they appear). Pure Python,
    deterministic — no external models. Returns 0.0 when there is no overlap.
    """
    query_tokens = set(tokenize(query))
    if not query_tokens:
        return 0.0
    doc_tokens = tokenize(text)
    if not doc_tokens:
        return 0.0
    overlap = query_tokens.intersection(doc_tokens)
    if not overlap:
        return 0.0
    coverage = len(overlap) / len(query_tokens)
    hits = sum(1 for tok in doc_tokens if tok in query_tokens)
    tf = min(1.0, (hits / len(doc_tokens)) * 3.0)
    return _clamp01(0.7 * coverage + 0.3 * tf)


# --------------------------------------------------------------------------- #
# Semantic (embedding-backed) relevance — Evolution Plan upgrade
# (TECH_DEBT: SEARCH-RANKING-EMBEDDINGS-1)
#
# Lexical relevance captures token overlap but not synonyms / paraphrase /
# intent. These helpers add a semantic signal on top of the *same* runtime
# embedding stack the app already reaches via ``search_service.search_memory``
# (``MemoryOrchestrator``) — no new external dependency on the app side.
#
# The seam is opt-in and self-healing:
#   * Lexical stays the default (deterministic, dependency-free).
#   * Embeddings are used only when AINDY_SEARCH_EMBEDDING_RANKING is enabled
#     *and* the runtime embedding backend actually returns a usable vector.
#   * Every failure mode (backend unimportable, API down, testing/CI zero
#     vectors, empty text) falls back to lexical, so callers never crash and
#     SQLite/app-profile runs stay lexical and deterministic.
# --------------------------------------------------------------------------- #
_EMBEDDING_FLAG = "AINDY_SEARCH_EMBEDDING_RANKING"
_TRUTHY = frozenset({"1", "true", "yes", "on"})

RelevanceFn = Callable[[str, str], float]


def _is_zero_vector(vec: object) -> bool:
    """True for the empty / all-zero vectors the embedding service returns
    when it is unavailable (testing mode, API failure, empty input)."""
    if not vec:
        return True
    try:
        return not any(vec)  # type: ignore[arg-type]
    except TypeError:
        return True


def embedding_relevance(query: str, text: str, *, fallback: RelevanceFn | None = None) -> float:
    """Semantic query↔text relevance on 0..1 via runtime embeddings.

    Falls back to ``lexical_relevance`` (or ``fallback``) whenever the embedding
    backend is unavailable — it returns a zero vector under testing/CI or on API
    failure — so callers always get a usable signal. Stateless: re-embeds on each
    call. Use :class:`EmbeddingRelevanceProvider` when ranking many items against
    one query so the query (and each document) is embedded only once.
    """
    fb = fallback or lexical_relevance
    if not (query or "").strip() or not (text or "").strip():
        return fb(query, text)
    try:
        from AINDY.memory.embedding_service import (
            cosine_similarity,
            generate_query_embedding,
        )
    except Exception as exc:  # pragma: no cover - import guard
        logger.debug("embedding backend unavailable, using lexical: %s", exc)
        return fb(query, text)

    q_vec = generate_query_embedding(query)
    if _is_zero_vector(q_vec):
        return fb(query, text)
    d_vec = generate_query_embedding(text)
    if _is_zero_vector(d_vec):
        return fb(query, text)
    return _clamp01(cosine_similarity(q_vec, d_vec))


class EmbeddingRelevanceProvider:
    """Caching, hybrid relevance callable: embeddings with lexical fallback.

    Designed to be constructed once per ranking pass and called as
    ``provider(query, text)`` for each item. The query is embedded once and each
    document text is cached, so :func:`rank_items` does not recompute embeddings
    per item (TECH_DEBT SEARCH-RANKING-EMBEDDINGS-1, scope item 4). Availability
    is decided once per query: if the query embeds to a zero vector (backend
    down / testing mode), every item for that query falls back to lexical.
    """

    def __init__(self, *, fallback: RelevanceFn | None = None) -> None:
        self._fallback: RelevanceFn = fallback or lexical_relevance
        self._embed: Callable[[str], list] | None = None
        self._cosine: Callable[[list, list], float] | None = None
        self._backend_checked = False
        self._query: str | None = None
        self._query_vec: list | None = None
        self._available = False
        self._doc_cache: dict[str, list] = {}

    def _ensure_backend(self) -> bool:
        if self._backend_checked:
            return self._embed is not None
        self._backend_checked = True
        try:
            from AINDY.memory.embedding_service import (
                cosine_similarity,
                generate_query_embedding,
            )
        except Exception as exc:  # pragma: no cover - import guard
            logger.debug("embedding backend unavailable, using lexical: %s", exc)
            return False
        self._embed = generate_query_embedding
        self._cosine = cosine_similarity
        return True

    def _prime_query(self, query: str) -> None:
        self._query = query
        self._doc_cache = {}
        if not (query or "").strip() or self._embed is None:
            self._query_vec = None
            self._available = False
            return
        self._query_vec = self._embed(query)
        self._available = not _is_zero_vector(self._query_vec)

    def __call__(self, query: str, text: str) -> float:
        if not self._ensure_backend():
            return self._fallback(query, text)
        if query != self._query:
            self._prime_query(query)
        if not self._available or not (text or "").strip():
            return self._fallback(query, text)
        vec = self._doc_cache.get(text)
        if vec is None:
            vec = self._embed(text)  # type: ignore[misc]
            self._doc_cache[text] = vec
        if _is_zero_vector(vec):
            return self._fallback(query, text)
        return _clamp01(self._cosine(self._query_vec, vec))  # type: ignore[misc,arg-type]


def embedding_ranking_enabled() -> bool:
    """Whether semantic ranking is opted into via ``AINDY_SEARCH_EMBEDDING_RANKING``."""
    return os.environ.get(_EMBEDDING_FLAG, "").strip().lower() in _TRUTHY


def default_relevance_provider() -> RelevanceFn:
    """Return the active relevance callable for ranking.

    Lexical by default. Returns a hybrid :class:`EmbeddingRelevanceProvider`
    (semantic similarity with automatic lexical fallback) when the embedding
    seam is enabled — the provider degrades to lexical on its own if the backend
    is unavailable, so this is always safe to call.
    """
    if embedding_ranking_enabled():
        return EmbeddingRelevanceProvider()
    return lexical_relevance


# --------------------------------------------------------------------------- #
# Outcome→query weighting — Search v4 §8 (TECH_DEBT search-v4 residual)
#
# The result-feedback capture (``SearchResultFeedback`` / ``feedback_service``)
# records whether a result actually *worked* and aggregates it into a per-query
# outcome weight. Here that weight becomes a small, bounded nudge on the ranking
# composite so results the user (or their agents) have acted on drift up, and
# ones they dismissed drift down — without letting a single vote dominate the
# relevance+quality signal. Opt-in: lexical/quality ranking is unchanged unless
# ``AINDY_SEARCH_OUTCOME_WEIGHTING`` is enabled *and* weights are supplied.
# --------------------------------------------------------------------------- #
_OUTCOME_FLAG = "AINDY_SEARCH_OUTCOME_WEIGHTING"

# Bounds: a strong single signal (convert / thumbs_up ≈ +1.0) lifts the
# composite by ~0.07; the nudge saturates at ±0.15 no matter how much feedback
# accumulates, so relevance+quality always stays the dominant axis.
_OUTCOME_MAX_NUDGE = 0.15
_OUTCOME_COEFFICIENT = 0.5


def outcome_weighting_enabled() -> bool:
    """Whether outcome→query ranking weighting is opted into via the env flag."""
    return os.environ.get(_OUTCOME_FLAG, "").strip().lower() in _TRUTHY


def outcome_nudge(
    weight: Optional[float],
    *,
    coefficient: float = _OUTCOME_COEFFICIENT,
    max_nudge: float = _OUTCOME_MAX_NUDGE,
) -> float:
    """Map an aggregated outcome weight onto a bounded ranking nudge on ±max_nudge.

    ``tanh`` keeps the nudge smooth, sign-preserving, and saturating: near zero it
    is roughly linear in the weight, and no amount of accumulated feedback can push
    a result more than ``max_nudge`` in either direction. Returns 0.0 for a missing
    or zero weight.
    """
    if not weight:
        return 0.0
    return max_nudge * math.tanh(coefficient * float(weight))


def composite_score(
    relevance: float,
    quality: Optional[float],
    *,
    relevance_weight: float = 0.6,
) -> float:
    """Blend query relevance with a surface quality score onto 0..1.

    ``relevance_weight`` controls how much the shared relevance signal dominates
    the surface-specific quality score (leadgen fit, research depth, SEO health).
    """
    rel = _clamp01(relevance)
    qual = _clamp01(quality or 0.0)
    return _clamp01(relevance_weight * rel + (1.0 - relevance_weight) * qual)


def score_lead_result(
    *,
    overall_score: Optional[float] = None,
    fit_score: Optional[float] = None,
    intent_score: Optional[float] = None,
    data_quality_score: Optional[float] = None,
) -> float:
    if overall_score is not None:
        return _clamp01(overall_score / 100.0)
    parts = [s for s in (fit_score, intent_score, data_quality_score) if s is not None]
    if not parts:
        return 0.0
    return _clamp01(sum(parts) / (len(parts) * 100.0))


def score_research_result(
    *,
    summary: str,
    memory_context_count: int = 0,
) -> float:
    length_factor = _clamp01(len(summary or "") / 500.0)
    memory_factor = _clamp01(memory_context_count / 5.0)
    return _clamp01(0.7 * length_factor + 0.3 * memory_factor)


# `score_seo_result` lived here until 2026-09-11. It blended readability, mean keyword
# density and word count into the SEO scorecard's `search_score`; dropped per
# SEO_EDITING_AID_SPEC §5 Q3. `search_score` on lead and research results is a different
# thing — a ranking composite — and is untouched.

