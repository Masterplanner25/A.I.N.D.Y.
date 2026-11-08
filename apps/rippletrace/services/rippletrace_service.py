from __future__ import annotations

import logging
import uuid
from typing import Any

from AINDY.platform_layer.event_trace_service import (
    build_trace_graph,
    calculate_depth,
    detect_root_event,
    detect_terminal_events,
    get_downstream_effects,
    link_event_to_memory,
    link_events,
)
from AINDY.db.models.system_event import SystemEvent

logger = logging.getLogger(__name__)


# Every trace helper takes the caller's user_id (runtime 2.31.6, FR-60): with it the runtime keeps only
# that user's events and memory nodes, and the edges whose ends both remain. None means unscoped.
def get_trace_graph(db, trace_id: str, user_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
    return build_trace_graph(db, trace_id, user_id=user_id)


def get_upstream_causes(db, event_id):
    from AINDY.platform_layer.event_trace_service import get_upstream_relationships

    return get_upstream_relationships(db, event_id)


def calculate_ripple_span(db, trace_id, user_id: str | None = None):
    from AINDY.platform_layer.event_trace_service import calculate_trace_span

    return calculate_trace_span(db, trace_id, user_id=user_id)


def detect_dominant_path(db, trace_id: str, user_id: str | None = None) -> list[dict[str, Any]]:
    graph = build_trace_graph(db, trace_id, user_id=user_id)
    if not graph["nodes"]:
        return []
    node_map = {node["id"]: node for node in graph["nodes"]}
    outgoing: dict[str, list[dict[str, Any]]] = {}
    for edge in graph["edges"]:
        outgoing.setdefault(edge["source"], []).append(edge)
    root = detect_root_event(db, trace_id, user_id=user_id)
    if not root:
        return []

    best_path: list[str] = []

    def _walk(node_id: str, path: list[str]) -> None:
        nonlocal best_path
        next_path = path + [node_id]
        if len(next_path) > len(best_path):
            best_path = next_path
        candidates = sorted(
            outgoing.get(node_id, []),
            key=lambda edge: (
                float(edge.get("weight") or 0.0),
                edge.get("relationship_type") == "caused_by",
            ),
            reverse=True,
        )
        for edge in candidates:
            target = edge["target"]
            if not target or target in next_path:
                continue
            _walk(target, next_path)

    _walk(root["id"], [])
    return [node_map[node_id] for node_id in best_path if node_id in node_map]


def detect_failure_clusters(db, trace_id: str, user_id: str | None = None) -> list[dict[str, Any]]:
    graph = build_trace_graph(db, trace_id, user_id=user_id)
    failures = [
        node
        for node in graph["nodes"]
        if node.get("node_kind") == "system_event"
        and (
            "failed" in str(node.get("type") or "").lower()
            or "error" in str(node.get("type") or "").lower()
        )
    ]
    clustered: dict[str, dict[str, Any]] = {}
    for node in failures:
        key = str(node.get("type") or "unknown_failure")
        bucket = clustered.setdefault(
            key,
            {"type": key, "count": 0, "events": [], "latest_timestamp": None},
        )
        bucket["count"] += 1
        bucket["events"].append(node)
        timestamp = node.get("timestamp")
        if timestamp and (
            bucket["latest_timestamp"] is None or timestamp > bucket["latest_timestamp"]
        ):
            bucket["latest_timestamp"] = timestamp
    return sorted(clustered.values(), key=lambda item: item["count"], reverse=True)


def _owned_drop_point_ids(db, events: list[dict[str, Any]], user_id: str | None = None) -> list[str]:
    """The drop points named in ``events`` that belong to the user whose event named them.

    An event's payload is written by whoever posted it (`POST /rippletrace/event` takes any
    `drop_point_id`), so naming a drop point proves nothing. Without this, a user could post an
    event naming someone else's drop point into their own trace, open the trace, and read that
    drop point's prediction and recommendation. A drop point counts only if its owner is the
    event's user, and also the caller when one is given. The runtime's execution-graph view
    calls this with no caller, so the event's owner is what makes it safe there.
    """
    from apps.rippletrace.models import DropPointDB

    named: list[tuple[str, uuid.UUID | None]] = []
    for event in events:
        payload = event.get("payload") or {}
        dp_id = payload.get("drop_point_id") or payload.get("drop_id")
        if not dp_id or not isinstance(dp_id, str):
            continue
        try:
            event_id = uuid.UUID(str(event.get("id")))
        except (TypeError, ValueError):
            event_id = None
        named.append((dp_id, event_id))
    if not named:
        return []

    event_ids = [event_id for _dp, event_id in named if event_id is not None]
    event_owner = (
        dict(db.query(SystemEvent.id, SystemEvent.user_id).filter(SystemEvent.id.in_(event_ids)).all())
        if event_ids
        else {}
    )
    dp_owner = dict(
        db.query(DropPointDB.id, DropPointDB.user_id)
        .filter(DropPointDB.id.in_([dp for dp, _event in named]))
        .all()
    )
    caller = None
    if user_id is not None:
        try:
            caller = uuid.UUID(str(user_id))
        except (TypeError, ValueError):
            return []

    owned: list[str] = []
    for dp_id, event_id in named:
        owner = dp_owner.get(dp_id)
        if owner is None or dp_id in owned:
            continue
        if event_owner.get(event_id) != owner:
            continue
        if caller is not None and owner != caller:
            continue
        owned.append(dp_id)
    return owned


def generate_trace_insights(db, trace_id: str, user_id: str | None = None) -> dict[str, Any]:
    root_event = detect_root_event(db, trace_id, user_id=user_id)
    terminal_events = detect_terminal_events(db, trace_id, user_id=user_id)
    dominant_path = detect_dominant_path(db, trace_id, user_id=user_id)
    failure_clusters = detect_failure_clusters(db, trace_id, user_id=user_id)
    ripple_span = calculate_ripple_span(db, trace_id, user_id=user_id)

    # Only drop points owned by the event's user (and the caller, when given); see above.
    drop_point_ids = _owned_drop_point_ids(
        db, terminal_events + ([root_event] if root_event else []), user_id
    )

    predictions: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []
    engine_errors: list[dict[str, str]] = []
    if drop_point_ids:
        from apps.rippletrace.services.prediction_engine import predict_drop_point
        from apps.rippletrace.services.recommendation_engine import (
            recommend_for_drop_point,
        )

        for drop_point_id in drop_point_ids[:3]:
            try:
                prediction = predict_drop_point(
                    drop_point_id,
                    db,
                    record_learning=False,
                )
                if prediction.get("prediction") or prediction.get("status"):
                    predictions.append(prediction)
            except Exception as exc:
                logger.warning(
                    "[rippletrace] prediction insight failed for drop_point %s: %s",
                    drop_point_id,
                    exc,
                )
                engine_errors.append(
                    {
                        "engine": "prediction_engine",
                        "drop_point_id": drop_point_id,
                        "error": str(exc),
                    }
                )
            try:
                recommendation = recommend_for_drop_point(
                    drop_point_id,
                    db,
                    log_prediction=False,
                )
                if recommendation.get("action") or recommendation.get("status"):
                    recommendations.append(recommendation)
            except Exception as exc:
                logger.warning(
                    "[rippletrace] recommendation insight failed for drop_point %s: %s",
                    drop_point_id,
                    exc,
                )
                engine_errors.append(
                    {
                        "engine": "recommendation_engine",
                        "drop_point_id": drop_point_id,
                        "error": str(exc),
                    }
                )

    summary_parts: list[str] = []
    if root_event:
        summary_parts.append(f"Root: {root_event.get('type')}.")
    if dominant_path:
        path_str = " → ".join(
            str(node.get("type", node.get("id", "?")))[:30]
            for node in dominant_path[:5]
        )
        summary_parts.append(f"Path: {path_str}.")
    if failure_clusters:
        top = failure_clusters[0]
        summary_parts.append(f"Primary failure: {top['type']} ({top['count']}×).")
    if predictions:
        prediction = predictions[0]
        summary_parts.append(
            f"Signal outlook: {prediction.get('prediction')} "
            f"(confidence {prediction.get('confidence', 0):.2f})."
        )
    if terminal_events:
        summary_parts.append(f"{len(terminal_events)} terminal effects.")

    final_summary = (
        " ".join(summary_parts)
        if summary_parts
        else "No causal insight available for this trace."
    )

    rec_strings: list[str] = []
    for recommendation in recommendations:
        for item in (recommendation.get("recommendations") or [])[:2]:
            rec_strings.append(item)
    if not rec_strings:
        if failure_clusters:
            rec_strings.append(
                f"Stabilize {failure_clusters[0]['type']} before retrying."
            )
        if ripple_span.get("depth", 0) >= 4:
            rec_strings.append(
                "Inspect the dominant causal chain for excessive propagation depth."
            )
    if not rec_strings:
        rec_strings.append(
            "Monitor the dominant path and terminal events for the next run."
        )

    return {
        "root_cause": root_event,
        "dominant_path": dominant_path,
        "failure_clusters": failure_clusters,
        "summary": final_summary,
        "recommendations": rec_strings,
        "predictions": predictions,
        "drop_point_recommendations": recommendations,
        "ripple_span": ripple_span,
        "engine_errors": engine_errors,
    }


def user_owns_event(db, event_id, user_id: str) -> bool:
    return (
        db.query(SystemEvent.id)
        .filter(SystemEvent.id == event_id, SystemEvent.user_id == uuid.UUID(str(user_id)))
        .first()
        is not None
    )


def count_trace_events(db, trace_id: str, user_id: str) -> int:
    """Return the number of SystemEvent rows matching trace_id for user_id."""
    return (
        db.query(SystemEvent)
        .filter(
            SystemEvent.trace_id == trace_id,
            SystemEvent.user_id == uuid.UUID(str(user_id)),
        )
        .count()
    )
