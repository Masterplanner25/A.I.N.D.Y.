"""The Work model, phase A — `WORK_MODEL_SPEC.md` §3, §4, §6.

Owner, 2026-09-27: the system had no idea of the owner's series, practice, or how their projects
fit together. The load-bearing properties, in order: a work needs a summary in the owner's words;
relations are a closed vocabulary; history is kept, not overwritten; proposing writes nothing,
and a proposal is answered once (confirm or dismiss); the planner sees only what the owner stated
or confirmed.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException

from apps.masterplan.masterplan import MasterPlan
from apps.masterplan.services import work_service as ws
from apps.masterplan.services.strategy_layer_seed import seed_strategy_layer
from apps.masterplan.strategy_layer import PlanObjective
from apps.masterplan.work_model import Work, WorkRevision

pytestmark = pytest.mark.app_profile

USER = uuid.uuid4()
OTHER = uuid.uuid4()
STRUCTURE = {
    "phases": [{"name": "Foundation Building", "duration_months": 12}],
    "core_domains": [{"name": "Platform Enablement", "intent": "Build platforms."}],
    "key_assets": [
        "Nodus (orchestration DSL)",
        "Aindy-runtime (self-hosted runtime for AI agents)",
        "30+ companion packages",
    ],
}


@pytest.fixture
def plan(db_session):
    row = MasterPlan(
        start_date=datetime(2026, 1, 1), duration_years=1.0, target_date=datetime(2027, 1, 1),
        user_id=USER, status="locked", structure_json=STRUCTURE, is_active=True,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    seed_strategy_layer(db_session, masterplan_id=row.id)
    return row


@pytest.fixture
def no_containers(monkeypatch):
    import AINDY.platform_layer.registry as registry

    monkeypatch.setattr(registry, "get_job", lambda name: None)


def _work(db, name="Nodus", **extra):
    data = {"name": name, "summary": "The orchestration language.", **extra}
    return ws.create_work(db, USER, data)


def _refused(fn, status):
    with pytest.raises(HTTPException) as exc:
        fn()
    assert exc.value.status_code == status
    return exc.value


# ── declaring a work ──────────────────────────────────────────────────────────────────────


def test_a_work_needs_a_summary_in_the_owners_words(db_session):
    _refused(lambda: ws.create_work(db_session, USER, {"name": "Nodus", "summary": "  "}), 422)


def test_the_vocabularies_are_closed(db_session):
    _refused(lambda: _work(db_session, kind="vibe"), 422)
    _refused(lambda: _work(db_session, role="fan"), 422)
    _refused(lambda: _work(db_session, status="someday"), 422)


def test_defaults_and_a_duplicate_name_is_refused(db_session):
    work = _work(db_session)
    assert (work["kind"], work["role"], work["status"], work["provenance"]) == ("project", "creator", "active", "declared")
    _refused(lambda: _work(db_session, name="  nodus "), 409)


def test_editing_keeps_what_it_said_before(db_session):
    work = _work(db_session)
    ws.update_work(db_session, USER, work["id"], {"summary": "The language aindy-runtime executes.", "status": "finished"})
    revisions = {r.field: (r.old_value, r.new_value) for r in db_session.query(WorkRevision).all()}
    assert revisions["summary"] == ("The orchestration language.", "The language aindy-runtime executes.")
    assert revisions["status"] == ("active", "finished")


def test_another_users_work_is_not_found(db_session):
    work = _work(db_session)
    _refused(lambda: ws.update_work(db_session, OTHER, work["id"], {"status": "paused"}), 404)


# ── how works relate, and what they serve ─────────────────────────────────────────────────


def test_relations_are_six_verbs_and_never_to_itself(db_session):
    nodus = _work(db_session, "Nodus")
    runtime = _work(db_session, "aindy-runtime", summary="Self-hosted runtime for AI agents.")
    link = ws.add_link(db_session, USER, runtime["id"], to_work_id=nodus["id"], relation="executes")
    assert link["relation"] == "executes"
    _refused(lambda: ws.add_link(db_session, USER, runtime["id"], to_work_id=nodus["id"], relation="executes"), 409)
    _refused(lambda: ws.add_link(db_session, USER, runtime["id"], to_work_id=nodus["id"], relation="loves"), 422)
    _refused(lambda: ws.add_link(db_session, USER, nodus["id"], to_work_id=nodus["id"], relation="part_of"), 422)


def test_a_work_serves_only_objectives_of_the_owners_plan(db_session, plan):
    work = _work(db_session)
    objective = db_session.query(PlanObjective).filter(PlanObjective.masterplan_id == plan.id).first()
    out = ws.set_objectives(db_session, USER, work["id"], [objective.id])
    assert out["objective_ids"] == [objective.id]
    listed = ws.list_works(db_session, USER)["works"][0]
    assert listed["objectives"] == [{"id": objective.id, "name": "Platform Enablement"}]
    _refused(lambda: ws.set_objectives(db_session, USER, work["id"], ["not-an-objective"]), 404)


# ── proposals: derived, never stored, answered once ───────────────────────────────────────


def test_key_assets_become_proposals_and_proposing_writes_nothing(db_session, plan, no_containers):
    proposals = ws.list_proposals(db_session, USER)["proposals"]
    by_name = {p["name"]: p for p in proposals}
    assert set(by_name) == {"Nodus", "Aindy-runtime", "30+ companion packages"}
    assert by_name["Nodus"]["summary"] == "orchestration DSL"
    assert by_name["30+ companion packages"]["summary"] == ""  # no description: the owner writes one
    assert db_session.query(Work).count() == 0


def test_confirming_uses_the_owners_words_and_closes_the_proposal(db_session, plan, no_containers):
    key = next(p["key"] for p in ws.list_proposals(db_session, USER)["proposals"] if p["name"] == "Nodus")
    work = ws.confirm_proposal(db_session, USER, key, {"summary": "The language aindy-runtime executes."})
    assert (work["summary"], work["provenance"]) == ("The language aindy-runtime executes.", "confirmed")
    assert "Nodus" not in {p["name"] for p in ws.list_proposals(db_session, USER)["proposals"]}


def test_a_proposal_without_a_description_needs_one_to_confirm(db_session, plan, no_containers):
    key = next(p["key"] for p in ws.list_proposals(db_session, USER)["proposals"] if p["summary"] == "")
    _refused(lambda: ws.confirm_proposal(db_session, USER, key, {}), 422)


def test_a_dismissed_proposal_is_not_asked_again(db_session, plan, no_containers):
    key = next(p["key"] for p in ws.list_proposals(db_session, USER)["proposals"] if p["name"] == "Aindy-runtime")
    ws.dismiss_proposal(db_session, USER, key)
    assert "Aindy-runtime" not in {p["name"] for p in ws.list_proposals(db_session, USER)["proposals"]}
    _refused(lambda: ws.dismiss_proposal(db_session, USER, key), 404)


def test_confirmed_series_become_series_proposals(db_session, monkeypatch):
    import AINDY.platform_layer.registry as registry

    containers = [{"id": "c-1", "name": "2025 ChatGPT Case Study Series", "drop_count_at_decision": 42, "status": "confirmed"}]
    monkeypatch.setattr(
        registry, "get_job",
        lambda name: (lambda *, user_id, db: containers) if name == "rippletrace.confirmed_containers" else None,
    )
    proposal = ws.list_proposals(db_session, USER)["proposals"][0]
    assert (proposal["kind"], proposal["role"], proposal["container_id"]) == ("series", "author", "c-1")
    work = ws.confirm_proposal(db_session, USER, proposal["key"], {"summary": "Working AI search optimization, in public."})
    assert work["container_id"] == "c-1"
    assert ws.list_proposals(db_session, USER)["proposals"] == []


# ── what the planner sees ─────────────────────────────────────────────────────────────────


def test_the_planner_block_carries_relations_and_objectives(db_session, plan, monkeypatch):
    runtime = _work(db_session, "aindy-runtime", summary="Self-hosted runtime for AI agents.")
    nodus = _work(db_session, "Nodus", status="active")
    _work(db_session, "Old series", summary="Finished.", kind="series", status="finished")
    ws.add_link(db_session, USER, runtime["id"], to_work_id=nodus["id"], relation="executes")
    objective = db_session.query(PlanObjective).filter(PlanObjective.masterplan_id == plan.id).first()
    ws.set_objectives(db_session, USER, runtime["id"], [objective.id])

    ctx = ws.work_context(user_id=USER, db=db_session)
    assert [w["name"] for w in ctx["works"]] == ["aindy-runtime", "Nodus", "Old series"]  # active first

    import AINDY.platform_layer.registry as registry
    from apps.agent.agents import runtime_extensions

    monkeypatch.setattr(registry, "get_job", lambda name: (lambda *, user_id, db: ctx) if name == "masterplan.work_context" else None)
    block = runtime_extensions._build_work_context_block(str(USER), db_session)
    assert "- aindy-runtime (project, creator, active): Self-hosted runtime for AI agents.; executes Nodus; serves Platform Enablement" in block
    assert "do not invent more" in block


def test_no_works_adds_nothing_to_the_plan(db_session, monkeypatch):
    assert ws.work_context(user_id=USER, db=db_session) is None


def test_the_overview_shows_the_exact_block_the_agent_is_sent(db_session, plan):
    _work(db_session, "aindy-runtime", summary="Self-hosted runtime for AI agents.")
    overview = ws.works_overview(db_session, USER)
    assert overview["agent_block"] == ws.work_context(user_id=USER, db=db_session)["block"]
    assert "aindy-runtime (project, creator, active)" in overview["agent_block"]
    assert overview["objectives_available"] == [{"id": overview["objectives_available"][0]["id"], "name": "Platform Enablement"}]
