"""SYSCALL-SILENT-ERRORS-1 — the loop-adjustment evaluation must dispatch as the user, not as nobody.

The three silently-failing syscalls all had one mechanism: dispatched with an EMPTY `user_id`
outside a request, the dispatcher refuses them before the handler runs —
`TENANT_VIOLATION: syscall requires authenticated tenant context` — on a path that logged nothing
before runtime 2.12.0. Inside a request the pipeline's tenant context papered over it, which is
why every route-level probe succeeded. The Infinity recalc runs as an async job, so
`update_loop_adjustment` was refused every time and swallowed: 115 `loop_adjustments` rows,
`actual_outcome` NULL on every one since 2026-07-23.

These tests go through the REAL dispatcher with no request context — the job shape.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.app_profile


def _make_adjustment(db_session, user_id):
    from apps.automation.public import create_loop_adjustment

    return create_loop_adjustment(
        db_session,
        user_id=user_id,
        trigger_event="task_completed",
        decision_type="review_plan",
        expected_outcome="improved",
        expected_score=50,
        score_snapshot={"master_score": 50},
        adjustment_payload={},
    )


def test_update_dispatched_as_the_user_reaches_the_row(db_session):
    from apps.analytics.services.integration import dependency_adapter as da
    from apps.automation.models import LoopAdjustment

    user_id = uuid.uuid4()
    created = _make_adjustment(db_session, user_id)

    # SQLite does not cast str -> UUID (Postgres does); pass the object, as CLAUDE.md says.
    updated = da.update_loop_adjustment(
        adjustment_id=uuid.UUID(str(created["id"])),
        db=db_session,
        user_id=str(user_id),
        actual_outcome="improved",
        actual_score=57,
        evaluated_at=datetime.now(timezone.utc),
    )
    assert updated is not None and updated["actual_outcome"] == "improved"

    row = db_session.query(LoopAdjustment).filter(LoopAdjustment.id == uuid.UUID(str(created["id"]))).one()
    assert row.actual_outcome == "improved"
    assert row.actual_score == 57
    assert row.evaluated_at is not None
    assert str(row.user_id) == str(user_id), "user_id is the tenant, never a patch field"


def test_update_without_a_tenant_is_refused_and_swallowed(db_session, caplog):
    """The shape the bug had: no user_id, no request → refused before the handler, empty dict back.

    Kept as a pin on the mechanism, not as desired behaviour — if the dispatcher ever starts
    accepting tenant-less dispatches this test tells us the reason for the fix moved.
    """
    from apps.analytics.services.integration import dependency_adapter as da
    from apps.automation.models import LoopAdjustment

    user_id = uuid.uuid4()
    created = _make_adjustment(db_session, user_id)

    with caplog.at_level("WARNING"):
        out = da.update_loop_adjustment(
            adjustment_id=uuid.UUID(str(created["id"])), db=db_session, actual_outcome="improved"
        )

    assert out is None or dict(out) == {}
    row = db_session.query(LoopAdjustment).filter(LoopAdjustment.id == uuid.UUID(str(created["id"]))).one()
    assert row.actual_outcome is None
    assert "TENANT_VIOLATION" in caplog.text  # the swallow says why, since 2026-09-11


def test_evaluate_pending_adjustment_passes_the_tenant(monkeypatch):
    """Pin the caller: `evaluate_pending_adjustment` must hand its user_id to the update."""
    from apps.analytics.services.orchestration import infinity_loop

    user_id = str(uuid.uuid4())
    seen: dict = {}

    class _Rec(dict):
        pass

    pending = _Rec(id="adj-1", decision_type="review_plan", expected_outcome="improved",
                   expected_score=50, adjustment_payload={}, score_snapshot={"master_score": 50})

    monkeypatch.setattr(infinity_loop, "supports_managed_transactions", lambda db: False, raising=False)
    monkeypatch.setattr(infinity_loop, "get_pending_adjustment_record", lambda **kw: pending)
    monkeypatch.setattr(infinity_loop, "update_loop_adjustment_record", lambda **kw: seen.update(kw) or pending)

    infinity_loop.evaluate_pending_adjustment(
        user_id=user_id, trigger_event="task_completed", actual_score=57.0, db=object()
    )
    assert seen.get("user_id") == user_id
