"""The agent's research result: cut at a word boundary, marked, and big enough to be useful.

It was `raw[:2000]` from the initial extraction: mid-word, unmarked ("…The goal is no",
2026-09-25). Since runtime 2.24.0 a `$from_step` reference carries exactly this value to the next
step (FR-46 ask 4 — the runtime truncates nothing; this cut is ours).
"""
from __future__ import annotations

import pytest

from apps.search.syscalls import (
    RESEARCH_RESULT_MAX_CHARS,
    RESEARCH_TRUNCATED_MARKER,
    _research_excerpt,
)

pytestmark = pytest.mark.app_profile


def test_short_results_are_untouched():
    assert _research_excerpt("Show HN works Tue-Thu.") == "Show HN works Tue-Thu."
    assert _research_excerpt(None) == ""


def test_the_limit_matches_the_findings_digest():
    from apps.agent.services.run_findings import MAX_FINDINGS_CHARS

    assert RESEARCH_RESULT_MAX_CHARS == MAX_FINDINGS_CHARS == 6000


def test_long_results_are_cut_between_words_and_marked():
    raw = ("word " * 2000).strip()  # 9999 chars
    out = _research_excerpt(raw)
    assert out.endswith(RESEARCH_TRUNCATED_MARKER)
    body = out[: -len(RESEARCH_TRUNCATED_MARKER)]
    assert len(body) <= RESEARCH_RESULT_MAX_CHARS
    assert body.endswith("word")  # never a fragment like "wo"


def test_a_result_with_no_spaces_is_still_bounded():
    out = _research_excerpt("x" * 10000)
    assert out == "x" * RESEARCH_RESULT_MAX_CHARS + RESEARCH_TRUNCATED_MARKER
