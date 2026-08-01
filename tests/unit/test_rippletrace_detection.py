"""Echo detection: what counts as a ripple, and what must never be recorded as one.

The filters are the whole substance here. A ping drives ``spread_score`` (distinct
platforms) and ``narrative_score``, so a filter that lets your own site through turns
self-publication into measured reach — the domain would report spread that did not
happen, which is worse than reporting nothing.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-required-length-1234567890")

from AINDY.db.database import Base
from tests.helpers.app_profile import bootstrap_app_models
from tests.helpers.runtime import import_runtime_model_registry

pytestmark = pytest.mark.app_profile

detection = pytest.importorskip("apps.rippletrace.services.ripple_detection")
mention_search = pytest.importorskip("apps.rippletrace.services.mention_search")
DropPointDB = pytest.importorskip("apps.rippletrace.models").DropPointDB
PingDB = pytest.importorskip("apps.rippletrace.models").PingDB

Hit = mention_search.SearchHit


def _build_session():
    import_runtime_model_registry()
    bootstrap_app_models(required=True)
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(
        autocommit=False, autoflush=False, expire_on_commit=False, bind=engine
    )()


def _drop_point(**overrides):
    defaults = {
        "id": "dp-test",
        "title": "Systems that measure achievement, not activity",
        "platform": "notes.example.com",
        "url": "https://notes.example.com/p/achievement",
        "date_dropped": datetime(2026, 7, 1, tzinfo=timezone.utc),
        "core_themes": "measurement",
        "tagged_entities": "",
        "intent": "published",
    }
    defaults.update(overrides)
    return DropPointDB(**defaults)


# ── Query construction ────────────────────────────────────────────────────────


def test_build_queries_uses_url_and_distinctive_title():
    queries = detection.build_queries(_drop_point())
    assert queries[0] == "https://notes.example.com/p/achievement"
    assert queries[1] == '"Systems that measure achievement, not activity"'


def test_build_queries_skips_generic_title():
    """A short title as a phrase query would match unrelated pages, each becoming spread."""
    queries = detection.build_queries(_drop_point(title="Second post"))
    assert queries == ["https://notes.example.com/p/achievement"]


def test_build_queries_empty_without_url_or_title():
    assert detection.build_queries(_drop_point(url=None, title="Hi")) == []


# ── Filters ───────────────────────────────────────────────────────────────────


def test_filter_rejects_same_host():
    drop_point = _drop_point()
    hits = [
        Hit(url="https://notes.example.com/tag/measurement", title="Tag index"),
        Hit(url="https://www.notes.example.com/p/other", title="Another of my posts"),
        Hit(url="https://someoneelse.com/post", title="Someone reacting"),
    ]
    kept, rejected = detection.filter_hits(hits, drop_point=drop_point)
    assert [hit.url for hit in kept] == ["https://someoneelse.com/post"]
    assert rejected["same_host"] == 2


def test_filter_rejects_the_drop_point_itself():
    drop_point = _drop_point(url="https://a.example/p/one")
    hits = [Hit(url="https://a.example/p/one/?utm_source=x", title="The post itself")]
    kept, rejected = detection.filter_hits(hits, drop_point=drop_point)
    assert kept == []
    # Tracking params must not disguise the article as an echo of itself.
    assert rejected["self"] == 1


def test_filter_rejects_pages_published_before_the_drop_point():
    """Prior art is not a reaction. A page that predates you cannot be echoing you."""
    drop_point = _drop_point(date_dropped=datetime(2026, 7, 1, tzinfo=timezone.utc))
    hits = [
        Hit(url="https://old.example/post", title="Older", published="2026-06-01"),
        Hit(url="https://new.example/post", title="Newer", published="2026-07-15"),
    ]
    kept, rejected = detection.filter_hits(hits, drop_point=drop_point)
    assert [hit.url for hit in kept] == ["https://new.example/post"]
    assert rejected["predates"] == 1


def test_filter_keeps_undated_hits():
    """Most results carry no date; absence of a date is not evidence of prior art."""
    drop_point = _drop_point()
    kept, _ = detection.filter_hits([Hit(url="https://x.example/a")], drop_point=drop_point)
    assert len(kept) == 1


# ── Ping identity ─────────────────────────────────────────────────────────────


def test_ping_id_is_stable_across_tracking_noise():
    first = detection.ping_id_for("dp-1", "https://x.example/post")
    second = detection.ping_id_for("dp-1", "https://x.example/post/?utm_source=rss#c")
    assert first == second
    assert detection.ping_id_for("dp-2", "https://x.example/post") != first


def test_detection_is_idempotent_and_scores_the_drop_point(monkeypatch):
    """Re-running detection must re-find the same references without inflating spread."""
    session = _build_session()
    try:
        drop_point = _drop_point(id="dp-idem", user_id=None)
        session.add(drop_point)
        session.commit()

        hits = [
            Hit(url="https://alpha.example/mentions-you", title="Alpha wrote about it"),
            Hit(url="https://beta.example/also", title="Beta too"),
        ]
        monkeypatch.setattr(detection, "search", lambda *a, **k: hits)

        first = detection.detect_for_drop_point(session, drop_point)
        assert first["created"] == 2
        # Two distinct hosts -> spread of 2. This is the number the whole domain exists
        # to produce, so it is asserted rather than assumed.
        assert first["spread_score"] == 2
        assert first["narrative_score"] > 0

        second = detection.detect_for_drop_point(session, drop_point)
        assert second["created"] == 0
        assert session.query(PingDB).count() == 2
        assert second["spread_score"] == 2
    finally:
        session.close()


def test_detection_stamps_checked_at_even_with_no_results(monkeypatch):
    """"Searched, found nothing" must be recorded, or the sweep re-pays for it forever."""
    session = _build_session()
    try:
        drop_point = _drop_point(id="dp-empty", user_id=None)
        session.add(drop_point)
        session.commit()
        monkeypatch.setattr(detection, "search", lambda *a, **k: [])

        outcome = detection.detect_for_drop_point(session, drop_point)
        assert outcome["created"] == 0
        assert drop_point.mentions_checked_at is not None
    finally:
        session.close()


def test_due_selection_respects_the_minimum_interval(monkeypatch):
    session = _build_session()
    try:
        recent = _drop_point(id="dp-recent", user_id=None, url="https://a.example/1")
        recent.mentions_checked_at = datetime.now(timezone.utc) - timedelta(hours=1)
        stale = _drop_point(id="dp-stale", user_id=None, url="https://a.example/2")
        stale.mentions_checked_at = datetime.now(timezone.utc) - timedelta(days=3)
        never = _drop_point(id="dp-never", user_id=None, url="https://a.example/3")
        session.add_all([recent, stale, never])
        session.commit()

        due = detection._due_drop_points(session, user_id=None, limit=10)
        ids = {row.id for row in due}
        assert "dp-recent" not in ids
        assert {"dp-stale", "dp-never"} <= ids
    finally:
        session.close()


# ── Availability ──────────────────────────────────────────────────────────────


def test_search_without_key_raises_unavailable(monkeypatch):
    """Not "found nothing" — the caller must be able to tell a failed search apart."""
    monkeypatch.delenv(mention_search.API_KEY_ENV, raising=False)
    with pytest.raises(mention_search.MentionSearchUnavailable):
        mention_search.search(["anything"])


def test_detection_job_is_opt_in(monkeypatch):
    monkeypatch.delenv(detection.DETECTION_FLAG, raising=False)
    assert detection.detect_due_mentions() == {"skipped": True, "reason": "flag_disabled"}


def test_detection_job_needs_a_key(monkeypatch):
    monkeypatch.setenv(detection.DETECTION_FLAG, "1")
    monkeypatch.delenv(mention_search.API_KEY_ENV, raising=False)
    assert detection.detect_due_mentions() == {"skipped": True, "reason": "no_api_key"}
