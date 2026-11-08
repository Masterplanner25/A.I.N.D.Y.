"""A trace's insights analyse only drop points owned by the user whose event named them.

`POST /rippletrace/event` took any `drop_point_id`, the event landed in the caller's own trace,
and `GET /rippletrace/{trace_id}` then ran predictions and recommendations on every drop point
its events named. A user could read another user's drop-point analysis by naming its id.
"""

from __future__ import annotations

import uuid

import pytest

from AINDY.db.models.system_event import SystemEvent
from apps.rippletrace.models import DropPointDB
from apps.rippletrace.services import rippletrace_service

pytestmark = pytest.mark.app_profile


def _drop(db, owner):
    drop = DropPointDB(
        id=f"drop-{uuid.uuid4().hex[:8]}", title="A piece", platform="notes.example.com",
        core_themes="t", tagged_entities="e", intent="published", user_id=owner,
    )
    db.add(drop)
    db.commit()
    return drop


def _event(db, owner, trace_id, drop_point_id):
    row = SystemEvent(
        type="ripple_event", user_id=owner, trace_id=trace_id, payload={"drop_point_id": drop_point_id}
    )
    db.add(row)
    db.commit()
    return {"id": str(row.id), "payload": row.payload}


def test_another_users_drop_point_named_in_my_event_is_not_analysed(db_session):
    me, victim = uuid.uuid4(), uuid.uuid4()
    theirs, mine = _drop(db_session, victim), _drop(db_session, me)
    trace = f"trace-{uuid.uuid4().hex}"
    events = [_event(db_session, me, trace, theirs.id), _event(db_session, me, trace, mine.id)]

    # With the caller (the route) and without one (the runtime's execution-graph view).
    assert rippletrace_service._owned_drop_point_ids(db_session, events, str(me)) == [mine.id]
    assert rippletrace_service._owned_drop_point_ids(db_session, events) == [mine.id]


def test_a_drop_point_counts_only_for_its_owners_own_event(db_session):
    owner, other = uuid.uuid4(), uuid.uuid4()
    drop = _drop(db_session, owner)
    trace = f"trace-{uuid.uuid4().hex}"
    owners_event = _event(db_session, owner, trace, drop.id)
    others_event = _event(db_session, other, trace, drop.id)

    assert rippletrace_service._owned_drop_point_ids(db_session, [others_event]) == []
    assert rippletrace_service._owned_drop_point_ids(db_session, [owners_event]) == [drop.id]
    # The owner's own event, but asked by someone else: still nothing.
    assert rippletrace_service._owned_drop_point_ids(db_session, [owners_event], str(other)) == []


def test_insights_never_run_engines_on_a_foreign_drop_point(db_session, monkeypatch):
    me, victim = uuid.uuid4(), uuid.uuid4()
    theirs = _drop(db_session, victim)
    trace = f"trace-{uuid.uuid4().hex}"
    event = _event(db_session, me, trace, theirs.id)

    monkeypatch.setattr(rippletrace_service, "detect_root_event", lambda db, trace_id, user_id=None: None)
    monkeypatch.setattr(rippletrace_service, "detect_terminal_events", lambda db, trace_id, user_id=None: [event])
    monkeypatch.setattr(rippletrace_service, "detect_dominant_path", lambda db, trace_id, user_id=None: [])
    monkeypatch.setattr(rippletrace_service, "detect_failure_clusters", lambda db, trace_id, user_id=None: [])
    monkeypatch.setattr(rippletrace_service, "calculate_ripple_span", lambda db, trace_id, user_id=None: {})

    called = []
    import apps.rippletrace.services.prediction_engine as prediction_engine
    import apps.rippletrace.services.recommendation_engine as recommendation_engine

    monkeypatch.setattr(prediction_engine, "predict_drop_point", lambda dp, db, **k: called.append(dp) or {})
    monkeypatch.setattr(recommendation_engine, "recommend_for_drop_point", lambda dp, db, **k: called.append(dp) or {})

    rippletrace_service.generate_trace_insights(db_session, trace, str(me))
    rippletrace_service.generate_trace_insights(db_session, trace)
    assert called == []


def _as_user(app, user_id):
    from AINDY.services.auth_service import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {"sub": str(user_id), "is_admin": False}


def test_an_event_cannot_name_another_users_drop_point(app, client, db_session):
    theirs = _drop(db_session, uuid.uuid4())
    _as_user(app, uuid.uuid4())

    refused = client.post("/apps/rippletrace/event", json={"ping_type": "mention", "drop_point_id": theirs.id})
    assert refused.status_code == 404, refused.text[:300]

    # The "bridge" sentinel and the caller's own drop point are fine.
    me = uuid.uuid4()
    mine = _drop(db_session, me)
    _as_user(app, me)
    assert client.post("/apps/rippletrace/event", json={"ping_type": "mention"}).status_code == 200
    assert client.post(
        "/apps/rippletrace/event", json={"ping_type": "mention", "drop_point_id": mine.id}
    ).status_code == 200
