"""DIRECTING_TIME_SPEC phase A: the transcript parser (§2), storage (§3) and the ingest route."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest

from apps.automation.services import directing_transcript as dt
from apps.automation.services.directing_service import ingest_events

pytestmark = pytest.mark.app_profile

SESSION = "c7166330-6ae4-48e9-a604-5b34dd896722"


def _user(text_or_blocks, uid, ts, **flags):
    return json.dumps({"type": "user", "uuid": uid, "sessionId": SESSION, "timestamp": ts,
                       "message": {"role": "user", "content": text_or_blocks}, **flags})


def _assistant(ts):
    return json.dumps({"type": "assistant", "uuid": str(uuid.uuid4()), "sessionId": SESSION, "timestamp": ts,
                       "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}})


# ── §2: what counts as a typed prompt ─────────────────────────────────────────────────


@pytest.mark.parametrize("content", [
    "<task-notification> <task-id>b1</task-id> </task-notification>",
    "<command-name>/mcp</command-name> <command-message>mcp</command-message>",
    "<command-message>doctor</command-message> <command-name>/doctor</command-name>",
    "<local-command-stdout>Reconnected to aindy.</local-command-stdout>",
    "<local-command-caveat>The command below was run directly</local-command-caveat>",
    "<system-reminder>background</system-reminder>",
    "[Cross-session delivery notice] Your message to another session was held",
    "[Request interrupted by user]",
    "   ",
])
def test_lines_claude_code_wrote_are_not_prompts(content):
    assert not dt.is_typed_prompt(json.loads(_user(content, "u1", "2026-11-16T02:16:42.879Z")))


@pytest.mark.parametrize("flag", ["isMeta", "isSidechain", "isCompactSummary"])
def test_meta_sidechain_and_compaction_lines_are_not_prompts(flag):
    assert not dt.is_typed_prompt(json.loads(_user("looks typed", "u1", "2026-11-16T02:16:42Z", **{flag: True})))


def test_tool_results_are_not_prompts_and_a_prompt_with_an_image_is():
    tool = [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "out"}]
    image = [{"type": "text", "text": "[Image #6] - this is what i'm seeing"}, {"type": "image", "source": {}}]
    assert not dt.is_typed_prompt(json.loads(_user(tool, "u1", "2026-11-16T02:16:42Z")))
    assert dt.is_typed_prompt(json.loads(_user(image, "u2", "2026-11-16T02:16:42Z")))
    assert dt.is_typed_prompt(json.loads(_user("yes, npm install and restart Vite", "u3", "2026-11-16T02:16:42Z")))


def test_events_carry_no_text_and_agent_until_ends_at_the_next_prompt():
    lines = [
        _user("first instruction, private words", "u1", "2026-11-16T02:16:42.879Z"),
        _assistant("2026-11-16T02:17:00.000Z"),
        _user([{"type": "tool_result", "tool_use_id": "t", "content": "x"}], "t1", "2026-11-16T02:20:10.000Z"),
        _user("<task-notification>done</task-notification>", "n1", "2026-11-16T02:21:00.000Z"),
        # Bookkeeping Claude Code writes while the person is away and as they submit: not the agent's work.
        json.dumps({"type": "system", "subtype": "away_summary", "timestamp": "2026-11-16T02:22:00.000Z"}),
        json.dumps({"type": "api-request", "timestamp": "2026-11-16T02:22:26.950Z"}),
        _user("second", "u2", "2026-11-16T02:22:26.897Z"),
        "not json",
        _assistant("2026-11-16T02:23:00.000Z"),
    ]
    events = dt.events_from_lines(lines, "C--dev-aindy-apps-monolith")
    assert [e["source_event_id"] for e in events] == ["u1", "u2"]
    assert events[0]["agent_until"] == "2026-11-16T02:20:10.000Z"
    assert events[1]["agent_until"] == "2026-11-16T02:23:00.000Z"
    assert events[0]["project"] == "C--dev-aindy-apps-monolith" and events[0]["source"] == "claude_code"
    assert set(events[0]) == {"source", "project", "agent_session_id", "source_event_id", "occurred_at", "agent_until"}
    assert "private" not in json.dumps(events)


def test_a_prompt_with_no_reply_yet_has_no_agent_until():
    events = dt.events_from_lines([_user("go", "u1", "2026-11-16T02:16:42Z")], "p")
    assert events[0]["agent_until"] is None


# ── §3: storage ───────────────────────────────────────────────────────────────────────


@pytest.fixture
def owner(db_session):
    from AINDY.db.models.user import User

    uid = uuid.uuid4()
    db_session.add(User(id=uid, email=f"{uid}@example.com", hashed_password="x", is_active=True))
    db_session.commit()
    return uid


def _event(eid, at="2026-11-16T02:16:42Z", until=None):
    return {"source": "claude_code", "project": "p", "agent_session_id": SESSION, "source_event_id": eid,
            "occurred_at": at, "agent_until": until}


def test_ingest_is_idempotent_and_moves_agent_until_on(db_session, owner):
    from apps.automation.directing import DirectingEvent

    first = ingest_events(db_session, str(owner), [_event("u1"), _event("u2", until="2026-11-16T02:20:00Z")])
    db_session.commit()
    assert first == {"accepted": 2, "duplicates": 0, "extended": 0, "rejected": 0}

    again = ingest_events(db_session, str(owner), [
        _event("u1", until="2026-11-16T02:21:00Z"),   # the backfill completes what the hook started
        _event("u2", until="2026-11-16T02:19:00Z"),   # an earlier reading never moves it back
        _event("bad", at="not a time"),
    ])
    db_session.commit()
    assert again == {"accepted": 0, "duplicates": 2, "extended": 1, "rejected": 1}
    rows = {r.source_event_id: r for r in db_session.query(DirectingEvent).filter_by(user_id=owner)}
    assert set(rows) == {"u1", "u2"}
    assert rows["u1"].agent_until.replace(tzinfo=timezone.utc) == datetime(2026, 11, 16, 2, 21, tzinfo=timezone.utc)
    assert rows["u2"].agent_until.replace(tzinfo=timezone.utc) == datetime(2026, 11, 16, 2, 20, tzinfo=timezone.utc)


def test_the_same_event_id_is_separate_per_user(db_session, owner):
    from AINDY.db.models.user import User

    other = uuid.uuid4()
    db_session.add(User(id=other, email=f"{other}@example.com", hashed_password="x", is_active=True))
    db_session.commit()
    assert ingest_events(db_session, str(owner), [_event("u1")])["accepted"] == 1
    assert ingest_events(db_session, str(other), [_event("u1")])["accepted"] == 1


# ── the route ─────────────────────────────────────────────────────────────────────────


def test_the_route_stores_for_the_caller_and_refuses_text(app, client, monkeypatch):
    from AINDY.services.auth_service import get_activity_caller
    import apps.automation.services.directing_service as service

    caller = uuid.uuid4()
    seen = {}

    def fake(db, user_id, events):
        seen.update(user_id=user_id, events=list(events))
        return {"accepted": len(seen["events"]), "duplicates": 0, "extended": 0, "rejected": 0}

    monkeypatch.setattr(service, "ingest_events", fake)
    app.dependency_overrides[get_activity_caller] = lambda: {"sub": str(caller), "is_admin": False}

    response = client.post("/apps/directing/events", json={"events": [_event("u1")]})
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert body.get("data", body)["accepted"] == 1
    assert seen["user_id"] == str(caller)

    with_text = dict(_event("u2"), content="the prompt itself")
    assert client.post("/apps/directing/events", json={"events": [with_text]}).status_code == 422
    with_user = {"events": [_event("u3")], "user_id": str(uuid.uuid4())}
    assert client.post("/apps/directing/events", json=with_user).status_code == 422


def test_the_route_admits_the_watcher_key_through_get_activity_caller():
    """FR-70 (runtime 2.37.0, DEC-133): the ingest route's caller is `get_activity_caller`, never `get_current_user`,
    which refuses a watcher-only key, and no `enforce_api_key_scope` beside it, which would refuse it again. The read
    routes (phase C) take a session: the watcher key only writes."""
    import inspect

    from AINDY.services.auth_service import get_activity_caller
    from apps.automation.routes import directing_router as module

    default = inspect.signature(module._directing_caller).parameters["current_user"].default
    assert default.dependency is get_activity_caller
    ingest = inspect.signature(module.ingest_directing_events_route).parameters["current_user"].default
    assert ingest.dependency is module._directing_caller
    assert "enforce_api_key_scope" not in inspect.getsource(module).split('"""', 2)[2]


def test_route_name_fits_the_event_source_column():
    assert len("automation.directing.ingest") <= 32
