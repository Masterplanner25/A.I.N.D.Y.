"""DIRECTING_TIME_SPEC phase C: derived sessions (§2, decisions 1–2), the Collaborator source (decision 4), the
summary beside the watcher (§4), and the read routes."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from apps.automation.services import directing_read as dr

pytestmark = pytest.mark.app_profile

T0 = datetime(2026, 11, 17, 15, 0, tzinfo=timezone.utc)  # 08:00 in America/Denver


def _p(minute, until=None, project="C--dev-repo", source="claude_code"):
    at = T0 + timedelta(minutes=minute)
    return dr.Prompt(at=at, until=None if until is None else T0 + timedelta(minutes=until), project=project,
                     source=source)


# ── sessions ──────────────────────────────────────────────────────────────────────────


def test_prompts_within_t_chain_and_a_longer_gap_splits():
    sessions = dr.derive_sessions([_p(0, 2), _p(10, 12), _p(25, 26), _p(60, 61)])
    assert [(s.prompts, s.minutes) for s in sessions] == [(3, 26.0), (1, 1.0)]


def test_the_end_is_the_agents_last_line_capped_at_t():
    long_run = dr.derive_sessions([_p(0, 90)])
    assert long_run[0].minutes == 20.0  # capped at T (decision 2)
    no_reply = dr.derive_sessions([_p(0)])
    assert no_reply[0].minutes == 0.0


def test_the_gap_is_measured_from_the_agents_end_not_the_last_prompt():
    # The agent worked 15 minutes on the first prompt; the next came 10 minutes after it finished.
    sessions = dr.derive_sessions([_p(0, 15), _p(25, 27)])
    assert len(sessions) == 1 and sessions[0].minutes == 27.0


def test_sessions_cross_projects_and_sources():
    sessions = dr.derive_sessions([_p(0, 3), _p(5, 8, project="collaborator", source="collaborator")])
    assert sessions[0].projects == {"C--dev-repo", "collaborator"}
    assert sessions[0].sources == {"claude_code", "collaborator"}


def test_an_until_before_the_prompt_counts_as_no_reply():
    assert dr.prompt_end(_p(10, 5)) == T0 + timedelta(minutes=10)


def test_resolve_zone():
    assert dr.resolve_zone(None).key == "UTC"
    assert dr.resolve_zone("America/Denver").key == "America/Denver"
    with pytest.raises(ValueError):
        dr.resolve_zone("Not/AZone")


# ── storage-backed reads ──────────────────────────────────────────────────────────────


@pytest.fixture
def owner(db_session):
    from AINDY.db.models.user import User

    uid = uuid.uuid4()
    db_session.add(User(id=uid, email=f"{uid}@example.com", hashed_password="x", is_active=True))
    db_session.commit()
    return uid


def _event(db, owner, eid, minute, until=None):
    from apps.automation.directing import DirectingEvent

    db.add(DirectingEvent(user_id=owner, source="claude_code", project="C--dev-repo", agent_session_id="s",
                          source_event_id=eid, occurred_at=T0 + timedelta(minutes=minute),
                          agent_until=None if until is None else T0 + timedelta(minutes=until)))


def test_summary_puts_directing_beside_the_watcher_by_local_day(db_session, owner):
    from AINDY.db.models import AgentRun
    from apps.automation.models import WatcherSignal

    _event(db_session, owner, "e1", 0, 4)
    _event(db_session, owner, "e2", 10, 30)          # capped: ends at 30
    _event(db_session, owner, "e3", 9 * 60, 9 * 60 + 5)  # 17:00 Denver: a second session the same day
    # The person started a Collaborator run 15 minutes after the first session's end: it chains.
    db_session.add(AgentRun(user_id=owner, goal="g", status="completed", created_at=T0 + timedelta(minutes=45),
                            completed_at=T0 + timedelta(minutes=47)))
    # An agent-spawned run is not the person's.
    db_session.add(AgentRun(user_id=owner, goal="child", status="completed", created_at=T0 + timedelta(minutes=46),
                            completed_at=T0 + timedelta(minutes=80), parent_run_id=uuid.uuid4()))
    db_session.add(WatcherSignal(user_id=owner, signal_type="session_ended", session_id="w1", app_name="code",
                                 activity_type="work", signal_timestamp=T0 + timedelta(hours=2),
                                 duration_seconds=1800))
    # 05:30 UTC on the 18th is still the 17th in Denver.
    db_session.add(WatcherSignal(user_id=owner, signal_type="session_ended", session_id="w2", app_name="code",
                                 activity_type="work", signal_timestamp=datetime(2026, 11, 18, 5, 30,
                                                                                 tzinfo=timezone.utc),
                                 duration_seconds=600))
    db_session.commit()

    now = datetime(2026, 11, 18, 6, 0, tzinfo=timezone.utc)
    out = dr.summary(db_session, str(owner), 2, dr.resolve_zone("America/Denver"), now=now)
    assert out["in_score"] is False and out["gap_minutes"] == 20 and out["time_zone"] == "America/Denver"
    day = {d["date"]: d for d in out["daily"]}["2026-11-17"]
    assert day == {"date": "2026-11-17", "directing_minutes": 52.0, "sessions": 2, "prompts": 4,
                   "watcher_minutes": 40.0}
    assert out["totals"]["directing_minutes"] == 52.0


def test_sessions_between_never_cuts_a_running_session(db_session, owner):
    _event(db_session, owner, "e1", 0, 5)
    _event(db_session, owner, "e2", 15, 18)
    db_session.commit()
    inside = dr.sessions_between(db_session, str(owner), T0 + timedelta(minutes=10), T0 + timedelta(hours=1))
    assert inside == []  # the session started at T0, before the window
    whole = dr.sessions_between(db_session, str(owner), T0, T0 + timedelta(hours=1))
    assert [(s.prompts, s.minutes) for s in whole] == [(2, 18.0)]


def test_another_users_events_are_never_read(db_session, owner):
    from AINDY.db.models.user import User

    other = uuid.uuid4()
    db_session.add(User(id=other, email=f"{other}@example.com", hashed_password="x", is_active=True))
    db_session.commit()
    _event(db_session, other, "e1", 0, 5)
    db_session.commit()
    assert dr.sessions_between(db_session, str(owner), T0 - timedelta(hours=1), T0 + timedelta(hours=1)) == []


# ── the routes ────────────────────────────────────────────────────────────────────────


@pytest.fixture
def as_caller(app):
    from AINDY.services.auth_service import get_current_user

    caller = uuid.uuid4()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(caller), "is_admin": False}
    return caller


def test_the_summary_route_reads_for_the_caller(client, as_caller, monkeypatch):
    seen = {}

    def fake(db, user_id, days, zone, now=None):
        seen.update(user_id=user_id, days=days, zone=zone.key)
        return {"days": days, "daily": [], "totals": {}, "in_score": False}

    monkeypatch.setattr(dr, "summary", fake)
    response = client.get("/apps/directing/summary?days=7&tz=America/Denver")
    assert response.status_code == 200, response.text[:300]
    assert seen == {"user_id": str(as_caller), "days": 7, "zone": "America/Denver"}
    assert client.get("/apps/directing/summary?tz=Not/AZone").status_code == 422
    assert client.get("/apps/directing/summary?days=0").status_code == 422
    assert client.get("/apps/directing/summary?days=91").status_code == 422


def test_the_sessions_route_bounds_the_range(client, as_caller, monkeypatch):
    seen = {}

    def fake(db, user_id, start, end):
        seen.update(user_id=user_id, start=start, end=end)
        return [dr.DirectingSession(start=T0, end=T0 + timedelta(minutes=5), prompts=1, projects={"p"},
                                    sources={"claude_code"})]

    monkeypatch.setattr(dr, "sessions_between", fake)
    response = client.get("/apps/directing/sessions?from=2026-11-10&to=2026-11-18")
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    body = body.get("data", body)
    assert body["sessions"][0]["minutes"] == 5.0 and body["gap_minutes"] == 20
    assert seen["start"] == datetime(2026, 11, 10, tzinfo=timezone.utc) and seen["user_id"] == str(as_caller)
    assert client.get("/apps/directing/sessions?from=2026-11-18&to=2026-11-10").status_code == 422
    assert client.get("/apps/directing/sessions?from=2026-01-01&to=2026-11-10").status_code == 422
    assert client.get("/apps/directing/sessions?from=yesterday").status_code == 422


def test_route_names_fit_the_event_source_column():
    assert max(len("automation.directing.sessions"), len("automation.directing.summary")) <= 32
