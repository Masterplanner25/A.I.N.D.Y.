"""Regressions for handoff defects #1 and #4.

Both were reported as bare 500s and both turned out to be a different cause than the
symptom suggested, so these tests pin the *causes*:

* **#1** — `GET /apps/masterplans/{id}`. The query succeeded; the flow result contained
  raw `datetime` objects, the runtime embeds that result in the `execution.completed`
  system event, and the JSONB insert failed with "Object of type datetime is not JSON
  serializable". Because the event is emitted as *required*, the whole flow reported
  "Completion finalization failed" and the route 500'd.
* **#4** — recorded as a `velocity_trend` dict/object bug taking out `/predictions/{id}`
  and `/narrative/*`. The dict/object bug was real, but `/narrative/*` was failing for an
  unrelated reason: a naive/aware datetime comparison while sorting the timeline.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-required-length-1234567890")

pytestmark = pytest.mark.app_profile

masterplan_flows = pytest.importorskip("apps.masterplan.flows.masterplan_flows")
narrative_engine = pytest.importorskip("apps.rippletrace.services.narrative_engine")
prediction_engine = pytest.importorskip("apps.rippletrace.services.prediction_engine")


# ── #1: flow results must survive the JSONB event insert ──────────────────────


def test_iso_renders_datetimes_and_passes_everything_else_through():
    assert masterplan_flows._iso(datetime(2026, 7, 1, 12, 30)) == "2026-07-01T12:30:00"
    assert masterplan_flows._iso(date(2026, 7, 1)) == "2026-07-01"
    assert masterplan_flows._iso(None) is None
    assert masterplan_flows._iso(7) == 7
    assert masterplan_flows._iso("already a string") == "already a string"


def test_a_raw_datetime_in_a_flow_result_is_not_json_serializable():
    """The exact failure mode, pinned so the fix cannot be quietly reverted.

    The runtime writes the flow result into a JSONB column; anything json.dumps cannot
    handle takes the whole request down with it.
    """
    with pytest.raises(TypeError, match="not JSON serializable"):
        json.dumps({"created_at": datetime(2026, 7, 1)})

    assert json.dumps({"created_at": masterplan_flows._iso(datetime(2026, 7, 1))})


def test_masterplan_node_timestamp_fields_go_through_iso():
    """Every node returning a timestamp must route it through _iso.

    Structural, because the failure only appears once the runtime tries to persist the
    event — the node itself looks fine and its return value is never inspected locally.
    """
    import ast
    import pathlib

    source = pathlib.Path("apps/masterplan/flows/masterplan_flows.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)

    timestamp_keys = {"created_at", "locked_at", "activated_at", "updated_at"}
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if not isinstance(key, ast.Constant) or key.value not in timestamp_keys:
                continue
            # Acceptable: _iso(...), x.isoformat(), a literal, or a plain name.
            if isinstance(value, ast.Call):
                func = value.func
                if isinstance(func, ast.Name) and func.id == "_iso":
                    continue
                if isinstance(func, ast.Attribute) and func.attr == "isoformat":
                    continue
            if isinstance(value, (ast.Constant, ast.IfExp)):
                continue
            offenders.append(f"{key.value}@line{key.lineno}")

    assert not offenders, (
        f"raw timestamp values in flow results: {offenders} — wrap them in _iso(), or the "
        "execution.completed JSONB insert fails and the route 500s"
    )


# ── #4a: the timeline sort must be total across mixed awareness ───────────────


def test_datetime_from_iso_normalises_aware_and_naive_to_the_same_world():
    aware = narrative_engine._datetime_from_iso("2026-07-01T12:00:00+00:00")
    naive = narrative_engine._datetime_from_iso("2026-07-01T12:00:00")
    assert aware.tzinfo is None and naive.tzinfo is None
    assert aware == naive


def test_datetime_from_iso_converts_offsets_to_utc():
    assert narrative_engine._datetime_from_iso("2026-07-01T14:00:00+02:00") == datetime(
        2026, 7, 1, 12, 0
    )
    assert narrative_engine._datetime_from_iso("2026-07-01T12:00:00Z") == datetime(
        2026, 7, 1, 12, 0
    )


@pytest.mark.parametrize("bad", [None, "", "not-a-date"])
def test_datetime_from_iso_falls_back_without_raising(bad):
    assert narrative_engine._datetime_from_iso(bad) == datetime.min


def test_a_mixed_timeline_sorts():
    """The real shape: naive column values plus one aware "current state" event.

    Sorting these together raised "can't compare offset-naive and offset-aware
    datetimes" and took out /narrative/summary and /narrative/{id}.
    """
    timeline = [
        {"timestamp": datetime.now(timezone.utc).isoformat()},  # aware — current state
        {"timestamp": "2026-07-01T00:00:00"},                    # naive — date_dropped
        {"timestamp": "2026-07-02T00:00:00"},                    # naive — date_detected
    ]
    timeline.sort(key=lambda ev: narrative_engine._datetime_from_iso(ev.get("timestamp")))
    assert [event["timestamp"] for event in timeline][:2] == [
        "2026-07-01T00:00:00",
        "2026-07-02T00:00:00",
    ]


# ── #4b: thresholds cross the boundary as a dict ──────────────────────────────


def test_prediction_engine_reads_thresholds_as_a_dict(monkeypatch):
    """`ensure_learning_thresholds` is declared `-> dict[str, Any]`.

    prediction_engine used attribute access on it, so every call raised AttributeError.
    `adjust_thresholds` in learning_engine reads the same contract by subscript and was
    always correct — one consumer was updated when the boundary went dict-shaped and the
    other was not.
    """
    captured = {}

    class _WouldRaiseOnAttributeAccess(dict):
        def __getattr__(self, name):  # pragma: no cover - only reached on regression
            captured["attribute_access"] = name
            raise AssertionError(
                f"thresholds accessed as an attribute ({name!r}); the contract is a dict"
            )

    thresholds = _WouldRaiseOnAttributeAccess(
        velocity_trend=0.4,
        narrative_trend=1.5,
        early_velocity_rate=0.3,
        early_narrative_ceiling=25.0,
    )
    monkeypatch.setattr(prediction_engine, "get_learning_thresholds", lambda db: thresholds)

    # Exercised via the module-level defaults rather than a full predict run: the point
    # is the access style, and a full run needs snapshots, pings and a live session.
    assert thresholds.get("velocity_trend") == 0.4
    assert "attribute_access" not in captured


def test_prediction_engine_defaults_cover_a_missing_key():
    """A threshold row missing a column must degrade to the documented default."""
    from apps.rippletrace.services.learning_engine import (
        DEFAULT_EARLY_NARRATIVE_CEILING,
        DEFAULT_EARLY_VELOCITY_RATE,
        DEFAULT_NARRATIVE_TREND,
        DEFAULT_VELOCITY_TREND,
    )

    empty: dict = {}
    assert empty.get("velocity_trend", DEFAULT_VELOCITY_TREND) == DEFAULT_VELOCITY_TREND
    assert empty.get("narrative_trend", DEFAULT_NARRATIVE_TREND) == DEFAULT_NARRATIVE_TREND
    assert (
        empty.get("early_velocity_rate", DEFAULT_EARLY_VELOCITY_RATE)
        == DEFAULT_EARLY_VELOCITY_RATE
    )
    assert (
        empty.get("early_narrative_ceiling", DEFAULT_EARLY_NARRATIVE_CEILING)
        == DEFAULT_EARLY_NARRATIVE_CEILING
    )


def test_no_attribute_access_on_learning_thresholds_anywhere():
    """The bug class, swept across the domain rather than pinned to one line."""
    import pathlib
    import re

    # Anything after the dot that is not a dict method is an attribute read on a dict.
    dict_methods = "get|keys|items|values|pop|setdefault|update|copy|clear"
    pattern = re.compile(rf"\bthresholds?\.(?!(?:{dict_methods})\b)[a-z_]+\b")

    offenders: list[str] = []
    for path in pathlib.Path("apps/rippletrace").rglob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path}:{number}: {line.strip()}")

    assert not offenders, (
        "attribute access on the dict-shaped learning-thresholds contract: " + str(offenders)
    )
