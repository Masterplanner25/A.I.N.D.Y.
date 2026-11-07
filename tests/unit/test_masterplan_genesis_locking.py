"""Regression tests for the genesis-session lock / masterplan-creation invariant.

Locks in the fix for APP-DEBT-MIGRATED-1a (TECH_DEBT.md): a single genesis
session may produce at most one masterplan, and a locked session cannot be
locked again. Two layers protect this and both are asserted here:

1. Application guard — ``create_masterplan_from_genesis`` reads the session
   under ``with_for_update()`` and rejects an already-locked session.
2. DB backstop — the partial unique index ``uq_masterplan_genesis_session_id``
   on ``master_plans.linked_genesis_session_id`` rejects a duplicate link even
   if two concurrent transactions both pass the application guard.

The DB index is what closes the original concurrency hole; the test inserts a
duplicate link directly so a regression that drops the index (e.g. a future
migration) fails here rather than in production.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-required-length-1234567890")

from AINDY.db.database import Base
from tests.helpers.app_profile import bootstrap_app_models
from tests.helpers.runtime import import_runtime_model_registry


pytestmark = pytest.mark.app_profile

masterplan_models = pytest.importorskip("apps.masterplan.models")
masterplan_factory = pytest.importorskip("apps.masterplan.services.masterplan_factory")
GenesisSessionDB = masterplan_models.GenesisSessionDB
MasterPlan = masterplan_models.MasterPlan
create_masterplan_from_genesis = masterplan_factory.create_masterplan_from_genesis


def _build_session():
    import_runtime_model_registry()
    bootstrap_app_models(required=True)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        bind=engine,
    )
    return engine, session_factory


def _synthesis_ready_session(session, *, draft=None):
    gs = GenesisSessionDB(
        status="synthesized",
        synthesis_ready=True,
        draft_json=draft or {"time_horizon_years": 5, "vision_statement": "test vision"},
    )
    session.add(gs)
    session.commit()
    session.refresh(gs)
    return gs


def _make_masterplan(gs_id, *, version_label="V1"):
    start = datetime.now(timezone.utc)
    return MasterPlan(
        version_label=version_label,
        is_origin=True,
        is_active=False,
        status="locked",
        start_date=start,
        duration_years=5,
        target_date=start + timedelta(days=365 * 5),
        linked_genesis_session_id=gs_id,
    )


def test_factory_locks_session_then_rejects_second_lock():
    """Happy path locks the session; a second lock attempt is rejected."""
    engine, session_factory = _build_session()
    session = session_factory()
    try:
        gs = _synthesis_ready_session(session)

        plan = create_masterplan_from_genesis(gs.id, {"time_horizon_years": 5}, session, user_id=None)
        assert plan.status == "locked"
        assert plan.linked_genesis_session_id == gs.id

        session.refresh(gs)
        assert gs.status == "locked"

        with pytest.raises(Exception, match="already locked"):
            create_masterplan_from_genesis(gs.id, {"time_horizon_years": 5}, session, user_id=None)
    finally:
        session.close()
        engine.dispose()


def test_duplicate_genesis_link_rejected_by_unique_index():
    """The DB backstop rejects two masterplans linked to one genesis session.

    This is the concurrency guarantee the application guard alone cannot give:
    two transactions both passing the status check still cannot both commit.
    """
    engine, session_factory = _build_session()
    session = session_factory()
    try:
        gs = _synthesis_ready_session(session)

        session.add(_make_masterplan(gs.id, version_label="V1"))
        session.add(_make_masterplan(gs.id, version_label="V2"))

        with pytest.raises(IntegrityError):
            session.commit()
    finally:
        session.rollback()
        session.close()
        engine.dispose()


def test_distinct_genesis_links_are_allowed():
    """The unique index constrains only same-session links, not all rows."""
    engine, session_factory = _build_session()
    session = session_factory()
    try:
        gs_a = _synthesis_ready_session(session)
        gs_b = _synthesis_ready_session(session)

        session.add(_make_masterplan(gs_a.id, version_label="V1"))
        session.add(_make_masterplan(gs_b.id, version_label="V1"))
        session.commit()  # must not raise

        linked = {p.linked_genesis_session_id for p in session.query(MasterPlan).all()}
        assert linked == {gs_a.id, gs_b.id}
    finally:
        session.close()
        engine.dispose()


def _owned_session(session, owner):
    gs = _synthesis_ready_session(session, draft={"time_horizon_years": 5, "vision_statement": "the owner's"})
    gs.user_id = owner
    session.commit()
    return gs


def test_only_the_owner_can_lock_a_session():
    """Another user reads as not found: no plan, the draft stays private, the owner can still lock."""
    engine, session_factory = _build_session()
    session = session_factory()
    try:
        owner, other = uuid.uuid4(), uuid.uuid4()
        gs = _owned_session(session, owner)

        with pytest.raises(Exception, match="not found"):
            create_masterplan_from_genesis(gs.id, {}, session, user_id=str(other))

        session.refresh(gs)
        assert gs.status == "synthesized"
        assert session.query(MasterPlan).count() == 0

        plan = create_masterplan_from_genesis(gs.id, {}, session, user_id=str(owner))
        assert plan.user_id == owner
        assert plan.structure_json["vision_statement"] == "the owner's"
    finally:
        session.close()
        engine.dispose()


def test_a_caller_with_no_user_cannot_lock_an_owned_session():
    engine, session_factory = _build_session()
    session = session_factory()
    try:
        gs = _owned_session(session, uuid.uuid4())

        with pytest.raises(Exception, match="not found"):
            create_masterplan_from_genesis(gs.id, {}, session, user_id=None)

        assert session.query(MasterPlan).count() == 0
    finally:
        session.close()
        engine.dispose()


def test_factory_rejects_session_not_synthesis_ready():
    """A session that has not been synthesized cannot be locked."""
    engine, session_factory = _build_session()
    session = session_factory()
    try:
        gs = GenesisSessionDB(status="active", synthesis_ready=False, draft_json={})
        session.add(gs)
        session.commit()
        session.refresh(gs)

        with pytest.raises(ValueError, match="synthesis-ready"):
            create_masterplan_from_genesis(gs.id, {}, session, user_id=None)
    finally:
        session.close()
        engine.dispose()


def test_factory_rejects_missing_session():
    """Locking a non-existent session id raises rather than creating a plan."""
    engine, session_factory = _build_session()
    session = session_factory()
    try:
        with pytest.raises(Exception, match="not found"):
            create_masterplan_from_genesis(999_999, {}, session, user_id=None)
    finally:
        session.close()
        engine.dispose()
