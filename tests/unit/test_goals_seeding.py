"""GOALS_LAYER_SPEC phase B: goals proposed from the plan, and the person's say (decided 2026-11-09).

A proposal is a goal with status `proposed`; nothing reads it until the person confirms it (decision 1). The anchor
becomes a measured goal; each success criterion links to the objectives that plainly serve it, or is declared.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from apps.masterplan.models import MasterPlan, PlanObjective
from apps.masterplan.services import goal_seeding as seeding
from apps.masterplan.services import goal_service

pytestmark = pytest.mark.app_profile

CRITERIA = [
    "Establishment of a widely adopted ethical AI framework",
    "Successful deployment of enabling platforms",
    "Formation of strategic partnerships",
    "Positive feedback from users and stakeholders",
    "Sustainable funding models in place",
]
OBJECTIVES = ["Ethical AI Framework", "Partnership Development", "Platform Enablement"]


def _plan(db, owner, *, plan_id):
    now = datetime.now(timezone.utc)
    plan = MasterPlan(id=plan_id, user_id=uuid.UUID(owner), start_date=now, duration_years=5.0, target_date=now,
                      is_active=True, goal_value=1_000_000, goal_unit="USD", goal_description="Financial Freedom ",
                      anchor_date=datetime(2030, 12, 31, tzinfo=timezone.utc),
                      structure_json={"success_criteria": CRITERIA})
    db.add(plan)
    db.flush()
    objectives = [PlanObjective(masterplan_id=plan_id, user_id=uuid.UUID(owner), name=n, ordinal=i)
                  for i, n in enumerate(OBJECTIVES, start=1)]
    db.add_all(objectives)
    db.commit()
    return plan, {o.name: o.id for o in objectives}


@pytest.fixture
def owner():
    return str(uuid.uuid4())


@pytest.fixture
def plan(db_session, owner):
    return _plan(db_session, owner, plan_id=900000 + uuid.uuid4().int % 90000)


def test_the_owners_criteria_suggest_the_objectives_that_serve_them():
    objectives = [{"id": n, "name": n} for n in OBJECTIVES]
    suggested = {c: seeding.suggest_objectives(c, objectives) for c in CRITERIA}
    assert suggested == {
        CRITERIA[0]: ["Ethical AI Framework"],
        CRITERIA[1]: ["Platform Enablement"],
        CRITERIA[2]: ["Partnership Development"],
        CRITERIA[3]: [],
        CRITERIA[4]: [],
    }


def test_the_plan_is_proposed_once_and_proposals_act_on_nothing(db_session, owner, plan):
    proposals = seeding.propose_goals(db_session, owner)
    assert len(proposals) == 6 and all(p["status"] == "proposed" for p in proposals)
    anchor = next(p for p in proposals if p["source"] == "anchor")
    assert anchor["name"] == "Financial Freedom" and anchor["measure"] == "anchor"
    assert anchor["target_value"] == 1_000_000 and anchor["unit"] == "USD"
    measures = {p["name"]: (p["measure"], [o["name"] for o in p["objectives"]]) for p in proposals if p["source"] != "anchor"}
    assert measures[CRITERIA[0]] == ("objectives", ["Ethical AI Framework"])
    assert measures[CRITERIA[3]] == ("declared", [])

    assert seeding.propose_goals(db_session, owner) == []  # once
    assert goal_service.get_active_goals(db_session, owner) == []  # nothing reads a proposal
    assert goal_service.rank_goals(db_session, owner) == []


def test_confirming_with_edits_makes_a_goal_active_and_measured(db_session, owner, plan, monkeypatch):
    from apps.masterplan.services import phase_advance

    _, ids = plan
    monkeypatch.setattr(phase_advance, "objective_attainment", lambda db, masterplan_id, user_id: {"objectives": [
        {"id": ids["Platform Enablement"], "attainment_pct": 0.3}, {"id": ids["Ethical AI Framework"], "attainment_pct": 0.9}]})
    proposals = seeding.propose_goals(db_session, owner)
    platforms = next(p for p in proposals if p["name"] == CRITERIA[1])
    confirmed = seeding.confirm_goal(db_session, owner, platforms["id"],
                                     {"priority": 0.8, "objective_ids": [ids["Platform Enablement"], ids["Ethical AI Framework"]]})
    assert confirmed["status"] == "active" and confirmed["measure"] == "objectives" and confirmed["priority"] == 0.8
    assert confirmed["progress"] == 0.6 and confirmed["measured"] is True
    assert [g["name"] for g in goal_service.get_active_goals(db_session, owner)] == [CRITERIA[1]]

    overview = seeding.goals_overview(db_session, owner)
    assert len(overview["proposed"]) == 5 and [g["name"] for g in overview["goals"]] == [CRITERIA[1]]
    assert [o["name"] for o in overview["objectives"]] == OBJECTIVES


def test_removing_every_link_makes_a_criterion_declared(db_session, owner, plan):
    proposals = seeding.propose_goals(db_session, owner)
    framework = next(p for p in proposals if p["name"] == CRITERIA[0])
    confirmed = seeding.confirm_goal(db_session, owner, framework["id"], {"objective_ids": []})
    assert confirmed["measure"] == "declared" and confirmed["progress"] is None and confirmed["objectives"] == []


def test_a_dropped_proposal_is_never_proposed_again(db_session, owner, plan):
    proposals = seeding.propose_goals(db_session, owner)
    feedback = next(p for p in proposals if p["name"] == CRITERIA[3])
    assert seeding.drop_goal(db_session, owner, feedback["id"])["status"] == "dropped"
    assert seeding.propose_goals(db_session, owner) == []
    assert all(g["name"] != CRITERIA[3] for g in seeding.goals_overview(db_session, owner)["proposed"])


def test_a_declared_goal_is_marked_done_and_a_measured_one_is_not(db_session, owner, plan):
    proposals = seeding.propose_goals(db_session, owner)
    funding = next(p for p in proposals if p["name"] == CRITERIA[4])
    anchor = next(p for p in proposals if p["source"] == "anchor")
    seeding.confirm_goal(db_session, owner, funding["id"])
    seeding.confirm_goal(db_session, owner, anchor["id"])
    assert seeding.update_goal(db_session, owner, funding["id"], {"status": "completed"})["status"] == "completed"
    with pytest.raises(ValueError):
        seeding.update_goal(db_session, owner, anchor["id"], {"status": "completed"})


def test_another_persons_goal_is_not_found(db_session, owner, plan):
    proposals = seeding.propose_goals(db_session, owner)
    stranger = str(uuid.uuid4())
    for call in (lambda: seeding.confirm_goal(db_session, stranger, proposals[0]["id"]),
                 lambda: seeding.drop_goal(db_session, stranger, proposals[0]["id"]),
                 lambda: seeding.update_goal(db_session, stranger, proposals[0]["id"], {"priority": 0.1}),
                 lambda: seeding.drop_goal(db_session, owner, "not-a-uuid")):
        with pytest.raises(LookupError):
            call()


def test_links_only_to_the_persons_own_objectives(db_session, owner, plan):
    other_owner = str(uuid.uuid4())
    _, theirs = _plan(db_session, other_owner, plan_id=990000 + uuid.uuid4().int % 9000)
    proposals = seeding.propose_goals(db_session, owner)
    goal = next(p for p in proposals if p["name"] == CRITERIA[2])
    confirmed = seeding.confirm_goal(db_session, owner, goal["id"], {"objective_ids": [theirs["Platform Enablement"]]})
    assert confirmed["objectives"] == [] and confirmed["measure"] == "declared"


# Route tests make ONE request each: under the shared test transaction a request's commit is not a real commit, so a
# second request sees none of the first one's writes (runtime 2.34.0 handoff §4). The lifecycle is covered above.


def _as(app, uid):
    from AINDY.services.auth_service import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {"sub": uid, "is_admin": False}


def _body(response):
    data = response.json()
    return data.get("data", data)


def test_the_overview_route_proposes_the_plan(app, client, owner, plan):
    _as(app, owner)
    response = client.get("/apps/goals/overview")
    assert response.status_code == 200, response.text[:300]
    body = _body(response)
    assert len(body["proposed"]) == 6 and body["goals"] == [] and len(body["objectives"]) == 3


@pytest.mark.parametrize("method, path, payload, expected_status", [
    ("post", "/apps/goals/{id}/confirm", {"priority": 0.9}, "active"),
    ("post", "/apps/goals/{id}/drop", None, "dropped"),
    ("patch", "/apps/goals/{id}", {"description": "edited"}, "proposed"),
])
def test_each_action_route(app, client, db_session, owner, plan, method, path, payload, expected_status):
    goal = seeding.propose_goals(db_session, owner)[0]
    _as(app, owner)
    response = getattr(client, method)(path.format(id=goal["id"]), **({"json": payload} if payload else {}))
    assert response.status_code == 200, response.text[:300]
    assert _body(response)["status"] == expected_status


def test_another_persons_goal_answers_404(app, client, db_session, owner, plan):
    goal = seeding.propose_goals(db_session, owner)[0]
    _as(app, str(uuid.uuid4()))
    assert client.post(f"/apps/goals/{goal['id']}/drop").status_code == 404


def test_a_stated_goal_is_measured_by_its_objectives_or_declared(db_session, owner, plan):
    from types import SimpleNamespace

    from apps.masterplan.syscalls.syscall_handlers import _handle_goal_create

    _, ids = plan
    ctx = SimpleNamespace(user_id=owner, metadata={"_db": db_session})
    linked = _handle_goal_create({"name": "Ship the runtime", "objective_ids": [ids["Platform Enablement"]]}, ctx)
    plain = _handle_goal_create({"name": "Read more"}, ctx)
    assert linked["goal_create_result"]["source"] == "stated"
    assert linked["goal_create_result"]["measure"] == "objectives"
    assert plain["goal_create_result"]["measure"] == "declared" and plain["goal_create_result"]["progress"] is None
