"""The agent's `leadgen.search` finds leads that are scored, saved and each described by its own text.

Found 2026-09-28 on run 8cdb97ef. The agent's tool called `sys.v1.leadgen.search_ai`, the raw twin
of the search the Search page runs, so every lead came back `score: null`, nothing reached
`leadgen_results` (untouched since 2026-09-16), and `leadgen.act`, which works from saved leads,
had nothing to act on. The three leads (AMAX, a LinkedIn post, a fast.io listicle) also shared one
context, the first 240 characters of the whole search text, and were named after the first word of
their domain ("Linkedin", "Fast").
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.app_profile

# `research_engine.web_search`'s own rendering: title, url, snippet, blocks split by a blank line.
RAW = (
    "AMAX AI Infrastructure Solutions | AMAX\n"
    "https://www.amax.com/ai-infrastructure\n"
    "AMAX designs and builds turnkey GPU clusters for enterprise AI.\n"
    "\n"
    "We're hiring: Head of AI Search Optimization - Jane Doe\n"
    "https://www.linkedin.com/posts/jane-doe_ai-search-123\n"
    "Our team is looking for someone to own how our product shows up in AI answers.\n"
    "Second line of the same snippet.\n"
    "\n"
    "10 Best AEO Agencies in 2026 - Fast.io\n"
    "https://fast.io/resources/best-aeo-agencies\n"
    "A roundup of answer-engine optimisation agencies."
)


def test_each_lead_carries_its_own_context_title_and_company():
    from apps.search.services.search_service import _extract_leads_from_text

    leads = _extract_leads_from_text(RAW, max_results=3)

    assert [lead["url"] for lead in leads] == [
        "https://www.amax.com/ai-infrastructure",
        "https://www.linkedin.com/posts/jane-doe_ai-search-123",
        "https://fast.io/resources/best-aeo-agencies",
    ]
    assert [lead["company"] for lead in leads] == ["AMAX", "Jane Doe", "Fast.io"]
    assert leads[0]["title"] == "AMAX AI Infrastructure Solutions | AMAX"
    assert leads[0]["context"].startswith("AMAX designs")
    assert leads[1]["context"] == (
        "Our team is looking for someone to own how our product shows up in AI answers. "
        "Second line of the same snippet."
    )
    assert leads[2]["context"].startswith("A roundup")
    assert len({lead["context"] for lead in leads}) == 3


def test_a_title_without_a_site_suffix_falls_back_to_the_domain():
    from apps.search.services.search_service import _extract_leads_from_text

    leads = _extract_leads_from_text("Acme builds robots\nhttps://acme-robotics.io/about\nText.")
    assert leads[0]["company"] == "Acme Robotics"
    assert leads[0]["title"] == "Acme builds robots"


def test_a_url_inside_prose_gets_the_text_around_it():
    from apps.search.services.search_service import _extract_leads_from_text

    text = "Filler " * 60 + "see https://example.com/page for the details " + "more " * 60
    leads = _extract_leads_from_text(text)
    assert leads[0]["url"] == "https://example.com/page"
    assert "https://example.com/page" in leads[0]["context"]


def test_max_results_and_duplicates():
    from apps.search.services.search_service import _extract_leads_from_text

    doubled = RAW + "\n\nAMAX again | AMAX\nhttps://www.amax.com/ai-infrastructure\nDup."
    assert len(_extract_leads_from_text(doubled, max_results=10)) == 3
    assert len(_extract_leads_from_text(RAW, max_results=2)) == 2


def test_with_a_segment_the_agent_tool_searches_inside_it(monkeypatch):
    """MARKET_MODEL_SPEC §5 (2026-09-30): the saved search is the one inside a segment."""
    from apps.search.agents import tools

    calls = []

    def fake_dispatch(name, args, user_id, *, capability):
        calls.append((name, args, capability))
        return {"leads": [{"id": 7, "company": "OpenTeams", "overall_score": 82}], "count": 1,
                "segment": "Platform teams", "proposed": [{"kind": "alternative", "name": "Gumloop"}]}

    monkeypatch.setattr(tools, "_dispatch_tool_syscall", fake_dispatch)
    out = tools.leadgen_search({"segment": "Platform teams"}, "user-1", None)

    assert calls == [("sys.v1.leadgen.search_segment", {"segment": "Platform teams", "where": "hiring"}, "leadgen.search")]
    assert out["saved"] is True and out["count"] == 1 and out["proposed"][0]["name"] == "Gumloop"


def test_without_a_segment_it_is_a_web_search_that_saves_nothing(monkeypatch):
    """§9 decision 4: outside a segment nothing is saved, so leadgen.act never drafts to an article."""
    from apps.search.agents import tools

    calls = []
    monkeypatch.setattr(tools, "_dispatch_tool_syscall",
                        lambda name, args, user_id, *, capability: calls.append(name) or {"leads": [{"company": "X"}]})
    out = tools.leadgen_search({"query": "aeo"}, "user-1", None)
    assert calls == ["sys.v1.leadgen.search_ai"]
    assert (out["saved"], out["count"], out["segment"]) == (False, 1, None)
    with pytest.raises(ValueError):
        tools.leadgen_search({}, "user-1", None)


def test_a_failed_retrieval_is_not_saved_as_a_lead(monkeypatch):
    """`search_leads` answers a failure with a url-less "External Search" preview row."""
    from apps.search.services import leadgen_service

    monkeypatch.delenv("AINDY_LEADGEN_ALLOW_FIXTURES", raising=False)
    monkeypatch.setattr(
        leadgen_service, "search_leads",
        lambda query, db=None, user_id=None, max_results=3: {
            "results": [{"company": "External Search", "url": "", "context": query}],
            "retrieval_error": "PERPLEXITY_API_KEY is not set",
        },
    )
    with pytest.raises(leadgen_service.LeadSearchUnavailable):
        leadgen_service.run_ai_search("aeo")


def test_an_empty_retrieval_saves_nothing(monkeypatch):
    from apps.search.services import leadgen_service

    monkeypatch.delenv("AINDY_LEADGEN_ALLOW_FIXTURES", raising=False)
    monkeypatch.setattr(
        leadgen_service, "search_leads",
        lambda query, db=None, user_id=None, max_results=3: {
            "results": [{"company": "External Search", "url": "", "context": query}],
            "retrieval_error": None,
        },
    )
    assert leadgen_service.run_ai_search("aeo") == []
