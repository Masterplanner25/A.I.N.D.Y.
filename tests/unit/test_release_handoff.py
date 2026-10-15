"""Release handoff, phase 1 — `RELEASE_HANDOFF_SPEC.md`.

The proof the spec asks for before a real release: the finished 2.27.0 run (38025672838), replayed from its
recorded GitHub responses minute by minute, walks `running → at_gate → approved → published → done` from
its own job times, names the approver, computes the 10 min 34 s gate wait, and writes the task and the
note. Then the ways it stops: a failed job, a cancelled run, a rejected gate, no run, a stall. And the
properties: the same tick twice changes nothing, each stage notifies once, a handoff is the caller's.
"""
from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException

from apps.automation.release_handoff import ReleaseHandoff
from apps.automation.services import release_handoff_service as rh

pytestmark = pytest.mark.app_profile

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "release_handoff"
RUN = json.loads((FIXTURES / "run_2_27_0.json").read_text())["workflow_runs"][0]
JOBS = json.loads((FIXTURES / "jobs_2_27_0.json").read_text())["jobs"]
APPROVALS = json.loads((FIXTURES / "approvals_2_27_0.json").read_text())
REPO = "Masterplanner25/aindy-runtime"
USER = uuid.uuid4()


def at(clock: str) -> datetime:
    return datetime.fromisoformat(f"2026-10-10T{clock}+00:00")


def _ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


class FakeGitHub:
    """GitHub as it stood at one moment of the 2.27.0 run, rebuilt from the recorded responses."""

    def __init__(self, moment: datetime, *, jobs=None, run=None, approvals=None):
        self.moment, self.calls = moment, []
        self._jobs, self._run, self._approvals = jobs, run, approvals

    def _pypi(self):
        return next(j for j in JOBS if j["name"] == "Publish to PyPI")

    def _testpypi(self):
        return next(j for j in JOBS if j["name"] == "Publish to TestPyPI")

    def _waiting(self) -> bool:
        return _ts(self._testpypi()["completed_at"]) <= self.moment < _ts(self._pypi()["started_at"])

    def find_run(self, repo, tag):
        self.calls.append("find_run")
        if self._run is not None:
            return self._run
        return self.get_run(repo, RUN["id"]) if self.moment >= _ts(RUN["created_at"]) else None

    def get_run(self, repo, run_id):
        self.calls.append("get_run")
        if self._run is not None:
            return self._run
        run = dict(RUN)
        if self.moment < _ts(RUN["updated_at"]):
            run.update(status="in_progress", conclusion=None)
        return run

    def jobs(self, repo, run_id):
        self.calls.append("jobs")
        if self._jobs is not None:
            return self._jobs
        out = []
        for job in JOBS:
            job = dict(job)
            started, completed = _ts(job["started_at"]), _ts(job["completed_at"])
            if job["name"] == "Publish to PyPI" and self._waiting():
                job.update(status="waiting", conclusion=None, completed_at=None)
            elif self.moment < started:
                job.update(status="queued", conclusion=None, started_at=None, completed_at=None)
            elif self.moment < completed:
                job.update(status="in_progress", conclusion=None, completed_at=None)
            out.append(job)
        return out

    def pending_deployments(self, repo, run_id):
        self.calls.append("pending_deployments")
        if self._jobs is not None:  # a hand-built failure: no gate is open
            return []
        return [{"environment": {"id": 15804342446, "name": "production"}}] if self._waiting() else []

    def approvals(self, repo, run_id):
        self.calls.append("approvals")
        if self._approvals is not None:
            return self._approvals
        return APPROVALS if self.moment >= _ts(self._pypi()["started_at"]) else []


@pytest.fixture
def records(monkeypatch):
    """The owners' syscalls and the email channel, recorded instead of performed."""
    calls = {"syscalls": [], "mail": []}

    def dispatch(db, user_id, name, payload, capability):
        calls["syscalls"].append((name, payload, capability))
        if name == "sys.v1.task.create":
            return {"task_id": str(len(calls["syscalls"])), "task_name": payload["name"]}
        if name == "sys.v1.memory.write":
            return {"node": {"id": "node-1"}}
        return {}

    def send(**kwargs):
        calls["mail"].append(kwargs)
        return {"success": True, "route": "smtp", "error": None}

    monkeypatch.setattr(rh, "_dispatch", dispatch)
    monkeypatch.setattr(rh, "_recipient", lambda db, handoff: "owner@example.com")
    monkeypatch.setenv("AINDY_GITHUB_TOKEN", "github_pat_test")
    monkeypatch.delenv("AINDY_RELEASE_REPOS", raising=False)
    calls["send"] = send
    return calls


def _handoff(db_session, tag="v2.27.0", *, created="04:54:00"):
    data = rh.start_handoff(db_session, USER, REPO, tag)
    row = db_session.query(ReleaseHandoff).filter(ReleaseHandoff.id == data["id"]).one()
    row.created_at = row.stage_at = at(created)
    db_session.commit()
    return row


def _tick(db_session, row, clock, records, **github):
    return rh.process(db_session, row, FakeGitHub(at(clock), **github), now=at(clock), send=records["send"])


def _syscalls(records, name):
    return [payload for n, payload, _ in records["syscalls"] if n == name]


# ── The proof: 2.27.0, replayed ─────────────────────────────────────────────────────────────


def test_the_finished_run_reads_as_every_stage_with_its_approver_and_gate_wait():
    seen = rh.observe(RUN, JOBS, [], APPROVALS)
    assert [stage for stage, _, _ in seen["events"]] == ["running", "at_gate", "approved", "published", "done"]
    assert seen["approved_by"] == "Masterplanner25"
    assert seen["gate_wait_seconds"] == 10 * 60 + 34
    assert seen["failure"] is None


def test_the_2_27_0_run_replayed_minute_by_minute(db_session, records):
    row = _handoff(db_session)
    assert row.stage == "requested" and row.task_name == "Release aindy-runtime 2.27.0"
    assert [n for n, _, _ in records["syscalls"]] == ["sys.v1.task.create", "sys.v1.task.start"]

    assert _tick(db_session, row, "04:54:10", records) == []           # tag pushed, run not created yet
    assert _tick(db_session, row, "04:55:00", records) == ["running"]
    assert row.run_id == "38025672838" and row.run_url.endswith("/38025672838")
    assert _tick(db_session, row, "04:56:10", records) == []           # TestPyPI still publishing

    assert _tick(db_session, row, "04:57:00", records) == ["at_gate"]
    [gate_mail] = records["mail"]
    assert gate_mail["subject"] == "aindy-runtime 2.27.0 is waiting for your approval"
    assert "https://github.com/Masterplanner25/aindy-runtime/actions/runs/38025672838" in gate_mail["body"]
    assert "2 min 5 s after the run started" in gate_mail["body"]

    for clock in ("04:58:00", "05:03:00", "05:06:59"):                 # waiting for the owner: nothing moves
        assert _tick(db_session, row, clock, records) == []
    assert len(records["mail"]) == 1

    assert _tick(db_session, row, "05:07:10", records) == ["approved"]
    assert row.approved_by == "Masterplanner25"
    assert rh.serialize(row)["gate_wait_seconds"] == 634
    assert _tick(db_session, row, "05:07:30", records) == ["published"]
    assert _tick(db_session, row, "05:08:35", records) == []           # wheel verified, release not yet
    assert _tick(db_session, row, "05:09:00", records) == ["done"]

    assert [h["stage"] for h in row.history] == ["requested", "running", "at_gate", "approved", "published", "done"]
    assert row.history[2]["at"] == "2026-10-10T04:56:26+00:00"        # the gate from TestPyPI's own end time
    assert _syscalls(records, "sys.v1.task.complete_full") == [{"task_name": "Release aindy-runtime 2.27.0"}]
    [note] = _syscalls(records, "sys.v1.memory.write")
    assert note["node_type"] == "outcome" and "release:2.27.0" in note["tags"]
    assert "Approved by Masterplanner25 after waiting 10 min 34 s at the gate." in note["content"]
    assert "docs/upgrades/APP_HANDOFF_v2.27.0.md" in note["content"]
    assert "Handoff to done: 14 min 39 s." in note["content"]
    assert _syscalls(records, "sys.v1.task.create")[-1]["name"] == "Adopt aindy-runtime 2.27.0 in A.I.N.D.Y."
    assert row.memory_node_id == "node-1" and row.adoption_task_id
    assert [m["subject"] for m in records["mail"]] == ["aindy-runtime 2.27.0 is waiting for your approval",
                                                       "aindy-runtime 2.27.0 is published"]
    assert set(row.notified) == {"at_gate", "done"}


def test_a_run_handed_off_after_the_gate_is_followed_without_asking_for_approval(db_session, records):
    row = _handoff(db_session, created="05:07:15")
    assert _tick(db_session, row, "05:07:20", records) == ["running", "at_gate", "approved"]
    assert records["mail"] == []                                       # nothing left to ask of the owner
    assert _tick(db_session, row, "05:10:00", records) == ["published", "done"]
    assert [m["subject"] for m in records["mail"]] == ["aindy-runtime 2.27.0 is published"]


def test_a_run_finished_before_its_handoff_has_no_handoff_to_done_time(db_session, records):
    # Found live 2026-10-15: handing off the finished 2.27.0 run wrote "Handoff to done: -120 h 42 min".
    row = _handoff(db_session, created="06:00:00")
    assert _tick(db_session, row, "06:00:30", records)[-1] == "done"
    [note] = _syscalls(records, "sys.v1.memory.write")
    assert "Handoff to done" not in note["content"]


# ── Restart safety and notifications ───────────────────────────────────────────────────────


def test_the_same_tick_twice_changes_nothing(db_session, records):
    row = _handoff(db_session)
    _tick(db_session, row, "04:57:00", records)
    before = (row.stage, copy.deepcopy(row.history), copy.deepcopy(row.notified), len(records["syscalls"]))
    assert _tick(db_session, row, "04:57:00", records) == []
    assert (row.stage, row.history, row.notified, len(records["syscalls"])) == before
    assert len(records["mail"]) == 1


def test_a_terminal_handoff_is_never_read_again(db_session, records):
    row = _handoff(db_session)
    _tick(db_session, row, "05:09:00", records)
    github = FakeGitHub(at("05:10:00"))
    assert rh.process(db_session, row, github, now=at("05:10:00"), send=records["send"]) == []
    assert github.calls == []


def test_a_failed_send_is_recorded_and_not_retried(db_session, records):
    row = _handoff(db_session)
    failing = lambda **kwargs: {"success": False, "route": "smtp", "error": "auth failed"}  # noqa: E731
    rh.process(db_session, row, FakeGitHub(at("04:57:00")), now=at("04:57:00"), send=failing)
    assert row.notified["at_gate"]["success"] is False and row.notified["at_gate"]["error"] == "auth failed"
    assert rh.notify(db_session, row, "at_gate", send=records["send"]) is None
    assert records["mail"] == []


# ── The ways a release stops ───────────────────────────────────────────────────────────────


def _failed_smoke_jobs():
    jobs = [dict(j) for j in JOBS[:5]]
    jobs[4].update(conclusion="failure", html_url="https://github.com/x/job/5")
    return jobs


def test_a_failed_job_stops_the_handoff_names_the_job_and_leaves_the_task_open(db_session, records):
    row = _handoff(db_session)
    run = {**RUN, "status": "completed", "conclusion": "failure"}
    assert _tick(db_session, row, "04:57:00", records, jobs=_failed_smoke_jobs(), run=run) == ["running", "failed"]
    assert row.failure == {"reason": "job_failed", "job": "Install Smoke Test", "conclusion": "failure",
                           "url": "https://github.com/x/job/5"}
    [mail] = records["mail"]
    assert mail["subject"] == "aindy-runtime 2.27.0 release stopped: Install Smoke Test ended failure"
    assert _syscalls(records, "sys.v1.task.complete_full") == []
    assert _syscalls(records, "sys.v1.memory.write") == []


def test_a_cancelled_run_stops_the_handoff(db_session, records):
    row = _handoff(db_session)
    run = {**RUN, "status": "completed", "conclusion": "cancelled"}
    jobs = [{**j, "conclusion": "cancelled"} if j["name"] == "Publish to PyPI" else j for j in JOBS[:7]]
    _tick(db_session, row, "05:00:00", records, jobs=jobs, run=run)
    assert row.stage == "failed" and row.failure["reason"] == "cancelled"


def test_a_rejected_gate_stops_the_handoff(db_session, records):
    row = _handoff(db_session)
    rejected = [{**APPROVALS[0], "state": "rejected"}]
    run = {**RUN, "status": "completed", "conclusion": "failure"}
    jobs = [{**j, "conclusion": "failure", "started_at": None} if j["name"] == "Publish to PyPI" else j
            for j in JOBS[:7]]
    assert _tick(db_session, row, "05:00:00", records, jobs=jobs, run=run, approvals=rejected) == [
        "running", "at_gate", "failed"]
    assert row.failure["reason"] == "rejected" and row.failure["by"] == "Masterplanner25"
    assert "rejected by Masterplanner25" in records["mail"][-1]["subject"]


def test_no_run_within_the_limit_fails_as_no_run(db_session, records):
    row = _handoff(db_session, created="04:00:00")
    github = FakeGitHub(at("04:20:00"))
    github.find_run = lambda repo, tag: None
    assert rh.process(db_session, row, github, now=at("04:20:00"), send=records["send"]) == []
    assert rh.process(db_session, row, github, now=at("04:31:00"), send=records["send"]) == ["failed"]
    assert row.failure["reason"] == "no_run"
    assert "no publish run was found" in records["mail"][-1]["subject"]


def test_no_stage_change_for_the_limit_fails_as_stalled(db_session, records, monkeypatch):
    monkeypatch.setenv("AINDY_RELEASE_STALL_MINUTES", "60")
    row = _handoff(db_session)
    _tick(db_session, row, "04:57:00", records)                       # at the gate since 04:56:26
    assert _tick(db_session, row, "05:06:00", records) == []
    github = FakeGitHub(at("05:00:00"))                                 # GitHub still says: waiting
    assert rh.process(db_session, row, github, now=at("05:57:00"), send=records["send"]) == ["failed"]
    assert row.failure["reason"] == "stalled" and row.failure["stage"] == "at_gate"


# ── The handoff itself ─────────────────────────────────────────────────────────────────────


def test_a_handoff_is_refused_for_another_repo_a_bad_tag_a_duplicate_or_no_token(db_session, records, monkeypatch):
    for repo, tag in (("someone/else", "v1.0.0"), (REPO, "2.27.0"), (REPO, "latest")):
        with pytest.raises(HTTPException) as refused:
            rh.start_handoff(db_session, USER, repo, tag)
        assert refused.value.status_code == 422
    _handoff(db_session)
    with pytest.raises(HTTPException) as duplicate:
        rh.start_handoff(db_session, USER, REPO, "v2.27.0")
    assert duplicate.value.status_code == 409
    monkeypatch.delenv("AINDY_GITHUB_TOKEN")
    with pytest.raises(HTTPException) as no_token:
        rh.start_handoff(db_session, USER, REPO, "v2.28.0")
    assert no_token.value.status_code == 503


def test_handoffs_are_the_callers_own(db_session, records):
    _handoff(db_session)
    assert [h["tag"] for h in rh.list_handoffs(db_session, USER)["handoffs"]] == ["v2.27.0"]
    assert rh.list_handoffs(db_session, uuid.uuid4())["handoffs"] == []


def test_a_tag_handed_off_again_after_a_failure_reuses_its_open_task(db_session, records):
    first = _handoff(db_session)
    _tick(db_session, first, "04:57:00", records, jobs=_failed_smoke_jobs(),
          run={**RUN, "status": "completed", "conclusion": "failure"})
    second = rh.start_handoff(db_session, USER, REPO, "v2.27.0")
    assert len(_syscalls(records, "sys.v1.task.create")) == 1
    assert second["task_id"] == first.task_id and second["task_name"] == first.task_name
    assert [h["stage"] for h in rh.list_handoffs(db_session, USER, active_only=True)["handoffs"]] == ["requested"]


def test_a_released_tag_cannot_be_handed_off_again(db_session, records):
    # Found live 2026-10-15: a second handoff of the released 2.27.0 wrote a second adoption task.
    row = _handoff(db_session)
    _tick(db_session, row, "05:09:00", records)
    with pytest.raises(HTTPException) as again:
        rh.start_handoff(db_session, USER, REPO, "v2.27.0")
    assert again.value.status_code == 409 and "already released" in again.value.detail["message"]


def test_route_names_fit_the_event_source_column():
    assert len("automation.release.handoff") <= 32 and len("automation.release.list") <= 32


def test_the_watcher_is_idle_without_open_handoffs(monkeypatch):
    class Session:
        def query(self, *_):
            return self

        def filter(self, *_):
            return self

        def order_by(self, *_):
            return self

        def all(self):
            return []

        def close(self):
            pass

    monkeypatch.setattr("AINDY.db.database.SessionLocal", Session)
    assert rh.release_handoff_watch() == {"handoffs": 0, "moved": 0, "skipped": False}


def test_gate_wait_is_read_from_history_not_wall_clock():
    row = ReleaseHandoff(history=[{"stage": "at_gate", "at": "2026-10-10T04:56:26+00:00"},
                                 {"stage": "approved", "at": "2026-10-10T05:07:00+00:00"}])
    assert rh.gate_wait_seconds(row) == 634
    assert rh._duration(634) == "10 min 34 s" and rh._duration(timedelta(hours=2).total_seconds()) == "2 h 0 min"
