"""Regression test for the plan-list serializer dropping `version_label`.

`MasterPlanDashboard` resolves a plan's heading as
``plan.version_label || plan.version || '#' + plan.id``. `list_masterplans` hand-picks
the fields it returns and omitted `version_label`, so the first branch was always
undefined; there is no `version` column either, so every plan rendered as its primary
key (`#10` on the live plan, whose stored label is `"V1"`).

Recorded in `docs/verification/FRONTEND_WALK_LOG.md` item 17 — which originally
mis-diagnosed this as the plan having no human-readable identity in the schema. The
column exists and is populated; only the serializer dropped it.

The sibling listing path in `masterplan_flows.py:376` already returned `version_label`,
which is why this read as an omission rather than a decision.
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

masterplan_models = pytest.importorskip("apps.masterplan.models")
masterplan_service = pytest.importorskip("apps.masterplan.services.masterplan_service")
MasterPlan = masterplan_models.MasterPlan
list_masterplans = masterplan_service.list_masterplans


def _build_session():
    import_runtime_model_registry()
    bootstrap_app_models(required=True)
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(
        autocommit=False, autoflush=False, expire_on_commit=False, bind=engine
    )()


def _make_plan(user_id, *, version_label):
    start = datetime.now(timezone.utc)
    return MasterPlan(
        user_id=user_id,
        version_label=version_label,
        is_origin=True,
        is_active=False,
        status="locked",
        posture="Stable",
        start_date=start,
        duration_years=5,
        target_date=start + timedelta(days=365 * 5),
    )


def test_list_masterplans_returns_version_label():
    """The heading the dashboard reaches for first must be in the payload."""
    session = _build_session()
    try:
        # A UUID object, not str: `master_plans.user_id` is a UUID column and the
        # SQLite dialect calls `.hex` on the bound value.
        user_id = uuid.uuid4()
        session.add(_make_plan(user_id, version_label="V1"))
        session.commit()

        plans = list_masterplans(session, user_id=user_id)["plans"]

        assert len(plans) == 1
        # Fails on the old serializer with a KeyError — the key was absent entirely,
        # not present-and-null, so the dashboard's `||` chain fell through to `#id`.
        assert plans[0]["version_label"] == "V1"
    finally:
        session.close()


def test_list_masterplans_labels_each_plan_distinctly():
    """Two versions of a plan must be distinguishable in the list, not both `#id`."""
    session = _build_session()
    try:
        # A UUID object, not str: `master_plans.user_id` is a UUID column and the
        # SQLite dialect calls `.hex` on the bound value.
        user_id = uuid.uuid4()
        session.add(_make_plan(user_id, version_label="V1"))
        session.add(_make_plan(user_id, version_label="V2"))
        session.commit()

        plans = list_masterplans(session, user_id=user_id)["plans"]

        # Newest first, per the service's `order_by(id.desc())`.
        assert [p["version_label"] for p in plans] == ["V2", "V1"]
    finally:
        session.close()
