"""A Nodus workflow is registered in the process that runs it, not only in the api process.

A scheduled job's callback runs in a fresh subprocess that imports only the job's module, so the
runtime's in-memory registry is empty there. From 2026-10-22 to 2026-11-01 every scheduled run of
ours (the Infinity recalc, the archive) fell back to Python with ``nodus workflow '…' is not
registered``. `run_domain_nodus_workflow` registers the domain's ``.nd`` files first when needed.
"""
from __future__ import annotations

import inspect

import pytest

import AINDY.runtime.nodus_workflow_registry as nwr
from apps._shared.nodus import run_domain_nodus_workflow
from apps.analytics.services.orchestration import nodus_recalc
from apps.analytics.services.reasoning import nodus_apply
from apps.rippletrace.services import archive_nodus, share_nodus

pytestmark = pytest.mark.app_profile

CALLERS = [
    ("analytics", nodus_recalc),
    ("analytics", nodus_apply),
    ("rippletrace", archive_nodus),
    ("rippletrace", share_nodus),
]


@pytest.mark.parametrize("domain,module", CALLERS)
def test_an_empty_registry_is_filled_before_the_run(monkeypatch, domain, module):
    monkeypatch.setattr(nwr, "_NODUS_WORKFLOWS", {})
    seen = {}

    def _run(name, **kwargs):
        seen["registered"] = nwr.get_nodus_workflow(name) is not None
        return {}

    monkeypatch.setattr(nwr, "run_nodus_workflow", _run)
    run_domain_nodus_workflow(domain, module._WORKFLOW, db=None, user_id="u")
    assert seen == {"registered": True}


@pytest.mark.parametrize("domain,module", CALLERS)
def test_every_caller_runs_through_the_helper(domain, module):
    source = inspect.getsource(module)
    assert "run_domain_nodus_workflow(" in source
    assert "import run_nodus_workflow" not in source
