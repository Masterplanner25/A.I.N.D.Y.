"""The masterplan's `watcher.session_ended` handler works without a session in the event (watcher first use)."""
from __future__ import annotations

import pytest

from apps.masterplan.services import watcher_events

pytestmark = pytest.mark.app_profile


def test_with_no_session_in_the_event_it_opens_its_own(monkeypatch):
    seen = {}

    class _Session:
        closed = False

        def query(self, *a, **k):  # makes it a usable session
            raise AssertionError("not used in this test")

        def close(self):
            _Session.closed = True

    import AINDY.db.database as database

    monkeypatch.setattr(database, "SessionLocal", _Session)
    monkeypatch.setattr(watcher_events, "recalculate_all_etas", lambda db: seen.setdefault("db", db) and 1)
    assert watcher_events.handle_watcher_session_ended({"type": "watcher.session_ended"}) == 1
    assert isinstance(seen["db"], _Session) and _Session.closed


def test_a_session_in_the_event_is_used(monkeypatch):
    class _Given:
        def query(self, *a, **k):
            raise AssertionError("not used in this test")

    given = _Given()
    monkeypatch.setattr(watcher_events, "recalculate_all_etas", lambda db: 7 if db is given else 0)
    assert watcher_events.handle_watcher_session_ended({"db": given}) == 7
