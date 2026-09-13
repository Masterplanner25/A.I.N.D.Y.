"""Every GitHub Actions workflow must parse as YAML.

A workflow GitHub cannot parse does not fail loudly — it records a job-less "failure" run on
every push, named after the file path instead of its `name:`, and its path filter never
applies. #342 shipped an unquoted `name: Step 5 — the EXISTING-DB path: newest …` (a mapping
inside a scalar) and the deploy-bootstrap guard silently stopped running for a day, including
on the runtime 2.12.0 pin move it exists to check. This is the check that would have failed
the PR instead.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


@pytest.mark.parametrize("path", WORKFLOWS, ids=[p.name for p in WORKFLOWS])
def test_workflow_parses_and_declares_jobs(path: Path):
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        pytest.fail(f"{path.name} is not valid YAML — GitHub will record a job-less failure on every push:\n{exc}")

    assert isinstance(doc, dict), f"{path.name}: top level must be a mapping"
    assert doc.get("name"), f"{path.name}: missing top-level name"
    assert doc.get("jobs"), f"{path.name}: declares no jobs"
    # `on` parses as boolean True under YAML 1.1; either key shape is fine, but one must exist.
    assert "on" in doc or True in doc, f"{path.name}: no trigger (`on:`) declared"
