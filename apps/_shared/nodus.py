"""Register a domain's Nodus workflows — every ``nodus/*.nd`` beside its ``bootstrap.py``.

Owner, 2026-10-22: our own workflows are written in Nodus (`CLAUDE.md`). Each domain that has
some calls this from ``register()``. Workflows are registered in memory each boot (``db=None``,
re-registered from the source file) and compiled at registration. Non-fatal: a failure warns
rather than failing the domain's boot.

**A scheduled job does not see those registrations.** Its callback runs in a fresh subprocess
(`runtime_callback_worker`) that imports only the job's own module, never ``load_plugins()``, so the
runtime's in-memory workflow registry is empty there. From 2026-10-22 to 2026-11-01 every scheduled
run of ours fell back to Python with ``nodus workflow '…' is not registered``. A caller runs its
workflow through `run_domain_nodus_workflow`, which registers the domain's ``.nd`` files first when
the name is missing.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def register_domain_nodus_workflows(bootstrap_file: str, domain: str) -> list[str]:
    """Register ``<domain dir>/nodus/*.nd``. Returns the names registered."""
    nd_dir = Path(bootstrap_file).resolve().parent / "nodus"
    if not nd_dir.is_dir():
        return []
    try:
        from AINDY.runtime.nodus_workflow_registry import register_nodus_workflow
    except Exception as exc:  # runtime without the hook
        logger.warning("[%s] register_nodus_workflow unavailable (non-fatal): %s", domain, exc)
        return []

    registered: list[str] = []
    for nd_file in sorted(nd_dir.glob("*.nd")):
        try:
            register_nodus_workflow(
                nd_file.stem,
                nd_file.read_text(encoding="utf-8"),
                kind="flow-graph",
                owner_class="first-party-app",
                allow_legacy_missing_provenance=True,
                overwrite=True,
                db=None,
            )
            registered.append(nd_file.stem)
            logger.info("[%s] registered nodus workflow %s", domain, nd_file.stem)
        except Exception as exc:
            logger.warning("[%s] nodus workflow %s registration skipped (non-fatal): %s", domain, nd_file.stem, exc)
    return registered


def ensure_domain_nodus_workflow(domain: str, name: str) -> None:
    """Register ``apps/<domain>/nodus/*.nd`` in this process if ``name`` is not registered yet."""
    from AINDY.runtime.nodus_workflow_registry import get_nodus_workflow

    if get_nodus_workflow(name) is None:
        register_domain_nodus_workflows(str(Path(__file__).resolve().parents[1] / domain / "bootstrap.py"), domain)


def run_domain_nodus_workflow(domain: str, name: str, **kwargs: Any) -> dict[str, Any]:
    """`run_nodus_workflow`, after making sure ``name`` is registered in this process."""
    from AINDY.runtime.nodus_workflow_registry import run_nodus_workflow

    ensure_domain_nodus_workflow(domain, name)
    return run_nodus_workflow(name, **kwargs)
