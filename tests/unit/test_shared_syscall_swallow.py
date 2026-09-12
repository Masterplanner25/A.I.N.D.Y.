"""A swallowed syscall failure says why. `SYSCALL-SILENT-ERRORS-1`.

The dispatcher has eleven error paths that log nothing; the envelope's `error` string reaches
the caller and, until this, died there in a correct-looking early return. The helper keeps
the return and adds the sentence.
"""

from __future__ import annotations

import logging

import pytest

from apps._shared.syscall import failed, swallowed

pytestmark = pytest.mark.app_profile


def test_failed_is_the_lowercase_syscall_envelope():
    assert failed({"status": "error", "error": "permission denied"})
    assert failed({"status": "partial"}), "an incomplete answer is not a complete one"
    assert failed({"status": "unknown"})
    assert failed(None)
    assert not failed({"status": "success", "data": {}})
    assert failed({"status": "SUCCESS"}), "uppercase is the FLOW envelope; that is a different thing"


def test_swallowed_returns_the_default_and_logs_the_error_string(caplog):
    log = logging.getLogger("test.swallow")
    result = {"status": "error", "error": "quota backend unavailable"}

    with caplog.at_level(logging.WARNING, logger="test.swallow"):
        value = swallowed("sys.v1.agent.count_runs", result, default=0, log=log, caller="identity_boot")

    assert value == 0
    record = caplog.records[-1]
    assert record.levelno == logging.WARNING
    assert "sys.v1.agent.count_runs" in record.getMessage()
    assert "'error'" in record.getMessage()
    assert "quota backend unavailable" in record.getMessage()
    assert "identity_boot" in record.getMessage()


def test_swallowed_says_when_the_envelope_carried_no_error(caplog):
    log = logging.getLogger("test.swallow")
    with caplog.at_level(logging.WARNING, logger="test.swallow"):
        value = swallowed("sys.v1.x", {"status": "unknown"}, default=[], log=log)

    assert value == []
    assert "no error string in envelope" in caplog.records[-1].getMessage()


# ── the two live sites ────────────────────────────────────────────────────────────────

def test_identity_boot_count_still_returns_zero_but_says_why(monkeypatch, caplog):
    from apps.identity.services import identity_boot_service as svc

    monkeypatch.setattr(
        "AINDY.kernel.syscall_dispatcher.dispatch_syscall",
        lambda *a, **k: {"status": "error", "error": "input validation: user_id"},
    )
    with caplog.at_level(logging.WARNING, logger=svc.logger.name):
        assert svc._count_user_agent_runs("00000000-0000-0000-0000-000000000001", db=None) == 0

    assert "sys.v1.agent.count_runs" in caplog.text
    assert "input validation: user_id" in caplog.text


def test_dependency_adapter_still_returns_empty_but_says_why(monkeypatch, caplog):
    from apps.analytics.services.integration import dependency_adapter as da

    class _Dispatcher:
        def dispatch(self, name, payload, ctx):
            return {"status": "error", "error": "handler contract violated"}

    monkeypatch.setattr(da, "get_dispatcher", lambda: _Dispatcher())
    with caplog.at_level(logging.WARNING, logger=da.logger.name):
        out = da._dispatch_syscall(
            "sys.v1.automation.update_loop_adjustment", {"adjustment_id": "x"},
            user_id="00000000-0000-0000-0000-000000000001", capability="automation.write",
        )

    assert out == {}
    assert "sys.v1.automation.update_loop_adjustment" in caplog.text
    assert "handler contract violated" in caplog.text
