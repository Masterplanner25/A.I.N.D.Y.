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


# ── phase B: claims, the ceiling, weekly, trend ───────────────────────────────────────────

from datetime import datetime, timedelta, timezone  # noqa: E402

from apps.masterplan.services import resolution_review as rr  # noqa: E402


def _finished_run(db_session, model, claims_by_engine):
    """A finished check whose answers about the brand carry these unverifiable claims."""
    brand = model["brand"]["id"]
    run = ResolutionRun(user_id=USER, scope="core", status="done", engines=list(claims_by_engine),
                        questions=[{"key": f"direct:{brand}", "kind": "direct", "subject": brand,
                                    "text": "What is Masterplan Infinite Weave?"}], calls={"perplexity": 1, "judge": 1})
    db_session.add(run)
    db_session.flush()
    for engine, claims in claims_by_engine.items():
        db_session.add(ResolutionAnswer(
            run_id=run.id, user_id=USER, question_key=f"direct:{brand}", engine=engine, answer="…",
            judgement={"claims": [{"text": c, "status": "unverifiable"} for c in claims]},
            scores={"resolution": "resolved", "facts_covered": 2, "facts_total": 4, "links_stated": 1, "links_total": 1}))
    db_session.commit()
    return run


def test_a_claim_several_engines_made_is_asked_once_and_an_answered_one_not_again(db_session, model):
    _finished_run(db_session, model, {
        "perplexity": ["Masterplan Infinite Weave is an LLC registered in Arizona", "It was founded in 2024"],
        "claude": ["Masterplan Infinite Weave is registered as an LLC in Arizona"],
        "openai": ["It is based in Phoenix, Arizona"],
    })
    claims = rr.pending_claims(db_session, USER)["claims"]
    llc = [c for c in claims if "LLC" in c["claim"]]
    assert len(llc) == 1 and llc[0]["engines"] == ["claude", "perplexity"] and llc[0]["count"] == 2
    assert claims[0] is llc[0]  # what more engines said comes first

    rr.decide_claim(db_session, USER, work_id=model["brand"]["id"], claim=llc[0]["claim"], decision="true")
    rr.decide_claim(db_session, USER, work_id=model["brand"]["id"], claim="It was founded in 2024", decision="false")
    remaining = [c["claim"] for c in rr.pending_claims(db_session, USER)["claims"]]
    assert remaining == ["It is based in Phoenix, Arizona"]
    with pytest.raises(HTTPException):
        rr.decide_claim(db_session, USER, work_id=model["brand"]["id"], claim="x", decision="maybe")


def test_the_owners_answers_become_the_next_checks_ground_truth(db_session, model):
    brand = model["brand"]["id"]
    rr.decide_claim(db_session, USER, work_id=brand, claim="It is an LLC in Arizona", decision="true")
    rr.decide_claim(db_session, USER, work_id=brand, claim="It was founded in 2024", decision="false")
    truth = rs.ground_truth(db_session, USER)
    assert "Confirmed by the owner: It is an LLC in Arizona" in rs._facts_for(truth["entities"][brand])
    assert truth["entities"][brand]["denied_claims"] == ["It was founded in 2024"]


def test_a_check_that_would_pass_the_monthly_ceiling_is_refused(db_session, model, monkeypatch):
    monkeypatch.setattr("apps.masterplan.services.resolution_engines.configured_engines",
                        lambda: ["perplexity", "openai", "claude"])
    monkeypatch.setenv("AINDY_RESOLUTION_MONTHLY_CEILING_USD", "0.10")
    with pytest.raises(HTTPException) as exc:
        rs.start_run(db_session, USER, "core")
    assert exc.value.status_code == 422 and "ceiling" in exc.value.detail["message"]

    monkeypatch.setenv("AINDY_RESOLUTION_MONTHLY_CEILING_USD", "10")
    started = rs.start_run(db_session, USER, "core")
    # an open run counts at its full estimate, so a second could not slip under the ceiling
    assert rr.month_spend(db_session, USER) == rr.estimate_cost(started["questions"], started["engines"])


def test_weekly_runs_only_for_owners_who_asked_and_not_twice_in_a_week(db_session, model, monkeypatch):
    import AINDY.db.database as database

    class Shared:
        def __getattr__(self, name):
            return getattr(db_session, name)

        def close(self):
            pass

    monkeypatch.setattr(database, "SessionLocal", lambda: Shared())
    monkeypatch.setattr("apps.masterplan.services.resolution_engines.configured_engines", lambda: ["perplexity"])
    assert rr.weekly_resolution_checks()["started"] == 0  # never ran a check: not opted in

    old = _finished_run(db_session, model, {"perplexity": []})
    old.created_at = datetime.now(timezone.utc) - timedelta(days=8)
    db_session.commit()
    assert rr.weekly_resolution_checks()["started"] == 1
    assert rr.weekly_resolution_checks()["started"] == 0  # one is open now


def test_the_trend_follows_each_question_and_engine_across_checks(db_session, model):
    _finished_run(db_session, model, {"perplexity": [], "claude": []})
    _finished_run(db_session, model, {"perplexity": []})
    out = rr.trend(db_session, USER)
    assert len(out["runs"]) == 2
    [row] = out["questions"]
    assert row["question"] == "What is Masterplan Infinite Weave?"
    assert [p["coverage"] for p in row["points"]["perplexity"]] == [0.5, 0.5]
    assert len(row["points"]["claude"]) == 1


def test_claims_are_filed_under_the_entity_they_name_and_admissions_of_ignorance_are_not_claims(db_session, model):
    """First live check: claims from "How are A.I.N.D.Y. and Aindy-runtime related?" were all filed
    under A.I.N.D.Y., and "I wasn't able to find any widely recognized meaning" was offered as a claim."""
    _finished_run(db_session, model, {
        "claude": ["aindy‑runtime is the extracted, self-hostable execution substrate",
                   "I wasn't able to find any widely recognized meaning for the term",
                   "Masterplan Infinite Weave is registered as an LLC in Arizona"],
        "openai": ["It is an LLC in Arizona, registered there"],
    })
    claims = rr.pending_claims(db_session, USER)["claims"]
    assert {c["work"] for c in claims} == {"aindy-runtime", "Masterplan Infinite Weave"}
    assert not any("widely recognized" in c["claim"] for c in claims)
    llc = [c for c in claims if "LLC" in c["claim"]]
    assert len(llc) == 1 and llc[0]["engines"] == ["claude", "openai"]  # a rewording is the same claim
