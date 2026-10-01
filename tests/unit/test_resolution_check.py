"""The Resolution Check, phase A — `RESOLUTION_CHECK_SPEC.md`.

The owner's definition of success, measured: does a direct search bring back the right entity, how
much of what it says is correct, does it connect the entities. The properties: ground truth is only what
the owner confirmed (Works, links, presence in their words); a person is connected to what they created
by their role; questions are generated, so a new Work is checked without a list being edited; the judge
reports facts and code scores; one engine failing never stops a check; a check runs one at a time.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from apps.masterplan.services import resolution_service as rs
from apps.masterplan.services import work_service as ws
from apps.masterplan.work_model import ResolutionAnswer, ResolutionRun

pytestmark = pytest.mark.app_profile

USER = uuid.uuid4()


@pytest.fixture
def model(db_session):
    """The owner's model as it stood on 2026-09-30: person, brand, two projects, their links, presence."""
    person = ws.create_work(db_session, USER, {
        "name": "Shawn Knight", "kind": "person", "role": "creator",
        "summary": "AI Search Optimization Specialist. Founder, Masterplan Infinite Weave."})
    brand = ws.create_work(db_session, USER, {
        "name": "Masterplan Infinite Weave", "kind": "brand", "role": "creator",
        "summary": "AI-powered execution, systems thinking, and digital strategy."})
    nodus = ws.create_work(db_session, USER, {"name": "Nodus", "summary": "An orchestration DSL.", "role": "creator"})
    runtime = ws.create_work(db_session, USER, {"name": "aindy-runtime", "summary": "A self-hosted execution substrate.",
                                                "role": "creator"})
    ws.add_link(db_session, USER, person["id"], to_work_id=brand["id"], relation="created")
    ws.add_link(db_session, USER, runtime["id"], to_work_id=nodus["id"], relation="built_on")
    ws.add_presence(db_session, USER, person["id"], {
        "platform": "LinkedIn", "url": "linkedin.com/in/masterplaninfiniteweave",
        "self_description": "AI Search Optimization Specialist | Founder, Masterplan Infinite Weave"})
    ws.add_presence(db_session, USER, brand["id"], {"platform": "Website", "url": "https://the-master-plan.com"})
    return {"person": person, "brand": brand, "nodus": nodus, "runtime": runtime}


# ── ground truth and questions ────────────────────────────────────────────────────────────


def test_presence_is_kept_in_the_owners_words_and_normalised(db_session, model):
    works = {w["name"]: w for w in ws.list_works(db_session, USER)["works"]}
    [linkedin] = works["Shawn Knight"]["presence"]
    assert linkedin["url"] == "https://linkedin.com/in/masterplaninfiniteweave"
    assert linkedin["self_description"].startswith("AI Search Optimization Specialist")
    with pytest.raises(HTTPException):
        ws.add_presence(db_session, USER, model["person"]["id"], {"platform": " "})


def test_a_person_is_connected_to_what_their_role_says_they_created(db_session, model):
    truth = rs.ground_truth(db_session, USER)
    texts = {link["text"] for link in truth["links"]}
    assert {"Shawn Knight created Masterplan Infinite Weave", "aindy-runtime built on Nodus",
            "Shawn Knight created Nodus", "Shawn Knight created aindy-runtime"} <= texts
    assert "Shawn Knight created Shawn Knight" not in texts
    assert set(truth["own_hosts"]) == {"linkedin.com", "the-master-plan.com"}


def test_questions_are_generated_from_the_model(db_session, model):
    questions = rs.build_questions(rs.ground_truth(db_session, USER), "core")
    texts = [q["text"] for q in questions]
    assert texts[:3] == ["What is Masterplan Infinite Weave?", "Who is Shawn Knight?",
                         "Who is Shawn Knight, the founder of Masterplan Infinite Weave?"]
    assert "What is Nodus?" in texts and "How are aindy-runtime and Nodus related?" in texts
    assert not any("created" in q["key"] and q["kind"] == "relation" and q["key"].startswith("implied") for q in questions)


# ── scoring: the judge reports facts, code scores ─────────────────────────────────────────


def test_the_three_criteria_become_numbers(db_session, model):
    truth = rs.ground_truth(db_session, USER)
    judgement = {"about": "mixed", "other_entities": ["nodus.com"],
                 "claims": [{"text": "a DSL", "status": "correct"}, {"text": "an LLC in Arizona", "status": "unverifiable"},
                            {"text": "a camera mount", "status": "incorrect"}],
                 "facts_stated": ["F1", "F2", "F9"], "links_stated": ["L1"],
                 "_facts": ["f1", "f2", "f3"], "_links": ["l1", "l2"]}
    scores = rs.score(judgement, ["https://the-master-plan.com/about", "https://nodus.com"], truth)
    assert scores["resolution"] == "mixed" and scores["other_entities"] == ["nodus.com"]
    assert (scores["claims_correct"], scores["claims_incorrect"], scores["claims_unverifiable"]) == (1, 1, 1)
    assert (scores["facts_covered"], scores["facts_total"]) == (2, 3)  # F9 does not exist
    assert (scores["links_stated"], scores["links_total"]) == (1, 2)
    assert scores["own_sources_cited"] == ["the-master-plan.com"]


# ── runs ──────────────────────────────────────────────────────────────────────────────────


def _engines(fail: str | None = None):
    def make(name):
        def ask(question):
            if name == fail:
                raise RuntimeError("HTTP 529 overloaded")
            return {"answer": f"{name} on: {question}", "citations": ["https://the-master-plan.com"]}
        return ask
    return {name: make(name) for name in ("perplexity", "openai", "claude")}


def _judge(question, answer, truth):
    return {"about": "subject", "claims": [{"text": "x", "status": "correct"}], "facts_stated": ["F1"],
            "links_stated": [], "_facts": ["f1"], "_links": []}


def test_a_check_is_answered_in_batches_and_one_engine_failing_does_not_stop_it(db_session, model, monkeypatch):
    monkeypatch.setattr("apps.masterplan.services.resolution_engines.configured_engines",
                        lambda: ["perplexity", "openai", "claude"])
    started = rs.start_run(db_session, USER, "core")
    with pytest.raises(HTTPException) as exc:
        rs.start_run(db_session, USER, "core")
    assert exc.value.status_code == 409  # one at a time

    run = db_session.get(ResolutionRun, started["id"])
    expected = started["expected"]
    while run.status != "done":
        rs.process_run(db_session, run, limit=4, ask=_engines(fail="claude"), judge=_judge)

    answers = db_session.query(ResolutionAnswer).filter_by(run_id=run.id).all()
    assert len(answers) == expected
    failed = [a for a in answers if a.engine == "claude"]
    assert all(a.error and a.scores is None for a in failed)
    ok = [a for a in answers if a.engine != "claude"]
    assert all(a.scores["resolution"] == "resolved" for a in ok)
    assert run.calls["judge"] == len(ok) and "claude" not in run.calls

    overview = rs.resolution_overview(db_session, USER)
    assert overview["latest"]["answered"] == expected
    assert overview["self_descriptions"] == [{
        "work": "Shawn Knight", "kind": "person", "platform": "LinkedIn",
        "url": "https://linkedin.com/in/masterplaninfiniteweave",
        "self_description": "AI Search Optimization Specialist | Founder, Masterplan Infinite Weave"}]


def test_nothing_to_check_until_there_are_works(db_session):
    with pytest.raises(HTTPException) as exc:
        rs.start_run(db_session, uuid.uuid4(), "core")
    assert exc.value.status_code == 422



def test_a_pair_with_two_confirmed_links_is_asked_once_and_checked_against_both(db_session, model):
    """The first live check asked "How are Nodus and Aindy-runtime related?" twice: the owner has
    confirmed two links between them."""
    ws.add_link(db_session, USER, model["nodus"]["id"], to_work_id=model["runtime"]["id"], relation="part_of")
    truth = rs.ground_truth(db_session, USER)
    relations = [q for q in rs.build_questions(truth, "full") if q["kind"] == "relation"]
    nodus_runtime = [q for q in relations if "Nodus" in q["text"] and "aindy-runtime" in q["text"]]
    assert len(nodus_runtime) == 1
    assert {link["text"] for link in rs._links_for(truth, nodus_runtime[0])} == {
        "aindy-runtime built on Nodus", "Nodus part of aindy-runtime"}
