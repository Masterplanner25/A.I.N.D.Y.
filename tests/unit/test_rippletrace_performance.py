"""RippleTrace as an Infinity feeder, and as a goal-attainment source.

Two things are load-bearing and get asserted rather than assumed:

* **"No echo" must require having looked.** A drop point with no pings is only a failure
  signal if detection actually ran against it. Reporting never-searched content as
  failure would tell the loop that publishing does not work, on no evidence.
* **The success bar is the domain's own.** The signal uses ``SUCCESS_NARRATIVE_THRESHOLD``
  from strategy_engine, so the loop and the strategy builder cannot disagree about what
  a successful drop point is.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

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

perf = pytest.importorskip("apps.rippletrace.services.ripple_performance_service")
models = pytest.importorskip("apps.rippletrace.models")
DropPointDB, PingDB, PlaybookDB = models.DropPointDB, models.PingDB, models.PlaybookDB

USER = uuid.uuid4()


def _build_session():
    import_runtime_model_registry()
    bootstrap_app_models(required=True)
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(
        autocommit=False, autoflush=False, expire_on_commit=False, bind=engine
    )()


def _drop(session, ident, **overrides):
    defaults = {
        "id": ident,
        "title": f"Post {ident}",
        "platform": "notes.example.com",
        "url": f"https://notes.example.com/{ident}",
        "core_themes": "",
        "tagged_entities": "",
        "intent": "published",
        "user_id": USER,
    }
    defaults.update(overrides)
    row = DropPointDB(**defaults)
    session.add(row)
    return row


def _ping(session, ident, drop_point_id, platform="other.example.com"):
    session.add(
        PingDB(
            id=ident,
            drop_point_id=drop_point_id,
            ping_type="mention",
            source_platform=platform,
            date_detected=datetime(2026, 7, 1),
            connection_summary="someone referenced it",
            external_url=f"https://{platform}/{ident}",
            user_id=USER,
            strength=1.0,
            connection_type="direct",
        )
    )


# ── Signals ───────────────────────────────────────────────────────────────────


def test_success_signal_uses_the_domains_own_threshold():
    session = _build_session()
    try:
        _drop(session, "dp-hit", narrative_score=perf.SUCCESS_NARRATIVE_THRESHOLD + 5, spread_score=4)
        _drop(session, "dp-miss", narrative_score=perf.SUCCESS_NARRATIVE_THRESHOLD - 1)
        session.commit()

        signals = perf.get_ripple_performance_signals(session, user_id=str(USER))
        success = [s for s in signals if s["type"] == "success"]
        assert len(success) == 1
        assert success[0]["reason"] == "content_reached_beyond_own_audience"
        assert success[0]["content"] == "Post dp-hit"
    finally:
        session.close()


def test_no_echo_signal_requires_having_searched():
    """Never-searched content must not be reported as failure — that is no evidence."""
    session = _build_session()
    try:
        _drop(session, "dp-never-checked")  # mentions_checked_at stays None
        session.commit()
        signals = perf.get_ripple_performance_signals(session, user_id=str(USER))
        assert [s for s in signals if s["type"] == "failure"] == []

        _drop(
            session,
            "dp-checked",
            mentions_checked_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        )
        session.commit()
        signals = perf.get_ripple_performance_signals(session, user_id=str(USER))
        failures = [s for s in signals if s["type"] == "failure"]
        assert len(failures) == 1
        assert failures[0]["reason"] == "published_without_echo"
        assert failures[0]["content"] == "Post dp-checked"
    finally:
        session.close()


def test_no_echo_signal_ignores_content_that_did_echo():
    session = _build_session()
    try:
        _drop(
            session,
            "dp-echoed",
            mentions_checked_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        )
        session.commit()
        _ping(session, "ping-1", "dp-echoed")
        session.commit()

        signals = perf.get_ripple_performance_signals(session, user_id=str(USER))
        assert [s for s in signals if s["type"] == "failure"] == []
    finally:
        session.close()


def test_spread_pattern_needs_more_than_one_instance():
    session = _build_session()
    try:
        _drop(session, "dp-a", spread_score=perf.CROSS_PLATFORM_SPREAD_THRESHOLD)
        session.commit()
        assert [
            s for s in perf.get_ripple_performance_signals(session, user_id=str(USER))
            if s["type"] == "pattern"
        ] == []

        _drop(session, "dp-b", spread_score=perf.CROSS_PLATFORM_SPREAD_THRESHOLD + 1)
        session.commit()
        patterns = [
            s for s in perf.get_ripple_performance_signals(session, user_id=str(USER))
            if s["type"] == "pattern"
        ]
        assert len(patterns) == 1
        assert patterns[0]["count"] == 2
    finally:
        session.close()


def test_signals_are_scoped_to_the_user():
    session = _build_session()
    try:
        _drop(session, "dp-mine", narrative_score=99.0)
        _drop(session, "dp-theirs", narrative_score=99.0, user_id=uuid.uuid4())
        session.commit()

        signals = perf.get_ripple_performance_signals(session, user_id=str(USER))
        success = [s for s in signals if s["type"] == "success"]
        assert success and success[0]["content"] == "Post dp-mine"
    finally:
        session.close()


def test_signals_respect_the_limit():
    session = _build_session()
    try:
        _drop(session, "dp-1", narrative_score=99.0, spread_score=5)
        _drop(session, "dp-2", spread_score=5)
        _drop(
            session, "dp-3", mentions_checked_at=datetime(2026, 7, 20, tzinfo=timezone.utc)
        )
        session.commit()
        assert len(perf.get_ripple_performance_signals(session, user_id=str(USER), limit=1)) == 1
    finally:
        session.close()


def test_empty_domain_produces_no_signals():
    session = _build_session()
    try:
        assert perf.get_ripple_performance_signals(session, user_id=str(USER)) == []
    finally:
        session.close()


# ── Goal metric ───────────────────────────────────────────────────────────────


def test_goal_metric_counts_playbooks_and_declares_global_scope():
    session = _build_session()
    try:
        result = perf.get_goal_metric(session, unit="playbooks", user_id=str(USER))
        assert result == {"supported": True, "unit": "playbooks", "value": 0.0, "scope": "global"}

        session.add(PlaybookDB(id="pb-1", strategy_id="s-1", title="One", steps="[]"))
        session.add(PlaybookDB(id="pb-2", strategy_id="s-2", title="Two", steps="[]"))
        session.commit()

        result = perf.get_goal_metric(session, unit="playbooks", user_id=str(USER))
        assert result["value"] == 2.0
        # Reported, not hidden: playbooks carry no owner, so a multi-user deployment
        # would be counting other people's.
        assert result["scope"] == "global"
    finally:
        session.close()


def test_goal_metric_rejects_units_it_cannot_answer():
    session = _build_session()
    try:
        assert perf.get_goal_metric(session, unit="books")["supported"] is False
        assert perf.get_goal_metric(session, unit="")["supported"] is False
    finally:
        session.close()


def test_playbooks_is_now_a_registered_goal_attainment_unit():
    """The unit was aliased but unresolvable while the table was empty."""
    goal_attainment = pytest.importorskip(
        "apps.analytics.services.integration.goal_attainment"
    )
    assert "playbooks" in goal_attainment.supported_units()
    assert goal_attainment.normalize_unit("Playbook") == "playbooks"
