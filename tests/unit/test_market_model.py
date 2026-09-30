"""The Market model, phase A — `MARKET_MODEL_SPEC.md` §3, §4, §6.

Run 8b75d75d (2026-09-28) saved a competitor's listicle, an analyst's article and a trade-press
story as leads: market research with nowhere to go. The load-bearing properties: a segment is a bet
with a status and needs a buyer; entries are a closed vocabulary; the agent proposes and never
confirms; a lead re-filed as market research leaves the leads; the planner sees only what the owner
confirmed, with every status printed.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from apps.masterplan.market_model import MarketEvidence, MarketProposal, MarketRevision
from apps.masterplan.services import market_service as ms
from apps.masterplan.services import work_service as ws

pytestmark = pytest.mark.app_profile

USER = uuid.uuid4()
OTHER = uuid.uuid4()

LEADS = [
    {"id": 2, "company": "Onereach", "url": "https://onereach.ai/blog/top-10", "context": "Orchestration is the decision factor.",
     "query": "companies building AI agents", "overall_score": 81},
    {"id": 6, "company": "Crn", "url": "https://www.crn.com/news/ai/ahead", "context": "AHEAD has embedded AI into its operations.",
     "query": "companies building AI agents", "overall_score": 75},
]


@pytest.fixture
def jobs(monkeypatch):
    """search's registered jobs, stubbed: the unactioned leads, and a record of what was retired."""
    import AINDY.platform_layer.registry as registry

    retired: list[int] = []
    leads = list(LEADS)

    def unactioned(*, user_id, db):
        return [lead for lead in leads if lead["id"] not in retired]

    def retire(*, user_id, lead_id, db):
        retired.append(lead_id)
        return True

    table = {"search.unactioned_leads": unactioned, "search.retire_lead": retire}
    monkeypatch.setattr(registry, "get_job", lambda name: table.get(name))
    return retired


@pytest.fixture
def no_jobs(monkeypatch):
    import AINDY.platform_layer.registry as registry

    monkeypatch.setattr(registry, "get_job", lambda name: None)


def _refused(fn, status):
    with pytest.raises(HTTPException) as exc:
        fn()
    assert exc.value.status_code == status
    return exc.value


def _segment(db, name="Platform teams shipping agents", **extra):
    data = {"name": name, "buyer": "head of platform, 50-500-person software company", **extra}
    return ms.create_segment(db, USER, data)


# ── segments: a bet, with a buyer ─────────────────────────────────────────────────────────


def test_a_segment_needs_a_buyer_and_starts_as_a_hypothesis(db_session):
    _refused(lambda: ms.create_segment(db_session, USER, {"name": "Developers", "buyer": " "}), 422)
    segment = _segment(db_session, category_terms=["AgentOps", "agentops", " agent runtime "])
    assert segment["status"] == "hypothesis"
    assert segment["category_terms"] == ["AgentOps", "agent runtime"]


def test_status_is_a_closed_vocabulary_and_moving_it_is_kept(db_session):
    segment = _segment(db_session)
    _refused(lambda: ms.update_segment(db_session, USER, segment["id"], {"status": "probably"}), 422)
    ms.update_segment(db_session, USER, segment["id"], {"status": "testing"})
    revision = db_session.query(MarketRevision).filter_by(segment_id=segment["id"]).one()
    assert (revision.field, revision.old_value, revision.new_value) == ("status", "hypothesis", "testing")


def test_a_segment_is_served_only_by_the_owners_works(db_session):
    work = ws.create_work(db_session, USER, {"name": "aindy-runtime", "summary": "A runtime for agents."})
    theirs = ws.create_work(db_session, OTHER, {"name": "Theirs", "summary": "Not yours."})
    segment = _segment(db_session)
    _refused(lambda: ms.set_segment_works(db_session, USER, segment["id"], [theirs["id"]]), 404)
    ms.set_segment_works(db_session, USER, segment["id"], [work["id"]])
    listing = ms.list_market(db_session, USER)
    assert listing["segments"][0]["works"] == [{"id": work["id"], "name": "aindy-runtime"}]


def test_another_users_segment_is_not_found(db_session):
    segment = _segment(db_session)
    _refused(lambda: ms.update_segment(db_session, OTHER, segment["id"], {"status": "testing"}), 404)


# ── entities and evidence ─────────────────────────────────────────────────────────────────


def test_entity_kinds_are_closed(db_session):
    _refused(lambda: ms.create_entity(db_session, USER, {"kind": "friend", "name": "Onereach"}), 422)
    entity = ms.create_entity(db_session, USER, {"kind": "alternative", "name": "Onereach"})
    assert entity["segment_id"] is None


def test_deleting_a_segment_keeps_its_entries(db_session):
    segment = _segment(db_session)
    entity = ms.create_entity(db_session, USER, {"kind": "voice", "name": "Futurum", "segment_id": segment["id"]})
    ms.delete_segment(db_session, USER, segment["id"])
    listing = ms.list_market(db_session, USER)
    assert [(e["id"], e["segment_id"]) for e in listing["entities"]] == [(entity["id"], None)]


def test_evidence_belongs_to_exactly_one_record(db_session):
    segment = _segment(db_session)
    _refused(lambda: ms.add_evidence(db_session, USER, claim="x"), 422)
    ms.add_evidence(db_session, USER, claim="Three platform leads asked for this.", segment_id=segment["id"],
                    stance="supports")
    assert ms.list_market(db_session, USER)["segments"][0]["evidence"][0]["stance"] == "supports"


# ── proposals: the agent proposes, the owner confirms ─────────────────────────────────────


def test_the_agent_proposes_and_nothing_is_confirmed(db_session, no_jobs):
    out = ms.propose(db_session, USER, {
        "kind": "voice", "name": "Futurum Group", "note": "Names the category AgentOps.",
        "evidence": [{"claim": "AgentOps is poised to overtake procedural automation.", "source_url": "https://futurum"}],
    })
    assert out["proposed"] is True
    assert ms.list_market(db_session, USER)["entities"] == []
    [proposal] = ms.list_proposals(db_session, USER)["proposals"]
    assert (proposal["kind"], proposal["name"], proposal["source"]) == ("voice", "Futurum Group", "agent")


def test_a_known_or_open_proposal_is_not_stored_twice(db_session, no_jobs):
    ms.propose(db_session, USER, {"kind": "voice", "name": "Futurum Group"})
    again = ms.propose(db_session, USER, {"kind": "voice", "name": " futurum  group "})
    assert again["proposed"] is False
    ms.create_entity(db_session, USER, {"kind": "alternative", "name": "Onereach"})
    assert ms.propose(db_session, USER, {"kind": "alternative", "name": "Onereach"})["proposed"] is False


def test_an_unknown_kind_fails_the_step(db_session, no_jobs):
    with pytest.raises(ValueError):
        ms.propose(db_session, USER, {"kind": "lead", "name": "AHEAD"})


def test_confirming_a_segment_proposal_needs_a_buyer_and_links_works_by_name(db_session, no_jobs):
    work = ws.create_work(db_session, USER, {"name": "aindy-runtime", "summary": "A runtime for agents."})
    ms.propose(db_session, USER, {"kind": "segment", "name": "Platform teams", "works": ["AINDY-runtime"],
                                  "category_terms": ["AgentOps"]})
    key = ms.list_proposals(db_session, USER)["proposals"][0]["key"]
    # Refused before anything is written, so the proposal is still open.
    _refused(lambda: ms.confirm_proposal(db_session, USER, key, {}), 422)
    out = ms.confirm_proposal(db_session, USER, key, {"buyer": "head of platform"})
    segment = ms.list_market(db_session, USER)["segments"][0]
    assert (out["kind"], segment["provenance"], segment["works"][0]["id"]) == ("segment", "confirmed", work["id"])
    assert ms.list_proposals(db_session, USER)["proposals"] == []


def test_confirming_carries_the_evidence_across(db_session, no_jobs):
    ms.propose(db_session, USER, {"kind": "voice", "name": "Futurum Group",
                                  "evidence": [{"claim": "AgentOps is rising.", "source_url": "https://f"}]})
    key = ms.list_proposals(db_session, USER)["proposals"][0]["key"]
    out = ms.confirm_proposal(db_session, USER, key, {})
    row = db_session.query(MarketEvidence).filter_by(entity_id=out["record"]["id"]).one()
    assert (row.claim, row.source_kind) == ("AgentOps is rising.", "research")


# ── saved leads that were market research ─────────────────────────────────────────────────


def test_unactioned_leads_are_asked_about_and_need_a_kind(db_session, jobs):
    proposals = ms.list_proposals(db_session, USER)["proposals"]
    assert [p["key"] for p in proposals] == ["lead:2", "lead:6"]
    assert proposals[0]["kind"] is None
    _refused(lambda: ms.confirm_proposal(db_session, USER, "lead:2", {}), 422)


def test_a_lead_refiled_as_research_leaves_the_leads_under_the_owners_name(db_session, jobs):
    out = ms.confirm_proposal(db_session, USER, "lead:6", {"kind": "intermediary", "name": "AHEAD"})
    assert (out["record"]["name"], out["record"]["kind"], out["lead_retired"]) == ("AHEAD", "intermediary", True)
    assert jobs == [6]
    assert [p["key"] for p in ms.list_proposals(db_session, USER)["proposals"]] == ["lead:2"]


def test_a_dismissed_lead_stays_a_lead_and_is_not_asked_again(db_session, jobs):
    ms.dismiss_proposal(db_session, USER, "lead:2")
    assert jobs == []
    assert [p["key"] for p in ms.list_proposals(db_session, USER)["proposals"]] == ["lead:6"]
    assert db_session.query(MarketProposal).filter_by(proposal_key="lead:2").one().status == "dismissed"


# ── what the planner sees ─────────────────────────────────────────────────────────────────


def test_the_block_prints_every_status_and_only_confirmed_records(db_session, no_jobs):
    work = ws.create_work(db_session, USER, {"name": "aindy-runtime", "summary": "A runtime for agents."})
    segment = _segment(db_session, problem="pilots fall over in production", category_terms=["AgentOps"],
                       work_ids=None)
    ms.set_segment_works(db_session, USER, segment["id"], [work["id"]])
    ms.create_entity(db_session, USER, {"kind": "alternative", "name": "Onereach", "segment_id": segment["id"]})
    ms.create_entity(db_session, USER, {"kind": "voice", "name": "Futurum"})
    ms.propose(db_session, USER, {"kind": "channel", "name": "Hacker News"})

    block = ms.market_context(user_id=USER, db=db_session)["block"]

    assert "Platform teams shipping agents — HYPOTHESIS" in block
    assert "Calls it: AgentOps." in block and "Served by: aindy-runtime." in block
    assert "Alternatives: Onereach." in block
    assert "Voices, not tied to a segment: Futurum." in block
    assert "Hacker News" not in block
    assert "1 market proposals await" in block


def test_no_market_adds_nothing_to_the_plan(db_session, no_jobs):
    assert ms.market_context(user_id=USER, db=db_session) is None


def test_the_overview_shows_the_exact_block_the_agent_is_sent(db_session, no_jobs):
    _segment(db_session)
    overview = ms.market_overview(db_session, USER)
    assert overview["agent_block"] == ms.market_context(user_id=USER, db=db_session)["block"]
