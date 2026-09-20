"""Every route name we hand to the pipeline must fit `system_events.source` — ROUTE-NAME-EVENT-SOURCE-1.

Found 2026-09-19 reading the api log while the owner used the MasterPlan page on runtime 2.21.0:

    [SystemEvent] Failed to emit execution.started ... (psycopg2.errors.StringDataRightTruncation)
    value too long for type character varying(32)
    execution.event_emit_skipped

The pipeline writes every request's `execution.started` / `execution.completed` with
`source = metadata["source"] or route_name`, and the runtime's `SystemEvent.source` is
`String(32)`. Eight of our 230 route names were longer (`masterplan.strategy.conclusion.propose`
was 38), so those eight routes had never had an execution record — the INSERT failed, the
runtime rolled the request session back and continued at WARNING, the route answered, and the
only trace was a log line nobody was reading. Runtime half: FR-41 (the width, and that a
required event failing on a valid name is reported per request rather than once).

The width is read from the runtime's model, not hard-coded, so this follows a widening.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

pytestmark = pytest.mark.app_profile

APPS = pathlib.Path(__file__).resolve().parents[2] / "apps"


def _source_width() -> int:
    from AINDY.db.models.system_event import SystemEvent

    width = SystemEvent.__table__.c.source.type.length
    assert isinstance(width, int) and width > 0, "system_events.source has no length — update this test"
    return width


def _route_names() -> dict[str, list[str]]:
    """Every string literal passed as a route name to the pipeline or one of our `_execute_*` wrappers."""
    names: dict[str, list[str]] = {}
    for path in APPS.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            fname = getattr(fn, "attr", None) or getattr(fn, "id", None) or ""
            candidates = []
            if fname in {"execute_with_pipeline_sync", "execute_with_pipeline"} and len(node.args) >= 2:
                candidates.append(node.args[1])
            elif fname.startswith("_execute_") and len(node.args) >= 2:
                candidates.append(node.args[1])
            candidates += [kw.value for kw in node.keywords if kw.arg == "route_name"]
            for c in candidates:
                if isinstance(c, ast.Constant) and isinstance(c.value, str):
                    names.setdefault(c.value, []).append(f"{path.relative_to(APPS.parent)}:{c.lineno}")
    return names


def test_the_scan_sees_our_routes():
    names = _route_names()
    assert len(names) > 150, f"the scanner found only {len(names)} route names — did the call shape change?"
    assert "agent.run.create" in names  # a known one, through the `_execute_agent` wrapper


def test_every_route_name_fits_the_event_source_column():
    width = _source_width()
    too_long = {n: v[0] for n, v in _route_names().items() if len(n) > width}
    assert not too_long, (
        f"these route names exceed system_events.source ({width}); every request on them fails its "
        f"execution.started INSERT and leaves no execution record: {too_long}"
    )


def test_the_eight_that_were_over_are_gone():
    names = _route_names()
    for old in (
        "masterplan.strategy.conclusion.propose",
        "masterplan.strategy.conclusion.dismiss",
        "rippletrace_recommendations_summary",
        "rippletrace_recommendations_system",
        "rippletrace_containers_performance",
        "rippletrace_containers_candidates",
        "analytics.policy_thresholds.adapt",
        "freelance.pricing.recommendations",
    ):
        assert old not in names, old
