"""Register a domain's Nodus workflows — every ``nodus/*.nd`` beside its ``bootstrap.py``.

Owner, 2026-10-22: our own workflows are written in Nodus (`CLAUDE.md`). Each domain that has
some calls this from ``register()``. Workflows are registered in memory each boot (``db=None``,
re-registered from the source file) and compiled at registration. Non-fatal: a failure warns
rather than failing the domain's boot.
"""
from __future__ import annotations

import logging
from pathlib import Path

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
