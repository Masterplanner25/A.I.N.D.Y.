"""The planner-context provider under the extension boundary — AGENT-PLANNER-CONTEXT-BOUNDARY-1.

The runtime calls `build_planner_context` through `registry.get_planner_context`, which sanitizes
the context: `db` is dropped at the root by design and the `uuid.UUID` the runtime passes as
`user_id` (`agent_runtime/shared.py:81`, FR-39) arrives as `{"_redacted_type": "UUID"}`. Until
2026-09-17 the provider read both from the context as if they were usable, every block took its
`except: return ""` path, and no planner prompt since the boundary landed carried the user's
Infinity context. These tests hand the provider exactly the boundary's shape and exactly the
shape FR-39 will produce, and pin what each must do.
"""
from __future__ import annotations

import logging

import pytest

pytestmark = pytest.mark.app_profile

runtime_extensions = pytest.importorskip("apps.agent.agents.runtime_extensions")

USER = "283ae082-19f1-47f8-af2e-1c2c5efada40"

_SNAPSHOT = {
    "master_score": 61.0,
    "confidence": "medium",
    "execution_speed": 55.0,
    "decision_efficiency": 70.0,
    "ai_productivity_boost": 30.0,
    "focus_quality": 64.0,
    "masterplan_progress": 42.0,
}


class _Session:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _patch_jobs(monkeypatch, seen: dict):
    import AINDY.platform_layer.registry as registry

    def _job(name):
        if name == "analytics.kpi_snapshot":

            def _snapshot(*, user_id, db):
                seen["kpi"] = (user_id, db)
                return dict(_SNAPSHOT)

            return _snapshot
        if name == "analytics.reasoning_recommendation":

            def _recommend(*, user_id, db):
                seen["reasoning"] = (user_id, db)
                return None

            return _recommend
        return None

    monkeypatch.setattr(registry, "get_job", _job)


def _patch_session(monkeypatch, opened: list):
    import AINDY.db.database as database

    def _open():
        session = _Session()
        opened.append(session)
        return session

    monkeypatch.setattr(database, "SessionLocal", _open)


def test_the_boundary_shape_yields_the_base_prompt_without_touching_jobs_or_db(monkeypatch, caplog):
    """No db, redacted user_id — what production hands us today. The provider must not open a
    session it cannot scope to a tenant, must not call the jobs, and must SAY so rather than
    swallow it (the completion hook's WARNING was the only reason its twin was ever found)."""
    seen: dict = {}
    opened: list = []
    _patch_jobs(monkeypatch, seen)
    _patch_session(monkeypatch, opened)

    with caplog.at_level(logging.WARNING):
        out = runtime_extensions.build_planner_context(
            {"run_type": "default", "user_id": {"_redacted_type": "UUID"}}
        )

    assert out == {"system_prompt": runtime_extensions.PLANNER_SYSTEM_PROMPT, "context_block": ""}
    assert seen == {}
    assert opened == []
    assert any("FR-39" in rec.getMessage() for rec in caplog.records)


def test_a_string_tenant_builds_the_blocks_against_a_session_the_provider_opens_and_closes(monkeypatch):
    """What FR-39 will hand us: a string. The boundary still strips `db`, so the provider opens
    its own session, passes THAT to both jobs, and closes it — and the KPI block reaches the prompt."""
    seen: dict = {}
    opened: list = []
    _patch_jobs(monkeypatch, seen)
    _patch_session(monkeypatch, opened)

    out = runtime_extensions.build_planner_context({"run_type": "default", "user_id": USER})

    assert len(opened) == 1 and opened[0].closed is True
    assert seen["kpi"] == (USER, opened[0])
    assert seen["reasoning"] == (USER, opened[0])
    assert "## User Performance Context (Infinity Score)" in out["context_block"]
    assert "Overall score: 61.0/100" in out["context_block"]
    assert out["system_prompt"].startswith(runtime_extensions.PLANNER_SYSTEM_PROMPT)
    assert out["context_block"] in out["system_prompt"]


def test_an_in_process_session_is_used_as_given_and_not_closed(monkeypatch):
    """A caller inside the process may pass a real session (tests, direct callers). It is used
    and left open — closing another owner's session is not this function's call."""
    seen: dict = {}
    opened: list = []
    _patch_jobs(monkeypatch, seen)
    _patch_session(monkeypatch, opened)
    theirs = _Session()

    runtime_extensions.build_planner_context({"run_type": "default", "user_id": USER, "db": theirs})

    assert opened == []
    assert seen["kpi"] == (USER, theirs)
    assert theirs.closed is False


def test_the_session_is_closed_even_when_a_block_raises(monkeypatch):
    import AINDY.platform_layer.registry as registry

    opened: list = []
    _patch_session(monkeypatch, opened)

    def _job(name):
        def _boom(**kw):
            raise RuntimeError("kpi store down")

        return _boom

    monkeypatch.setattr(registry, "get_job", _job)

    out = runtime_extensions.build_planner_context({"run_type": "default", "user_id": USER})

    # each block is best-effort on its own; the prompt is still the base prompt
    assert out["context_block"] == ""
    assert len(opened) == 1 and opened[0].closed is True


def test_the_planner_is_told_that_pending_tasks_lower_the_score(monkeypatch):
    """Owner, 2026-09-25: the first real goal ended in three `task.create` steps and its own
    recalc took -8.64 (decision efficiency 68 -> 50, masterplan progress 88 -> 70) — both KPIs
    are completion ratios. The planner had never been told; it must be, on every plan that
    carries the KPI block."""
    seen: dict = {}
    _patch_jobs(monkeypatch, seen)
    block = runtime_extensions._build_kpi_context_block(USER, _Session())
    assert "Pending tasks lower the score" in block
    assert "every task created lowers both" in block
