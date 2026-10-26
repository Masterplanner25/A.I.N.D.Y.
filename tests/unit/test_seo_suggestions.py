"""
SEO improvement suggestions (Search v4 §3.1).

`seo_analysis` previously returned metrics but no actionable suggestions. Tests the
deterministic heuristics + that seo_analysis surfaces them. Hermetic.
"""
from __future__ import annotations

import pytest

from apps.search.services.seo_services import seo_analysis, seo_improvement_suggestions

pytestmark = pytest.mark.app_profile


def _metrics(word_count=500, readability=70.0, densities=None, top_keywords=("ai",)):
    return {
        "word_count": word_count,
        "readability": readability,
        "keyword_densities": densities if densities is not None else {"ai": 1.5},
        "top_keywords": list(top_keywords),
    }


def _by_metric(suggestions):
    return {s["metric"] for s in suggestions}


def test_healthy_analysis_returns_single_ok():
    out = seo_improvement_suggestions(_metrics())
    assert len(out) == 1
    assert out[0]["metric"] == "overall"
    assert out[0]["severity"] == "info"


def test_thin_content_flagged():
    out = seo_improvement_suggestions(_metrics(word_count=120))
    assert "word_count" in _by_metric(out)
    assert any(s["severity"] == "warn" and s["metric"] == "word_count" for s in out)


def test_hard_readability_flagged():
    out = seo_improvement_suggestions(_metrics(readability=20.0))
    assert any(s["metric"] == "readability" and s["severity"] == "warn" for s in out)


def test_difficult_readability_is_info():
    out = seo_improvement_suggestions(_metrics(readability=45.0))
    read = [s for s in out if s["metric"] == "readability"]
    assert read and read[0]["severity"] == "info"


def test_keyword_stuffing_flagged():
    out = seo_improvement_suggestions(_metrics(densities={"ai": 6.5}))
    stuffing = [s for s in out if s["metric"] == "keyword_density"]
    assert stuffing and "ai" in stuffing[0]["issue"]


def test_no_keywords_flagged():
    out = seo_improvement_suggestions(_metrics(top_keywords=(), densities={}))
    assert "keywords" in _by_metric(out)


def test_weak_focus_is_info():
    out = seo_improvement_suggestions(_metrics(densities={"ai": 0.2}))
    focus = [s for s in out if s["metric"] == "keyword_focus"]
    assert focus and focus[0]["severity"] == "info"


def test_seo_analysis_surfaces_suggestions():
    result = seo_analysis("AI systems help teams move faster. " * 5)
    assert "suggestions" in result
    assert isinstance(result["suggestions"], list) and result["suggestions"]
    assert all({"metric", "issue", "suggestion", "severity"} <= set(s) for s in result["suggestions"])


# ── readability names its sentences (owner, 2026-10-25) ───────────────────────────────────
#
# "Improve readability with shorter sentences" did not say which sentences, or allow that the
# length might be deliberate. The finding now lists the longest ones and says to leave them
# where the length is intended.

LONG = (
    "This sentence keeps adding clause after clause because the writer is building a contrast "
    "between what the version promised and what the release actually did on the day it shipped."
)


def test_the_longest_sentences_are_pointed_at():
    from apps.search.services.seo_services import longest_sentences

    out = longest_sentences("Short one. " + LONG + " Another short one.")
    assert len(out) == 1
    assert out[0]["words"] == len(LONG.split())
    assert out[0]["opening"].startswith("This sentence keeps adding clause")
    assert out[0]["opening"].endswith("…")


def test_a_readability_finding_carries_its_passages_and_allows_intent():
    metrics = _metrics(readability=20.0)
    metrics["long_sentences"] = [{"opening": "This sentence keeps…", "words": 31}]

    read = [s for s in seo_improvement_suggestions(metrics) if s["metric"] == "readability"][0]
    assert read["passages"] == metrics["long_sentences"]
    assert "deliberate" in read["suggestion"]


def test_seo_analysis_reports_the_long_sentences():
    result = seo_analysis(("Short one. " + LONG + " ") * 3)
    assert result["long_sentences"]


# ── "Get Suggestions" returns the measured findings, not a second list ─────────────────────

def test_get_suggestions_returns_the_analysis_findings(monkeypatch):
    """The button built its own list from word counts ("Build headings around the strongest
    terms: nodus, project, version"). It now returns what the analysis measured."""
    from apps.search.services import search_service

    seen = {}

    def _analyze(text, top_n=10, *, db=None, user_id=None, title=None, target_keywords=None):
        seen.update(title=title, target_keywords=target_keywords)
        return seo_analysis(text, top_n, title=title, target_keywords=target_keywords)

    monkeypatch.setattr(search_service, "analyze_seo_content", _analyze)

    out = search_service.suggest_seo_improvements(
        ("Short one. " + LONG + " ") * 3, title="What a version promises",
        target_keywords=["version"],
    )

    assert seen == {"title": "What a version promises", "target_keywords": ["version"]}
    assert out["suggestions"] and all("issue" in s for s in out["suggestions"])
    assert "strongest terms" not in out["seo_suggestions"]
    # The title reached the analysis: the old list never looked at one.
    assert "title_length" in {s["metric"] for s in out["suggestions"]}
