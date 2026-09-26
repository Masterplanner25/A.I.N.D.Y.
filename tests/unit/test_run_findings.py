"""A finished agent run's real findings are saved to memory, once.

Owner, 2026-09-26: three runs in a row planned a `memory.write` "summary" of research that had not
run yet (FR-46: a step cannot read an earlier step's result), and recall ranked those placeholders
first. The planner is now told not to, and the completion hook saves the run's actual findings.

The digest must match Collaborator's (`client/src/utils/runFindings.js`): both are held to the same
fixture, `tests/fixtures/run_findings/`, and `client/src/test/run-findings.test.js` reads it too.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.agent.agents import runtime_extensions
from apps.agent.services.run_findings import (
    FINDINGS_MARKER,
    MAX_FINDINGS_CHARS,
    build_findings_digest,
    goal_ask,
)

pytestmark = pytest.mark.app_profile

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "run_findings"


def _expected() -> str:
    return (FIXTURES / "expected_digest.txt").read_text(encoding="utf-8").replace("\r\n", "\n")


def test_the_digest_matches_the_shared_fixture():
    steps = json.loads((FIXTURES / "steps.json").read_text(encoding="utf-8"))
    assert build_findings_digest(steps) == _expected()


def test_the_digest_is_capped():
    huge = [{"tool_name": "research.query", "status": "success", "result": {"raw_result": "x" * (MAX_FINDINGS_CHARS * 2)}}]
    digest = build_findings_digest(huge)
    assert digest.endswith("\n[truncated]")
    assert len(digest) == MAX_FINDINGS_CHARS + len("\n[truncated]")


def test_goal_ask_strips_attached_findings():
    assert goal_ask("Draft the outline" + FINDINGS_MARKER + "[research.query]\nx") == "Draft the outline"
    assert goal_ask("Draft the outline") == "Draft the outline"


def test_the_planner_is_told_not_to_fake_findings():
    prompt = runtime_extensions.PLANNER_SYSTEM_PROMPT
    assert "a step cannot read an earlier" in prompt
    assert 'never plan memory.write to save a "summary"' in prompt


# ── the completion hook ────────────────────────────────────────────────────────


class _Run:
    def __init__(self, result=None):
        self.id = "run-1"
        self.user_id = "283ae082-19f1-47f8-af2e-1c2c5efada40"
        self.goal = "Research Human-AI collaboration techniques"
        self.result = result


class _Query:
    def __init__(self, run):
        self._run = run

    def filter(self, *a, **k):
        return self

    def first(self):
        return self._run


class _Session:
    def __init__(self, run):
        self.run = run
        self.committed = False

    def query(self, *_a):
        return _Query(self.run)

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        pass


def _hook(monkeypatch, run, save):
    import AINDY.db.database as database
    import AINDY.platform_layer.registry as registry

    session = _Session(run)
    monkeypatch.setattr(database, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        registry,
        "get_job",
        lambda name: (lambda **kw: {"next_action": {"type": "review_plan", "title": "Review"}})
        if name == "analytics.infinity_execute"
        else None,
    )
    monkeypatch.setattr(runtime_extensions, "_save_run_findings", save)
    runtime_extensions.handle_agent_run_completed({"run_id": "run-1"})
    return session


def test_the_hook_saves_the_findings_and_records_the_node(monkeypatch):
    calls = []
    run = _Run()
    _hook(monkeypatch, run, lambda db, r, user_id: calls.append(user_id) or "node-1")
    assert calls == ["283ae082-19f1-47f8-af2e-1c2c5efada40"]
    assert run.result["findings_node_id"] == "node-1"
    assert run.result["loop_enforced"] is True


def test_a_failed_save_never_blocks_the_infinity_loop(monkeypatch):
    def _boom(db, r, user_id):
        raise RuntimeError("memory store down")

    run = _Run()
    session = _hook(monkeypatch, run, _boom)
    assert run.result["loop_enforced"] is True
    assert "findings_node_id" not in run.result
    assert session.committed is True


def test_findings_are_saved_once(monkeypatch):
    calls = []
    run = _Run(result={"findings_node_id": "node-0"})
    _hook(monkeypatch, run, lambda db, r, user_id: calls.append(1) or "node-2")
    assert calls == []
    assert run.result["findings_node_id"] == "node-0"
