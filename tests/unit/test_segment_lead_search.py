"""Lead search inside a market segment — `MARKET_MODEL_SPEC.md` §5, phase B.

The owner, 2026-09-28: *"the problem is where are we looking."* Verified live 2026-09-30: the open
web returned listicles for the platform-teams segment's words; a job-board filter returned companies
hiring for the problem. The load-bearing properties: the search starts from a confirmed segment and
its words; it looks on job boards by default and on the segment's own channels on request; a buyer
is saved tagged with the segment; anything else is proposed as what it is, never saved as a lead;
and outcomes are grouped by segment, not by a reworded query.

Only the web search and the model's judgement are stubbed. The segment, the proposals and the saved
leads are the real masterplan and search code, joined through the registered jobs.
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("AINDY_ALLOW_SQLITE", "1")

from AINDY.db.database import Base
from AINDY.db.models.user import User
from tests.helpers.app_profile import bootstrap_app_models
from tests.helpers.runtime import import_runtime_model_registry

pytestmark = pytest.mark.app_profile


@pytest.fixture()
def db():
    import_runtime_model_registry()
    bootstrap_app_models(required=True)
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def user(db):
    uid = uuid.uuid4()
    db.add(User(id=uid, email=f"{uid}@example.com", hashed_password="x", is_active=True))
    db.commit()
    return str(uid)


@pytest.fixture()
def jobs(monkeypatch):
    """masterplan's two jobs, the real functions, wired as bootstrap registers them."""
    import AINDY.platform_layer.registry as registry
    from apps.masterplan.services import market_service

    table = {
        "masterplan.segment_brief": market_service.segment_brief,
        "masterplan.market_propose": market_service.propose_from_search,
    }
    monkeypatch.setattr(registry, "get_job", lambda name: table.get(name))


@pytest.fixture()
def segment(db, user):
    from apps.masterplan.services import market_service, work_service

    work = work_service.create_work(db, user, {"name": "aindy-runtime", "summary": "A self-hosted runtime for agents."})
    return market_service.create_segment(db, user, {
        "name": "Platform engineering teams building internal agent platforms",
        "buyer": "platform engineering lead, mid-to-large software org",
        "problem": "agents that survive restarts, governed, on our own infrastructure",
        "category_terms": ["self-hosted agent runtime", "durable workflow orchestration", "agent orchestration platform"],
    }, work_ids=[work["id"]])


RESULTS = [
    {"title": "Platform Engineer, AI/ML Infrastructure", "url": "https://job-boards.greenhouse.io/openteams/jobs/4735509005",
     "snippet": "Build the platform our agents run on."},
    {"title": "10 best AI agent orchestration platforms in 2026", "url": "https://www.gumloop.com/blog/ai-agent-orchestration-platform",
     "snippet": "A roundup."},
    {"title": "Cat pictures", "url": "https://cats.example/", "snippet": "Cats."},
    {"title": "Broken", "url": "https://broken.example/", "snippet": "?"},
]

# The judge reports facts; `classify` decides. Shapes as the reworked prompt returns them.
VERDICTS = {
    "https://job-boards.greenhouse.io/openteams/jobs/4735509005": {
        "organisation": "OpenTeams", "org_type": "end_user", "matches_buyer": True, "problem_evidence": True,
        "fit_score": 85, "intent_score": 80, "data_quality_score": 70, "overall_score": 88,
        "reasoning": "Hiring to build an internal agent platform."},
    "https://www.gumloop.com/blog/ai-agent-orchestration-platform": {
        "organisation": "Gumloop", "org_type": "vendor", "matches_buyer": False, "problem_evidence": False,
        "overall_score": 10, "reasoning": "Sells an orchestration platform."},
    "https://cats.example/": {"organisation": "Cats", "org_type": "other", "reasoning": "Unrelated."},
}


def _search(calls):
    def search(query, *, domains=None, recency=None, max_results=10):
        calls.append({"query": query, "domains": domains, "recency": recency})
        return RESULTS
    return search


def _judge(result, brief):
    if result["url"] == "https://broken.example/":
        raise ValueError("model returned prose")
    assert "aindy-runtime" in [w["name"] for w in brief["works"]]
    return VERDICTS[result["url"]]


def test_hiring_searches_job_boards_this_month_in_the_segments_words(db, user, jobs, segment):
    from apps.search.services.segment_search import JOB_BOARDS, segment_lead_search

    calls = []
    segment_lead_search(db, user_id=user, segment=segment["name"], search=_search(calls), judge=_judge)
    [call] = calls
    assert call["domains"] == list(JOB_BOARDS) and call["recency"] == "month"
    assert "self-hosted agent runtime" in call["query"]


def test_a_buyer_is_saved_with_its_segment_and_the_rest_are_not_leads(db, user, jobs, segment):
    from apps.masterplan.services import market_service
    from apps.search.models.leadgen_model import LeadGenResult
    from apps.search.services.segment_search import segment_lead_search

    out = segment_lead_search(db, user_id=user, segment=segment["id"], search=_search([]), judge=_judge)

    [lead] = db.query(LeadGenResult).all()
    assert (lead.company, lead.segment_id, lead.overall_score) == ("OpenTeams", segment["id"], 88)
    assert (out["count"], out["proposed"], out["dropped"], out["failed"]) == (
        1, [{"kind": "alternative", "name": "Gumloop"}], 1, 1)
    [proposal] = market_service.list_proposals(db, user)["proposals"]
    assert (proposal["kind"], proposal["name"], proposal["segment"], proposal["source"]) == (
        "alternative", "Gumloop", segment["name"], "lead_search")


def test_searching_again_rescores_the_same_buyer_rather_than_saving_it_twice(db, user, jobs, segment):
    from apps.search.models.leadgen_model import LeadGenResult
    from apps.search.services.segment_search import segment_lead_search

    for _ in range(2):
        segment_lead_search(db, user_id=user, segment=segment["id"], search=_search([]), judge=_judge)
    assert db.query(LeadGenResult).count() == 1


def test_no_such_segment_and_no_channels_are_refused(db, user, jobs, segment):
    from apps.search.services.segment_search import SegmentSearchRefused, segment_lead_search

    with pytest.raises(SegmentSearchRefused):
        segment_lead_search(db, user_id=user, segment="Nobody", search=_search([]), judge=_judge)
    with pytest.raises(SegmentSearchRefused):
        segment_lead_search(db, user_id=user, segment=segment["id"], where="channels", search=_search([]), judge=_judge)


def test_channels_search_the_segments_confirmed_channels(db, user, jobs, segment):
    from apps.masterplan.services import market_service
    from apps.search.services.segment_search import segment_lead_search

    market_service.create_entity(db, user, {"kind": "channel", "name": "Hacker News",
                                            "url": "https://news.ycombinator.com/", "segment_id": segment["id"]})
    calls = []
    segment_lead_search(db, user_id=user, segment=segment["id"], where="channels", search=_search(calls), judge=_judge)
    assert calls[0]["domains"] == ["news.ycombinator.com"]


@pytest.mark.parametrize("url,title,company", [
    ("https://job-boards.greenhouse.io/similarweb/jobs/8198659", "Job Application for AI Engineer at Similarweb - Greenhouse", "Similarweb"),
    ("https://job-boards.greenhouse.io/openteams/jobs/4735509005", "Platform Engineer, AI/ML Infrastructure", "Openteams"),
    ("https://jobs.lever.co/acme-robotics/123", "Staff Platform Engineer", "Acme Robotics"),
    ("https://www.qovery.com/blog/self-hosted", "Running AI Agents Inside Your Own VPC - Qovery", "Qovery"),
])
def test_the_organisation_is_the_employer_not_the_job_board(url, title, company):
    from apps.search.services.segment_search import company_from_result

    assert company_from_result(url, title) == company


def test_suppression_groups_outcomes_by_segment_not_by_reworded_query():
    from apps.search.services.lead_execution_service import segment_key

    assert segment_key("seg-1", "platform engineer agents") == segment_key("seg-1", "self-hosted runtime engineer")
    assert segment_key(None, "legacy query") == "legacy query"


@pytest.mark.parametrize("facts,decision", [
    ({"org_type": "end_user", "matches_buyer": True, "problem_evidence": True}, "buyer"),
    # Owner's first run (2026-09-30): each of these was saved as a buyer at 85-90.
    ({"org_type": "vendor", "matches_buyer": True, "problem_evidence": True}, "alternative"),   # Vercel
    ({"org_type": "agency", "matches_buyer": True, "problem_evidence": True}, "intermediary"),  # Livefront
    ({"org_type": "publisher"}, "voice"),
    ({"org_type": "end_user", "matches_buyer": False, "problem_evidence": True}, "drop"),     # not regulated
    ({"org_type": "end_user", "matches_buyer": True, "problem_evidence": False}, "drop"),
    ({"org_type": "other"}, "drop"),
    ({}, "drop"),
])
def test_the_code_decides_from_the_judges_facts(facts, decision):
    from apps.search.services.segment_search import classify

    assert classify(facts) == decision


def test_a_lead_saved_by_a_laxer_judgement_is_refiled_when_rejudged(db, user, jobs, segment):
    """Vercel, saved as a buyer by the first judge, is re-judged a vendor: it leaves the leads and
    is proposed as an alternative."""
    from apps.masterplan.services import market_service
    from apps.search.models.leadgen_model import LeadGenResult
    from apps.search.services.leadgen_service import save_lead
    from apps.search.services.segment_search import segment_lead_search

    url = "https://job-boards.greenhouse.io/vercel/jobs/6207796004"
    save_lead(db, user_id=user, url=url, fields={"company": "Vercel", "query": "q", "context": "c",
                                                  "overall_score": 85, "segment_id": segment["id"]})
    db.commit()

    def search(query, **kw):
        return [{"title": "Software Engineer, Workflows", "url": url, "snippet": "Build Vercel Workflow."}]

    def judge(result, brief):
        return {"organisation": "Vercel", "org_type": "vendor", "matches_buyer": False,
                "problem_evidence": False, "reasoning": "Builds its own workflow product."}

    out = segment_lead_search(db, user_id=user, segment=segment["id"], search=search, judge=judge)
    assert (out["count"], out["retired"], out["proposed"]) == (0, 1, [{"kind": "alternative", "name": "Vercel"}])
    assert db.query(LeadGenResult).count() == 0
    assert market_service.list_proposals(db, user)["proposals"][0]["name"] == "Vercel"


def test_the_hiring_query_carries_the_buyers_kind_of_organisation():
    from apps.search.services.segment_search import build_query, buyer_organisation

    buyer = "MLOps or AI infrastructure lead in a regulated enterprise (finance, healthcare, gov)"
    assert buyer_organisation(buyer) == "regulated enterprise finance healthcare gov"
    query = build_query({"buyer": buyer, "category_terms": ["governed agent execution"]}, "hiring")
    assert query == "governed agent execution engineer regulated enterprise finance healthcare gov"


def test_saved_leads_the_search_did_not_return_are_rejudged_too(db, user, jobs, segment):
    """The owner's first run saved 13 leads; the reworked query returns different postings, so
    re-judging only what comes back would leave most of them. A lead with outreach is left alone."""
    import uuid as _uuid

    from apps.search.models.lead_action import LeadAction
    from apps.search.models.leadgen_model import LeadGenResult
    from apps.search.services.leadgen_service import save_lead
    from apps.search.services.segment_search import segment_lead_search

    agency = save_lead(db, user_id=user, url="https://job-boards.greenhouse.io/livefront/jobs/1",
                       fields={"company": "Livefront", "query": "q", "context": "Build agents for clients.",
                               "overall_score": 85, "segment_id": segment["id"]})
    contacted = save_lead(db, user_id=user, url="https://job-boards.greenhouse.io/robotsandpencils/jobs/2",
                          fields={"company": "Robots and Pencils", "query": "q", "context": "c",
                                  "overall_score": 88, "segment_id": segment["id"]})
    db.add(LeadAction(user_id=_uuid.UUID(user), lead_id=contacted.id, status="sent", channel="email"))
    db.commit()

    judged = []

    def judge(result, brief):
        judged.append(result["url"])
        return {"organisation": result["title"], "org_type": "agency", "reasoning": "Builds for clients."}

    out = segment_lead_search(db, user_id=user, segment=segment["id"], search=lambda q, **kw: [], judge=judge)

    assert judged == [agency.url]  # the contacted lead is never re-judged
    assert (out["rejudged"], out["retired"], out["proposed"]) == (1, 1, [{"kind": "intermediary", "name": "Livefront"}])
    assert [r.company for r in db.query(LeadGenResult).all()] == ["Robots and Pencils"]
