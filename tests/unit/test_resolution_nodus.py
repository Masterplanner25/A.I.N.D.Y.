"""The Resolution Check as one Nodus workflow that sleeps between batches (FR-55, runtime 2.39.0).

`resolution_tick` hands a new check to `resolution_check_v1.nd` behind AINDY_RESOLUTION_NODUS,
leaves a check alone while its flow run is alive, and takes a dead one back to Python. Covers the
flag, the launch, the hand-back, the batch syscall (the caller's own check, by name the capability
it requires), the wake's lateness, the script's kind and compile, and registration.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import AINDY.runtime.nodus_workflow_registry as nwr
from apps._shared import nodus as shared_nodus
from apps.masterplan import bootstrap
from apps.masterplan.services import resolution_nodus as rn
from apps.masterplan.services import resolution_service as rs
from apps.masterplan.services import work_service as ws
from apps.masterplan.work_model import ResolutionAnswer, ResolutionRun

pytestmark = pytest.mark.app_profile

USER = uuid.uuid4()
ENGINES = ["perplexity", "openai", "claude"]
_ND_PATH = Path(bootstrap.__file__).resolve().parent / "nodus" / "resolution_check_v1.nd"


@pytest.fixture
def run(db_session):
    """A pending check of 3 questions x 3 engines, answered by fakes that cost nothing."""
    ws.create_work(db_session, USER, {"name": "Masterplan Infinite Weave", "kind": "brand", "role": "creator",
                                      "summary": "AI-powered execution."})
    questions = rs.build_questions(rs.ground_truth(db_session, USER), "core")[:1] * 3
    questions = [{**q, "key": f"{q['key']}#{i}"} for i, q in enumerate(questions)]
    row = ResolutionRun(user_id=USER, scope="core", status="pending", questions=questions, engines=ENGINES, calls={})
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture
def fake_engines(monkeypatch):
    def make(name):
        return lambda question, **k: {"answer": f"{name}: {question}", "citations": []}

    monkeypatch.setattr("apps.masterplan.services.resolution_engines.ENGINES", {n: make(n) for n in ENGINES})
    monkeypatch.setattr(rs, "judge_answer", lambda q, a, t, **k: {"about": "subject", "claims": [], "_facts": [],
                                                                  "_links": []})


@pytest.fixture
def tick_session(monkeypatch, db_session):
    """The tick opens its own session and closes it; hand it the test's, kept open."""
    class _Session:
        def __getattr__(self, name):
            return getattr(db_session, name)

        def close(self):
            pass

        def rollback(self):
            # The test session is one outer transaction, so a real rollback would also take the
            # fixture's committed check. In the job, it only discards the failed VM call's work.
            db_session.expire_all()

    monkeypatch.setattr("AINDY.db.database.SessionLocal", lambda: _Session())


@pytest.fixture
def fallbacks(monkeypatch):
    recorded = []
    monkeypatch.setattr(shared_nodus, "record_nodus_fallback", lambda db, **k: recorded.append(k))
    return recorded


def _answers(db, run) -> int:
    return db.query(ResolutionAnswer).filter(ResolutionAnswer.run_id == run.id).count()


# ── the tick: launch, leave alone, take back ──────────────────────────────────────────────


def test_flag_default_off(monkeypatch):
    monkeypatch.delenv("AINDY_RESOLUTION_NODUS", raising=False)
    assert rn.nodus_resolution_enabled() is False
    monkeypatch.setenv("AINDY_RESOLUTION_NODUS", "1")
    assert rn.nodus_resolution_enabled() is True


def test_off_the_tick_answers_in_python(monkeypatch, db_session, run, fake_engines, tick_session):
    monkeypatch.delenv("AINDY_RESOLUTION_NODUS", raising=False)
    monkeypatch.setattr(nwr, "run_nodus_workflow", lambda *a, **k: pytest.fail("flag is off"))
    summary = rs.resolution_tick()
    assert summary["answered"] == rs.TICK_PAIRS and summary["nodus"] == 0
    assert run.driver is None


def test_a_pending_check_is_handed_to_the_workflow_as_its_user(monkeypatch, db_session, run, fake_engines,
                                                                tick_session):
    monkeypatch.setenv("AINDY_RESOLUTION_NODUS", "1")
    captured = {}
    monkeypatch.setattr(nwr, "run_nodus_workflow",
                        lambda name, **k: captured.update(k, name=name) or {"status": "WAITING", "run_id": "flow-1"})
    summary = rs.resolution_tick()
    assert summary == {"runs": 0, "answered": 0, "skipped": False, "nodus": 1}
    db_session.refresh(run)
    assert (run.driver, run.driver_run_id, run.status) == ("nodus", "flow-1", "running")
    assert _answers(db_session, run) == 0, "the launch only parks; the workflow answers"
    assert captured["name"] == rn.WORKFLOW and captured["user_id"] == str(USER)
    assert captured["input_payload"]["args"] == {"run_id": run.id, "max_batches": 2 + rn.SPARE_BATCHES,
                                                 "sleep_seconds": rn.SLEEP_SECONDS}


def test_a_check_the_workflow_drives_is_left_alone(monkeypatch, db_session, run, fake_engines, tick_session):
    monkeypatch.setenv("AINDY_RESOLUTION_NODUS", "1")
    run.driver, run.driver_run_id, run.status = "nodus", "flow-1", "running"
    db_session.commit()
    monkeypatch.setattr(rn, "_flow_status", lambda db, flow_run_id: "waiting")
    monkeypatch.setattr(nwr, "run_nodus_workflow", lambda *a, **k: pytest.fail("already driven"))
    assert rs.resolution_tick()["nodus"] == 1
    assert _answers(db_session, run) == 0


@pytest.mark.parametrize("flow_status", ["failed", "success", None])
def test_a_dead_workflow_hands_the_check_back_to_python(monkeypatch, db_session, run, fake_engines, tick_session,
                                                         fallbacks, flow_status):
    monkeypatch.setenv("AINDY_RESOLUTION_NODUS", "1")
    run.driver, run.driver_run_id, run.status = "nodus", "flow-1", "running"
    db_session.commit()
    monkeypatch.setattr(rn, "_flow_status", lambda db, flow_run_id: flow_status)
    monkeypatch.setattr(nwr, "run_nodus_workflow", lambda *a, **k: pytest.fail("a running check is not relaunched"))
    summary = rs.resolution_tick()
    assert summary["answered"] == rs.TICK_PAIRS
    assert run.driver is None
    assert [f["workflow"] for f in fallbacks] == [rn.WORKFLOW]


@pytest.mark.parametrize("out", [{"status": "FAILED", "run_id": "flow-1"}, {"status": "SUCCESS"}, None, RuntimeError])
def test_a_launch_that_does_not_park_falls_back_in_the_same_tick(monkeypatch, db_session, run, fake_engines,
                                                                  tick_session, fallbacks, out):
    monkeypatch.setenv("AINDY_RESOLUTION_NODUS", "1")

    def _run(name, **k):
        if out is RuntimeError:
            raise RuntimeError("worker died")
        return out

    monkeypatch.setattr(nwr, "run_nodus_workflow", _run)
    summary = rs.resolution_tick()
    assert summary["answered"] == rs.TICK_PAIRS, "the check is not left a minute behind"
    assert run.driver is None and run.status == "running"
    assert len(fallbacks) == 1


# ── the batch syscall ─────────────────────────────────────────────────────────────────────


def test_a_batch_answers_the_callers_own_check_and_says_what_is_left(db_session, run, fake_engines):
    out = rs.update_run_batch(db_session, USER, run.id)
    assert out == {"handled": rs.TICK_PAIRS, "remaining": 3, "status": "running", "late_s": None}
    out = rs.update_run_batch(db_session, USER, run.id)
    assert out["handled"] == 3 and out["remaining"] == 0 and out["status"] == "done"
    # A late wake after the check finished ends the workflow instead of failing it.
    assert rs.update_run_batch(db_session, USER, run.id) == {"handled": 0, "remaining": 0, "status": "done",
                                                             "late_s": None}


def test_a_batch_never_touches_another_users_check(db_session, run, fake_engines):
    with pytest.raises(ValueError, match="NOT_FOUND"):
        rs.update_run_batch(db_session, uuid.uuid4(), run.id)
    assert _answers(db_session, run) == 0


def test_the_syscall_reads_the_run_user_not_the_payload(monkeypatch):
    from AINDY.kernel.syscall_registry import SyscallContext

    from apps.masterplan.syscalls import syscall_handlers as sh

    seen = {}
    monkeypatch.setattr(sh, "_session_from_context", lambda ctx: (object(), False))
    monkeypatch.setattr(rs, "update_run_batch", lambda db, uid, run_id, woke=None: seen.update(uid=uid, run_id=run_id) or {})
    ctx = SyscallContext(execution_unit_id="eu", user_id="run-user", capabilities=["resolution.write"], trace_id="t")
    sh._handle_resolution_update_run({"run_id": "r1", "user_id": "someone-else"}, ctx)
    assert seen == {"uid": "run-user", "run_id": "r1"}


def test_lateness_is_measured_from_the_waits_own_deadline():
    deadline = (datetime.now(timezone.utc) - timedelta(seconds=12)).isoformat()
    late = rn.lateness_seconds({"timed_out": True, "deadline": deadline})
    assert 11 <= late <= 20
    assert rn.lateness_seconds({"some": "payload"}) is None
    assert rn.lateness_seconds(None) is None


# ── the script ────────────────────────────────────────────────────────────────────────────


def test_the_script_is_a_plain_script_not_a_workflow_block():
    # A step's retry would catch the exception await_event_for raises to park.
    source = _ND_PATH.read_text(encoding="utf-8")
    assert shared_nodus.workflow_kind(source) == "script"
    assert "prior_state(\"batches_done\")" in source
    for nd in Path(bootstrap.__file__).resolve().parents[1].glob("*/nodus/*.nd"):
        if nd != _ND_PATH:
            assert shared_nodus.workflow_kind(nd.read_text(encoding="utf-8")) == "flow-graph", nd


def test_each_wait_has_its_own_name():
    # await_event_for returns at once for a name already delivered: one fixed name parks only once.
    names = re.findall(r"await_event_for\(([^,]+),", _ND_PATH.read_text(encoding="utf-8"))
    assert names and all("str(done" in n for n in names), names


def test_bootstrap_registers_it_as_a_script():
    from AINDY.runtime.nodus_workflow_registry import get_nodus_workflow

    shared_nodus.register_domain_nodus_workflows(bootstrap.__file__, "masterplan")
    meta = get_nodus_workflow(rn.WORKFLOW)
    assert meta is not None and meta["kind"] == "script"


def test_the_syscall_name_grants_the_capability_it_requires():
    import AINDY.main  # noqa: F401  registers the app's syscalls
    from AINDY.kernel.syscall_dispatcher import _infer_dispatch_capability
    from AINDY.kernel.syscall_registry import SYSCALL_REGISTRY

    called = re.findall(r'sys\("([\w.]+)"', _ND_PATH.read_text(encoding="utf-8"))
    assert called == ["sys.v1.resolution.update_run"]
    assert _infer_dispatch_capability(called[0]) == SYSCALL_REGISTRY[called[0]].capability


def test_registering_twice_is_not_a_conflict():
    from apps.masterplan.syscalls.syscall_handlers import register_masterplan_syscall_handlers

    register_masterplan_syscall_handlers()
    register_masterplan_syscall_handlers()
