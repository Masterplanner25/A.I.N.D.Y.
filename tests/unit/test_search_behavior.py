"""Behavior tests for the leadgen and research search surfaces.

These run under the app profile on in-memory SQLite. External IO (web search,
LLM scoring/summarization) and Memory Bridge writes are mocked, so the tests
exercise the real persistence, scoring, caching, unified-contract normalization,
and flow-node wiring without any network or embedding dependency.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("AINDY_ALLOW_SQLITE", "1")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-required-length-1234567890")

from AINDY.db.database import Base
from AINDY.db.models.user import User
from tests.helpers.app_profile import bootstrap_app_models
from tests.helpers.runtime import import_runtime_model_registry

pytestmark = pytest.mark.app_profile


@pytest.fixture()
def db_session():
    import_runtime_model_registry()
    bootstrap_app_models(required=True)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def user_id(db_session):
    uid = uuid.uuid4()
    db_session.add(
        User(id=uid, email=f"{uid}@example.com", hashed_password="x", is_active=True)
    )
    db_session.commit()
    return str(uid)


# --------------------------------------------------------------------------- #
# LeadGen service behavior
# --------------------------------------------------------------------------- #
def test_run_ai_search_uses_external_results(monkeypatch):
    from apps.search.services import leadgen_service

    monkeypatch.setattr(leadgen_service, "is_pipeline_active", lambda: True)
    monkeypatch.setattr(
        leadgen_service,
        "search_leads",
        lambda q, db=None, user_id=None, max_results=3: {
            "results": [{"company": "Beta", "url": "https://beta.io", "context": "ctx"}]
        },
    )

    leads = leadgen_service.run_ai_search("ai consultants", user_id="u", db=object())
    assert leads == [{"company": "Beta", "url": "https://beta.io", "context": "ctx"}]


def test_run_ai_search_raises_when_external_fails(monkeypatch):
    """Retrieval failure must not become three fabricated leads.

    This test previously asserted the opposite — that a failed search returns the
    hardcoded demo companies — and so pinned the defect in place. Everything downstream
    of that substitution was real: a genuine scoring call, a persisted `leadgen_results`
    row, and a memory node recalled as prior context on later runs.

    Fixtures are now development-only behind `AINDY_LEADGEN_ALLOW_FIXTURES`; the gate and
    the failure/empty distinction are covered in `test_leadgen_fixture_gate.py`.
    """
    from apps.search.services import leadgen_service

    monkeypatch.delenv("AINDY_LEADGEN_ALLOW_FIXTURES", raising=False)
    monkeypatch.setattr(leadgen_service, "is_pipeline_active", lambda: True)

    def boom(*a, **k):
        raise RuntimeError("no provider")

    monkeypatch.setattr(leadgen_service, "search_leads", boom)

    with pytest.raises(leadgen_service.LeadSearchUnavailable):
        leadgen_service.run_ai_search("ai consultants", user_id="u", db=object())


def test_create_lead_results_persists_and_sorts(monkeypatch, db_session, user_id):
    from apps.search.models.leadgen_model import LeadGenResult
    from apps.search.services import leadgen_service

    monkeypatch.setattr(leadgen_service, "is_pipeline_active", lambda: True)
    monkeypatch.setattr(
        leadgen_service,
        "run_ai_search",
        lambda q, user_id=None, db=None: [
            {"company": "LowFit", "url": "https://low.io", "context": "c1"},
            {"company": "HighFit", "url": "https://high.io", "context": "c2"},
        ],
    )

    def fake_score(lead):
        overall = 90 if lead["company"] == "HighFit" else 30
        return {
            "fit_score": overall,
            "intent_score": overall,
            "data_quality_score": overall,
            "overall_score": overall,
            "reasoning": f"scored {lead['company']}",
        }

    monkeypatch.setattr(leadgen_service, "score_lead", fake_score)

    results = leadgen_service.create_lead_results(db_session, "fintech", user_id=user_id)

    # returned newest/highest first
    assert [row.company for row, _ in results] == ["HighFit", "LowFit"]
    assert results[0][1] > results[1][1]  # search_score sorted desc

    # both rows persisted
    rows = db_session.query(LeadGenResult).all()
    assert {r.company for r in rows} == {"HighFit", "LowFit"}
    high = next(r for r in rows if r.company == "HighFit")
    assert high.overall_score == 90
    assert high.reasoning == "scored HighFit"


def test_create_lead_results_requires_user():
    from apps.search.services import leadgen_service

    with pytest.raises(ValueError):
        leadgen_service.create_lead_results(object(), "q", user_id=None)


def test_list_leads_newest_first(db_session, user_id):
    from apps.search.models.leadgen_model import LeadGenResult
    from apps.search.services import leadgen_service

    for i, company in enumerate(["First", "Second"]):
        db_session.add(
            LeadGenResult(
                query="q",
                user_id=uuid.UUID(user_id),
                company=company,
                url=f"https://{company}.io",
                context="c",
                fit_score=10.0,
                intent_score=10.0,
                data_quality_score=10.0,
                overall_score=float(i),
                reasoning="r",
            )
        )
        db_session.commit()

    leads = leadgen_service.list_leads(db_session, user_id)
    assert len(leads) == 2
    # search_score is mapped from overall_score
    assert all("search_score" in row for row in leads)
    assert {row["company"] for row in leads} == {"First", "Second"}


# --------------------------------------------------------------------------- #
# Research service behavior
# --------------------------------------------------------------------------- #
def test_create_research_result_persists_with_data_and_source(monkeypatch, db_session, user_id):
    from apps.search.schemas.research_results_schema import ResearchResultCreate
    from apps.search.services import research_results_service

    monkeypatch.setattr(research_results_service, "is_pipeline_active", lambda: True)

    row = research_results_service.create_research_result(
        db_session,
        ResearchResultCreate(query="market sizing", summary="big TAM"),
        user_id=user_id,
        data={"search_score": 0.5},
        source="research_query",
    )
    assert row.id is not None
    assert row.source == "research_query"
    assert row.data == {"search_score": 0.5}

    all_rows = research_results_service.get_all_research_results(db_session, user_id=user_id)
    assert [r.query for r in all_rows] == ["market sizing"]


def test_get_all_research_results_scoped_by_user(monkeypatch, db_session, user_id):
    from apps.search.schemas.research_results_schema import ResearchResultCreate
    from apps.search.services import research_results_service

    monkeypatch.setattr(research_results_service, "is_pipeline_active", lambda: True)
    research_results_service.create_research_result(
        db_session, ResearchResultCreate(query="mine", summary="s"), user_id=user_id
    )
    other = str(uuid.uuid4())
    research_results_service.create_research_result(
        db_session, ResearchResultCreate(query="theirs", summary="s"), user_id=other
    )

    mine = research_results_service.get_all_research_results(db_session, user_id=user_id)
    assert [r.query for r in mine] == ["mine"]


# --------------------------------------------------------------------------- #
# Unified search service behavior (persistence + caching + Step 2 normalization)
# --------------------------------------------------------------------------- #
def test_unified_query_normalizes_persists_and_caches(monkeypatch, db_session, user_id):
    from apps.search.models import SearchHistory
    from apps.search.services import search_service

    monkeypatch.setattr(
        search_service,
        "search_memory",
        lambda q, db=None, user_id=None, tags=None, limit=5: {
            "items": [{"id": "m1"}], "ids": ["m1"], "formatted": "", "count": 1
        },
    )

    result = search_service.unified_query(
        "quantum compute market",
        db=db_session,
        user_id=user_id,
        web_search_fn=lambda q: "RAW CONTENT https://src.io",
        ai_analyze_fn=lambda raw: "A concise summary.",
    )

    assert result["summary"] == "A concise summary."
    assert result["source"] == "external_search"
    assert result["search_type"] == "research"
    assert result["search_score"] > 0
    # Step 2 normalized results present
    assert result["results"][0]["snippet"] == "A concise summary."
    # learning context reflects recalled memory
    lc = result["learning_context"]
    assert lc["recalled_memory"] is True
    assert lc["memory_count"] == 1
    assert result["history_id"]

    # one history row persisted
    assert db_session.query(SearchHistory).count() == 1

    # identical query is served from cache — no duplicate row
    cached = search_service.unified_query(
        "quantum compute market",
        db=db_session,
        user_id=user_id,
        web_search_fn=lambda q: (_ for _ in ()).throw(AssertionError("should not be called")),
        ai_analyze_fn=lambda raw: "unused",
    )
    assert cached["history_id"] == result["history_id"]
    assert db_session.query(SearchHistory).count() == 1


def test_search_leads_extracts_and_enriches(monkeypatch, db_session, user_id):
    from apps.search.models import SearchHistory
    from apps.search.services import research_engine, search_service

    monkeypatch.setattr(
        search_service, "search_memory",
        lambda q, db=None, user_id=None, tags=None, limit=5: {
            "items": [], "ids": [], "formatted": "", "count": 0
        },
    )
    monkeypatch.setattr(
        research_engine, "web_search",
        lambda q: '{"results": [{"title": "Acme", "url": "https://acme.io", "snippet": "hiring"}]}',
    )

    out = search_service.search_leads("ai leads", db=db_session, user_id=user_id, max_results=3)
    lead = out["results"][0]
    # legacy + Step 2 shared keys both present
    assert lead["company"] == "Acme"
    assert lead["title"] == "Acme"
    assert lead["url"] == "https://acme.io"
    assert "score" in lead

    # persisted under the lead_preview search type
    row = db_session.query(SearchHistory).one()
    assert (row.result or {}).get("search_type") == "lead_preview"


def test_search_history_crud(db_session, user_id):
    from apps.search.services import search_service

    a = search_service.persist_search_result(
        db=db_session, user_id=user_id, query="alpha",
        result={"query": "alpha", "results": []}, search_type="research",
    )
    search_service.persist_search_result(
        db=db_session, user_id=user_id, query="beta",
        result={"query": "beta", "results": []}, search_type="lead_preview",
    )

    all_items = search_service.get_search_history(db_session, user_id, limit=25)
    assert len(all_items) == 2

    research_only = search_service.get_search_history(
        db_session, user_id, limit=25, search_type="research"
    )
    assert [i.query for i in research_only] == ["alpha"]

    fetched = search_service.get_search_history_item(db_session, user_id, a["history_id"])
    assert fetched is not None and fetched.query == "alpha"

    assert search_service.delete_search_history_item(db_session, user_id, a["history_id"]) is True
    assert search_service.get_search_history_item(db_session, user_id, a["history_id"]) is None


def test_get_cached_search_result_respects_search_type(db_session, user_id):
    from apps.search.services import search_service

    search_service.persist_search_result(
        db=db_session, user_id=user_id, query="shared",
        result={"query": "shared", "results": []}, search_type="research",
    )
    # same query, different surface => cache miss
    assert search_service.get_cached_search_result(
        db=db_session, user_id=user_id, query="shared", search_type="leadgen"
    ) is None
    # matching surface => hit
    hit = search_service.get_cached_search_result(
        db=db_session, user_id=user_id, query="shared", search_type="research"
    )
    assert hit is not None and hit["history_id"]


# --------------------------------------------------------------------------- #
# Flow-node behavior (end-to-end through the search flows)
# --------------------------------------------------------------------------- #
def test_research_query_node_end_to_end(monkeypatch, db_session, user_id):
    from apps.search.models.research_results import ResearchResult
    from apps.search.services import research_engine, research_results_service, search_service
    from apps.search.flows import search_flows

    monkeypatch.setattr(research_results_service, "is_pipeline_active", lambda: True)
    monkeypatch.setattr(
        search_service, "search_memory",
        lambda q, db=None, user_id=None, tags=None, limit=5: {
            "items": [], "ids": [], "formatted": "", "count": 0
        },
    )
    monkeypatch.setattr(research_engine, "web_search", lambda q: "raw research content")
    monkeypatch.setattr(research_engine, "ai_analyze", lambda raw: "node summary")

    out = search_flows.research_query_node(
        {"query": "edge AI trends"}, {"db": db_session, "user_id": user_id}
    )
    assert out["status"] == "SUCCESS"
    payload = out["output_patch"]["research_query_result"]["data"]
    assert payload["search_type"] == "research"
    assert payload["summary"] == "node summary"
    assert payload["results"]  # Step 2/6 normalized results surfaced through the flow

    assert db_session.query(ResearchResult).count() == 1


def test_leadgen_preview_search_node_end_to_end(monkeypatch, db_session, user_id):
    from apps.search.services import research_engine, search_service
    from apps.search.flows import search_flows

    monkeypatch.setattr(
        search_service, "search_memory",
        lambda q, db=None, user_id=None, tags=None, limit=5: {
            "items": [], "ids": [], "formatted": "", "count": 0
        },
    )
    monkeypatch.setattr(
        research_engine, "web_search",
        lambda q: '{"results": [{"title": "Lead Co", "url": "https://lead.co", "snippet": "x"}]}',
    )

    out = search_flows.leadgen_preview_search_node(
        {"query": "b2b leads"}, {"db": db_session, "user_id": user_id}
    )
    assert out["status"] == "SUCCESS"
    result = out["output_patch"]["leadgen_preview_search_result"]
    assert result["results"][0]["company"] == "Lead Co"
    assert result["results"][0]["title"] == "Lead Co"
