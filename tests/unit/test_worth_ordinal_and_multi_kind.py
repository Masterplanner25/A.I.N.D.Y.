"""Worth declarations: ordinal for judgement kinds, cardinal for money, several per target.

Two changes land together because they are the same claim — that the schema should describe
how worth actually works rather than what was convenient to store.

**Ordinal for `intrinsic` / `strategic`.** These were free floats, which is false precision:
nothing distinguished 8 from 7, nothing bounded the value, and an unbounded rating can
saturate the axis the same way the un-scaled monetary figure used to (SOAK_AUDIT §2b).
`monetary_potential` stays a float because dollars are genuinely cardinal — $100k really is
twice $50k.

**Several kinds per target.** The upsert key was `(user, target_type, target_id)` with `kind`
absent, and the write did `row.kind = kind`. So declaring a project's strategic worth and
then its monetary potential OVERWROTE the first — the row's kind simply flipped. A single
item could only ever hold one flavour of worth, which is not how worth works: the owner's
correction was that it cannot be either/or, because that would not capture worth accurately.

That is the bug the second half of this file pins. It also made the per-kind scoring fix
(#287) largely theoretical: the maths could combine kinds the write path could barely
produce.
"""

from __future__ import annotations

import os
import uuid

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

value_declaration = pytest.importorskip("apps.analytics.value_declaration")
service = pytest.importorskip("apps.analytics.services.scoring.value_declaration_service")

WORTH_ORDINAL_LEVELS = value_declaration.WORTH_ORDINAL_LEVELS
record_value_declaration = service.record_value_declaration
declared_worth_summary = service.declared_worth_summary


@pytest.fixture
def db():
    import_runtime_model_registry()
    bootstrap_app_models(required=True)
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(
        autocommit=False, autoflush=False, expire_on_commit=False, bind=engine
    )()
    try:
        yield session
    finally:
        session.close()


USER = uuid.uuid4()


# ── the mapping is a contract ──────────────────────────────────────────────────────────

def test_ordinal_levels_are_pinned():
    """Retuning these changes every existing row's contribution to the score.

    `ordinal_level` persists what the user chose so history is not silently reinterpreted,
    but the numbers still move. This test makes a change deliberate and visible in review.
    """
    assert WORTH_ORDINAL_LEVELS == {"low": 1.0, "moderate": 3.0, "high": 8.0, "critical": 20.0}


def test_the_scale_is_roughly_geometric():
    """Worth judgements are order-of-magnitude ones — 'high' is not one step above 'low'."""
    values = [WORTH_ORDINAL_LEVELS[k] for k in ("low", "moderate", "high", "critical")]
    ratios = [b / a for a, b in zip(values, values[1:])]
    assert all(r >= 2.0 for r in ratios), f"steps are too linear to express class changes: {ratios}"


# ── ordinal kinds ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["intrinsic", "strategic"])
def test_ordinal_kinds_accept_a_level_and_store_both(db, kind):
    out = record_value_declaration(
        db, user_id=USER, target_type="project", target_id="nodus",
        declared_value="high", kind=kind,
    )
    assert out["ordinal_level"] == "high"
    # The mapped float still drives scoring, so three_axis_service is unchanged.
    assert out["declared_value"] == WORTH_ORDINAL_LEVELS["high"]


@pytest.mark.parametrize("bad", [8, 8.0, "8", "enormous", "", None])
def test_ordinal_kinds_reject_anything_that_is_not_a_level(db, bad):
    """A number is rejected, NOT coerced.

    Accepting 8 for "high" would let the false precision back in through the side door, and
    silently — the caller would believe it had expressed something finer than the scale holds.
    """
    with pytest.raises(ValueError, match="ordinal kind"):
        record_value_declaration(
            db, user_id=USER, target_type="project", target_id="x",
            declared_value=bad, kind="strategic",
        )


def test_level_names_are_case_insensitive(db):
    out = record_value_declaration(
        db, user_id=USER, target_type="project", target_id="y",
        declared_value="  HIGH  ", kind="strategic",
    )
    assert out["ordinal_level"] == "high"


# ── the cardinal kind ──────────────────────────────────────────────────────────────────

def test_monetary_keeps_its_float(db):
    """Dollars are genuinely cardinal — this kind must NOT be coarsened."""
    out = record_value_declaration(
        db, user_id=USER, target_type="project", target_id="contract",
        declared_value=50000.0, kind="monetary_potential",
    )
    assert out["declared_value"] == 50000.0
    assert out["ordinal_level"] is None


def test_monetary_rejects_a_level_name(db):
    with pytest.raises(ValueError, match="cardinal kind"):
        record_value_declaration(
            db, user_id=USER, target_type="project", target_id="c2",
            declared_value="high", kind="monetary_potential",
        )


def test_monetary_rejects_a_negative_figure(db):
    with pytest.raises(ValueError, match="negative"):
        record_value_declaration(
            db, user_id=USER, target_type="project", target_id="c3",
            declared_value=-1.0, kind="monetary_potential",
        )


# ── several kinds per target — the owner's correction ──────────────────────────────────

def test_one_target_can_hold_several_kinds_of_worth(db):
    """The core fix. Before this, the second declaration overwrote the first."""
    record_value_declaration(
        db, user_id=USER, target_type="project", target_id="nodus",
        declared_value="critical", kind="strategic",
    )
    record_value_declaration(
        db, user_id=USER, target_type="project", target_id="nodus",
        declared_value=50000.0, kind="monetary_potential",
    )

    summary = declared_worth_summary(db, USER)
    assert summary["count"] == 2, "the monetary declaration replaced the strategic one"
    assert summary["by_kind"]["strategic"] == WORTH_ORDINAL_LEVELS["critical"]
    assert summary["by_kind"]["monetary_potential"] == 50000.0


def test_redeclaring_the_same_kind_still_updates_in_place(db):
    """Multi-kind must not turn every re-declaration into a duplicate row."""
    first = record_value_declaration(
        db, user_id=USER, target_type="project", target_id="nodus",
        declared_value="low", kind="strategic",
    )
    second = record_value_declaration(
        db, user_id=USER, target_type="project", target_id="nodus",
        declared_value="critical", kind="strategic",
    )

    assert first["created"] is True
    assert second["created"] is False
    assert second["id"] == first["id"]

    summary = declared_worth_summary(db, USER)
    assert summary["count"] == 1
    assert summary["by_kind"]["strategic"] == WORTH_ORDINAL_LEVELS["critical"]


def test_switching_a_target_to_a_cardinal_kind_clears_the_stale_level(db):
    """A monetary row must not keep a level that no longer describes its value."""
    record_value_declaration(
        db, user_id=USER, target_type="project", target_id="z",
        declared_value="high", kind="strategic",
    )
    out = record_value_declaration(
        db, user_id=USER, target_type="project", target_id="z",
        declared_value=1000.0, kind="monetary_potential",
    )
    assert out["ordinal_level"] is None


def test_multi_kind_feeds_the_per_kind_scoring(db):
    """The point of #287's per-kind maths: it can now actually receive several kinds."""
    from apps.analytics.services.scoring.three_axis_service import _worth_kind_score

    record_value_declaration(
        db, user_id=USER, target_type="project", target_id="nodus",
        declared_value="critical", kind="strategic",
    )
    record_value_declaration(
        db, user_id=USER, target_type="project", target_id="nodus",
        declared_value=50000.0, kind="monetary_potential",
    )

    by_kind = declared_worth_summary(db, USER)["by_kind"]
    subs = {k: _worth_kind_score(k, v) for k, v in by_kind.items()}

    # Both dimensions contribute, and neither is at the ceiling — the drowning §2b described
    # required the kinds to be summed, which they no longer are.
    assert 0 < subs["strategic"] < 100
    assert 0 < subs["monetary_potential"] < 100
