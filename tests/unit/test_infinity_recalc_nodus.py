"""Daily Infinity recalculation on the Nodus VM (owner, 2026-10-22: our workflows are written in Nodus).

`_scheduler_recalculate_all_scores` hands each user to `infinity_recalc_v1.nd` behind
AINDY_INFINITY_RECALC_NODUS, falling back to Python per user. Covers the flag gate, the envelope
check, the fallback, that the workflow compiles and registers, and that it calls a syscall whose
name grants the capability it requires and which reads the user from the run.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import AINDY.runtime.nodus_workflow_registry as nwr
from apps.analytics import bootstrap
from apps.analytics.services.orchestration import nodus_recalc
from apps.analytics.services.orchestration.nodus_recalc import (
    _succeeded,
    nodus_recalc_enabled,
    recalculate_user,
)

pytestmark = pytest.mark.app_profile

_ND_PATH = Path(bootstrap.__file__).resolve().parent / "nodus" / "infinity_recalc_v1.nd"


def _envelope(*, nodus_status="success", syscall_status="success", score=None) -> dict:
    return {
        "status": "SUCCESS",
        "data": {
            "nodus_status": nodus_status,
            "nodus_output_state": {
                "infinity_recalc_result": {
                    "status": syscall_status,
                    "data": {"score_recalculate_result": {"master_score": 45.2} if score is None else score},
                },
            },
        },
    }


class TestRouting:

    def test_flag_default_off(self, monkeypatch):
        monkeypatch.delenv("AINDY_INFINITY_RECALC_NODUS", raising=False)
        assert nodus_recalc_enabled() is False
        monkeypatch.setenv("AINDY_INFINITY_RECALC_NODUS", "1")
        assert nodus_recalc_enabled() is True

    def test_off_uses_python(self, monkeypatch):
        monkeypatch.delenv("AINDY_INFINITY_RECALC_NODUS", raising=False)
        monkeypatch.setattr(nodus_recalc, "_recalc_via_python", lambda db, uid: {"score": 1})

        def _boom(*a, **k):
            raise AssertionError("nodus path must not run when the flag is off")

        monkeypatch.setattr(nwr, "run_nodus_workflow", _boom)
        assert recalculate_user(None, "u1") == (True, "python")

    def test_on_runs_the_workflow_as_the_user(self, monkeypatch):
        monkeypatch.setenv("AINDY_INFINITY_RECALC_NODUS", "1")
        captured = {}

        def _run(name, **kwargs):
            captured.update(kwargs, name=name)
            return _envelope()

        monkeypatch.setattr(nwr, "run_nodus_workflow", _run)
        assert recalculate_user(None, "u1") == (True, "nodus")
        assert captured["name"] == "infinity_recalc_v1"
        assert captured["user_id"] == "u1"
        # No user_id in the payload: the syscall reads the run's own user.
        assert "user_id" not in captured["input_payload"]["args"]

    @pytest.mark.parametrize("out", [
        _envelope(nodus_status="failure"),
        _envelope(syscall_status="error"),
        _envelope(score={}),
        None,
    ])
    def test_a_failed_vm_run_falls_back_to_python(self, monkeypatch, out):
        monkeypatch.setenv("AINDY_INFINITY_RECALC_NODUS", "1")
        monkeypatch.setattr(nwr, "run_nodus_workflow", lambda name, **k: out)
        monkeypatch.setattr(nodus_recalc, "_recalc_via_python", lambda db, uid: {"score": 1})
        assert recalculate_user(None, "u1") == (True, "python")

    def test_a_raising_vm_falls_back_to_python(self, monkeypatch):
        monkeypatch.setenv("AINDY_INFINITY_RECALC_NODUS", "1")

        def _raise(name, **k):
            raise RuntimeError("worker died")

        monkeypatch.setattr(nwr, "run_nodus_workflow", _raise)
        monkeypatch.setattr(nodus_recalc, "_recalc_via_python", lambda db, uid: {"score": 1})
        assert recalculate_user(None, "u1") == (True, "python")

    def test_success_needs_a_score(self):
        assert _succeeded(_envelope()) is True
        assert _succeeded(_envelope(score={})) is False


class TestWorkflow:

    def test_source_compiles(self):
        from AINDY.runtime.nodus_flow_compiler import compile_nodus_flow

        graph = compile_nodus_flow(_ND_PATH.read_text(encoding="utf-8"))
        assert graph["workflow_name"] == "infinity_recalc_v1"

    def test_bootstrap_registers_it(self):
        from AINDY.runtime.nodus_workflow_registry import get_nodus_workflow

        bootstrap._register_nodus_workflows()
        meta = get_nodus_workflow("infinity_recalc_v1")
        assert meta is not None
        assert meta["kind"] == "flow-graph"
        assert meta["owner_class"] == "first-party-app"

    def test_the_syscall_name_grants_its_capability(self):
        # A .nd's sys() is granted the capability inferred from the syscall's name. If that is not
        # the one the syscall requires, every VM run is denied and silently falls back to Python.
        import AINDY.main  # noqa: F401  registers the app's syscalls
        from AINDY.kernel.syscall_dispatcher import _infer_dispatch_capability
        from AINDY.kernel.syscall_registry import SYSCALL_REGISTRY

        name = "sys.v1.score.recalculate"
        assert f'sys("{name}"' in _ND_PATH.read_text(encoding="utf-8")
        assert _infer_dispatch_capability(name) == SYSCALL_REGISTRY[name].capability
