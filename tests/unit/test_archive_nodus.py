"""Archiving published work on the Nodus VM (owner, 2026-10-22: our workflows are written in Nodus).

`archive_published_work` hands each owner with something due to `archive_published_work_v1.nd`
behind AINDY_ARCHIVE_NODUS, falling back to Python per owner. Covers the flag and the due guard,
the envelope merge, the fallback, the workflow's compile and registration, and that each step's
syscall name grants the capability it requires and reads the user from the run.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import AINDY.runtime.nodus_workflow_registry as nwr
from apps.rippletrace import bootstrap
from apps.rippletrace.services import archive_nodus, content_archive
from apps.rippletrace.services.archive_nodus import STEP_KEYS, _outcome, archive_owner, nodus_archive_enabled

pytestmark = pytest.mark.app_profile

_ND_PATH = Path(bootstrap.__file__).resolve().parent / "nodus" / "archive_published_work_v1.nd"
_STEP_DATA = ({"recleaned": 0}, {"fetched": 2, "none": 0, "failed": 0}, {"collapsed": 1}, {"remembered": 2, "chunks": 9})


def _envelope(*, nodus_status="success", failing_step=None) -> dict:
    state = {
        key: {"status": "error" if key == failing_step else "success", "data": data}
        for key, data in zip(STEP_KEYS, _STEP_DATA)
    }
    return {"status": "SUCCESS", "data": {"nodus_status": nodus_status, "nodus_output_state": state}}


class _Db:
    def rollback(self):
        pass


@pytest.fixture
def python_path(monkeypatch):
    calls = []
    monkeypatch.setattr(content_archive, "archive_step", lambda db, user_id: calls.append(user_id) or {"fetched": 0})
    return calls


class TestRouting:

    def test_flag_default_off(self, monkeypatch):
        monkeypatch.delenv("AINDY_ARCHIVE_NODUS", raising=False)
        assert nodus_archive_enabled() is False
        monkeypatch.setenv("AINDY_ARCHIVE_NODUS", "1")
        assert nodus_archive_enabled() is True

    def test_off_uses_python(self, monkeypatch, python_path):
        monkeypatch.delenv("AINDY_ARCHIVE_NODUS", raising=False)
        monkeypatch.setattr(nwr, "run_nodus_workflow", lambda *a, **k: pytest.fail("flag is off"))
        assert archive_owner(_Db(), "u1") == ({"fetched": 0}, "python")
        assert python_path == ["u1"]

    def test_nothing_due_stays_in_python(self, monkeypatch, python_path):
        # A settled catalogue must not boot a cold worker every 10 minutes.
        monkeypatch.setenv("AINDY_ARCHIVE_NODUS", "1")
        monkeypatch.setattr(archive_nodus, "archive_due", lambda db, uid: False)
        monkeypatch.setattr(nwr, "run_nodus_workflow", lambda *a, **k: pytest.fail("nothing is due"))
        assert archive_owner(_Db(), "u1")[1] == "python"

    def test_due_runs_the_workflow_as_the_owner(self, monkeypatch, python_path):
        monkeypatch.setenv("AINDY_ARCHIVE_NODUS", "1")
        monkeypatch.setattr(archive_nodus, "archive_due", lambda db, uid: True)
        captured = {}
        monkeypatch.setattr(nwr, "run_nodus_workflow", lambda name, **k: captured.update(k, name=name) or _envelope())
        outcome, via = archive_owner(_Db(), "u1")
        assert via == "nodus" and python_path == []
        assert outcome == {"recleaned": 0, "fetched": 2, "none": 0, "failed": 0, "collapsed": 1, "remembered": 2, "chunks": 9}
        assert captured["name"] == "archive_published_work_v1"
        assert captured["user_id"] == "u1"
        assert captured["input_payload"]["args"] == {"limit": archive_nodus.NODUS_BATCH}

    @pytest.mark.parametrize("out", [
        _envelope(nodus_status="failure"),
        _envelope(failing_step="collapse_result"),
        None,
    ])
    def test_a_failed_vm_run_falls_back_to_python(self, monkeypatch, python_path, out):
        monkeypatch.setenv("AINDY_ARCHIVE_NODUS", "1")
        monkeypatch.setattr(archive_nodus, "archive_due", lambda db, uid: True)
        monkeypatch.setattr(nwr, "run_nodus_workflow", lambda name, **k: out)
        assert archive_owner(_Db(), "u1")[1] == "python"
        assert python_path == ["u1"]

    def test_a_raising_vm_falls_back_to_python(self, monkeypatch, python_path):
        monkeypatch.setenv("AINDY_ARCHIVE_NODUS", "1")
        monkeypatch.setattr(archive_nodus, "archive_due", lambda db, uid: True)

        def _raise(name, **k):
            raise RuntimeError("worker died")

        monkeypatch.setattr(nwr, "run_nodus_workflow", _raise)
        assert archive_owner(_Db(), "u1")[1] == "python"

    def test_outcome_needs_every_step(self):
        assert _outcome(_envelope()) is not None
        for key in STEP_KEYS:
            assert _outcome(_envelope(failing_step=key)) is None


class TestWorkflow:

    def test_source_compiles_with_four_steps_in_order(self):
        from AINDY.runtime.nodus_flow_compiler import compile_nodus_flow

        source = _ND_PATH.read_text(encoding="utf-8")
        graph = compile_nodus_flow(source)
        assert graph["workflow_name"] == "archive_published_work_v1"
        assert re.findall(r'set_state\("(\w+)"', source) == list(STEP_KEYS)

    def test_bootstrap_registers_it(self):
        from AINDY.runtime.nodus_workflow_registry import get_nodus_workflow

        bootstrap._register_nodus_workflows()
        meta = get_nodus_workflow("archive_published_work_v1")
        assert meta is not None and meta["kind"] == "flow-graph"

    def test_each_step_syscall_grants_its_capability(self):
        # A .nd's sys() is granted only the capability inferred from the name; a mismatch denies
        # every VM run, and the job quietly falls back to Python.
        import AINDY.main  # noqa: F401  registers the app's syscalls
        from AINDY.kernel.syscall_dispatcher import _infer_dispatch_capability
        from AINDY.kernel.syscall_registry import SYSCALL_REGISTRY

        from apps.rippletrace.syscalls import ARCHIVE_STEP_SYSCALLS

        called = re.findall(r'sys\("([\w.]+)"', _ND_PATH.read_text(encoding="utf-8"))
        assert sorted(called) == sorted(ARCHIVE_STEP_SYSCALLS)
        for name in called:
            assert _infer_dispatch_capability(name) == SYSCALL_REGISTRY[name].capability, name

    def test_step_syscalls_read_the_run_user_not_the_payload(self, monkeypatch):
        from AINDY.kernel.syscall_registry import SyscallContext

        from apps.rippletrace import syscalls

        seen = {}
        monkeypatch.setattr(syscalls, "_session_from_context", lambda ctx: (object(), False))
        for name, (step, _) in syscalls.ARCHIVE_STEP_SYSCALLS.items():
            monkeypatch.setitem(
                syscalls.ARCHIVE_STEP_SYSCALLS, name, (lambda db, uid, limit, n=name: seen.__setitem__(n, (uid, limit)) or {}, _)
            )
        ctx = SyscallContext(execution_unit_id="eu", user_id="run-user", capabilities=["rippletrace.write"], trace_id="t")
        for name, (step, _) in syscalls.ARCHIVE_STEP_SYSCALLS.items():
            syscalls._archive_step(step)({"user_id": "someone-else", "limit": 999}, ctx)
        assert set(seen) == set(syscalls.ARCHIVE_STEP_SYSCALLS)
        assert all(uid == "run-user" and limit == content_archive.BATCH for uid, limit in seen.values())


def test_registering_twice_is_not_a_conflict():
    # Every boot registers again, and the registry refuses a second handler object for one name.
    from apps.rippletrace.syscalls import register_rippletrace_syscall_handlers

    register_rippletrace_syscall_handlers()
    register_rippletrace_syscall_handlers()
