"""The RippleTrace page lists drop points in the order the api returns them, so the api returns them
newest first. Found 2026-10-25: with no order, the owner's two newest pieces sat at positions 39, 43
and 45 of 218, behind pieces from 2025, and looked as if they had not arrived.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from apps.rippletrace.drop import DropPointDB
from apps.rippletrace.services.rippletrace_services import get_all_drop_points

pytestmark = pytest.mark.app_profile

USER = uuid.uuid4()


def _drop(db, title, dropped, *, user_id=USER):
    db.add(DropPointDB(id=f"dp-{uuid.uuid4()}", title=title, platform="Medium",
                       url=f"https://example.com/{uuid.uuid4()}", date_dropped=dropped,
                       core_themes="", tagged_entities="", intent="published", user_id=user_id))


def test_drop_points_come_newest_first_with_undated_last(db_session):
    _drop(db_session, "middle", datetime(2026, 3, 5))
    _drop(db_session, "undated", None)
    _drop(db_session, "newest", datetime(2026, 10, 25))
    _drop(db_session, "oldest", datetime(2025, 6, 24))
    _drop(db_session, "someone else's", datetime(2026, 12, 1), user_id=uuid.uuid4())
    db_session.commit()
    titles = [p.title for p in get_all_drop_points(db_session, user_id=str(USER))]
    assert titles == ["newest", "middle", "oldest", "undated"]
