"""Regression tests for ``/apps/compute/create_masterplan``.

The route was structurally incapable of succeeding. ``create_masterplan_compute``
passed the request body straight into ``MasterPlan(**data)``, but:

1. ``MasterPlanInput`` required a ``name`` field the ORM has no column for, so every
   call raised ``TypeError: 'name' is an invalid keyword argument for MasterPlan``
   and returned HTTP 500 — verified live before the fix.
2. ``master_plans.target_date`` is NOT NULL and was never supplied, so even without
   ``name`` the insert would have failed.

Both are asserted here, plus the serialization gap: the compute routes returned the
ORM object itself, which the response envelope rendered as ``{}`` — a caller could not
read back even the new plan's id.
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

compute_service = pytest.importorskip("apps.analytics.services.calculations.compute_service")
create_masterplan_compute = compute_service.create_masterplan_compute
list_masterplans_compute = compute_service.list_masterplans_compute


def _build_session():
    import_runtime_model_registry()
    bootstrap_app_models(required=True)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(
        autocommit=False, autoflush=False, expire_on_commit=False, bind=engine
    )()


def _payload(**overrides):
    """The exact body FastAPI builds from MasterPlanInput, including `name`."""
    body = {
        "name": "my plan",
        "start_date": datetime(2026, 1, 1, tzinfo=timezone.utc).replace(tzinfo=None),
        "duration_years": 1,
        "wcu_target": 1.0,
        "revenue_target": 1.0,
        "books_required": 0,
        "platform_required": False,
        "studio_required": False,
        "playbooks_required": 0,
    }
    body.update(overrides)
    return body


def test_create_succeeds_with_the_name_field_present():
    """`name` maps to no column — it must be discarded, not passed to the ORM."""
    session = _build_session()
    user_id = str(uuid.uuid4())

    result = create_masterplan_compute(session, data=_payload(), user_id=user_id)

    assert result["id"] is not None
    # Previously this raised TypeError: 'name' is an invalid keyword argument.
    assert "name" not in result


def test_target_date_is_derived_from_the_horizon():
    """target_date is NOT NULL and absent from the input; it must be computed."""
    session = _build_session()

    result = create_masterplan_compute(session, data=_payload(duration_years=2), user_id=str(uuid.uuid4()))

    # 2026-01-01 + 730 days (neither 2026 nor 2027 is a leap year).
    assert result["target_date"].startswith("2028-01-01")


def test_first_plan_is_origin_and_later_plans_are_not():
    """Matches the lineage rule create_masterplan_from_genesis applies."""
    session = _build_session()
    user_id = str(uuid.uuid4())

    first = create_masterplan_compute(session, data=_payload(), user_id=user_id)
    second = create_masterplan_compute(session, data=_payload(), user_id=user_id)

    assert first["is_origin"] is True
    assert second["is_origin"] is False


def test_origin_is_scoped_per_user():
    session = _build_session()
    create_masterplan_compute(session, data=_payload(), user_id=str(uuid.uuid4()))

    other = create_masterplan_compute(session, data=_payload(), user_id=str(uuid.uuid4()))

    assert other["is_origin"] is True


def test_create_returns_a_serializable_projection_not_an_orm_object():
    """The envelope rendered the raw ORM object as `{}`; callers got no id back."""
    session = _build_session()

    result = create_masterplan_compute(session, data=_payload(), user_id=str(uuid.uuid4()))

    assert isinstance(result, dict)
    assert result != {}
    for field in ("id", "status", "start_date", "target_date", "duration_years", "is_origin"):
        assert field in result


def test_list_returns_projections_scoped_to_the_user():
    session = _build_session()
    mine = str(uuid.uuid4())
    create_masterplan_compute(session, data=_payload(), user_id=mine)
    create_masterplan_compute(session, data=_payload(), user_id=str(uuid.uuid4()))

    listed = list_masterplans_compute(session, user_id=mine)

    assert len(listed) == 1
    assert isinstance(listed[0], dict)
    assert listed[0] != {}
    assert listed[0]["id"] is not None
