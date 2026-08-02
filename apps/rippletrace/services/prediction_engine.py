from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from apps.rippletrace.services.engine_registry import call_with_engine_breaker
from apps.rippletrace.models import PingDB
from apps.rippletrace.services.delta_engine import compute_deltas, drop_point_ids_with_history
from apps.rippletrace.services.learning_engine import (
    DEFAULT_EARLY_NARRATIVE_CEILING,
    DEFAULT_EARLY_VELOCITY_RATE,
    DEFAULT_NARRATIVE_TREND,
    DEFAULT_VELOCITY_TREND,
    get_learning_thresholds,
    record_prediction,
)

HIGH_PING_THRESHOLD = 5


def _normalize(value: Optional[float]) -> float:
    return float(value) if value is not None else 0.0


def _minutes_between(oldest, latest):
    if not oldest or not latest:
        return 1.0
    delta_minutes = (latest - oldest).total_seconds() / 60.0
    return max(delta_minutes, 1.0)


def _datetime_from_iso(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _predict_drop_point_internal(
    drop_point_id: str,
    db: Session,
    record_learning: bool = True,
) -> dict:
    from apps.analytics.public import list_score_snapshots

    snapshots = list_score_snapshots(drop_point_id, db, limit=5)
    if len(snapshots) < 3:
        return {"drop_point_id": drop_point_id, "status": "insufficient_data"}

    latest = snapshots[0]
    oldest = snapshots[-1]
    delta_minutes = _minutes_between(
        _datetime_from_iso(oldest.get("timestamp")),
        _datetime_from_iso(latest.get("timestamp")),
    )
    velocity_trend = (
        (_normalize(latest.get("velocity_score")) - _normalize(oldest.get("velocity_score")))
        / delta_minutes
    )
    narrative_trend = (
        (_normalize(latest.get("narrative_score")) - _normalize(oldest.get("narrative_score")))
        / delta_minutes
    )

    # `ensure_learning_thresholds` is declared `-> dict[str, Any]` and returns
    # `row_to_dict(...)`. This read used attribute access, so every call raised
    # AttributeError and took out /predictions/{id} and /narrative/*. `adjust_thresholds`
    # in learning_engine reads the same contract by subscript and was always correct —
    # one consumer was updated when the boundary went dict-shaped and the other was not.
    # Defaults mirror the ones passed into ensure_learning_thresholds, so a row missing a
    # column degrades to the documented default instead of a KeyError.
    thresholds = get_learning_thresholds(db) or {}
    velocity_threshold = thresholds.get("velocity_trend", DEFAULT_VELOCITY_TREND)
    narrative_threshold = thresholds.get("narrative_trend", DEFAULT_NARRATIVE_TREND)
    early_velocity_rate = thresholds.get("early_velocity_rate", DEFAULT_EARLY_VELOCITY_RATE)
    early_narrative_ceiling = thresholds.get(
        "early_narrative_ceiling", DEFAULT_EARLY_NARRATIVE_CEILING
    )

    delta_payload = compute_deltas(drop_point_id, db)
    velocity_rate = 0.0
    if isinstance(delta_payload, dict) and "rates" in delta_payload:
        velocity_rate = delta_payload["rates"].get("velocity_rate", 0.0)

    total_pings = (
        db.query(func.count(PingDB.id))
        .filter(PingDB.drop_point_id == drop_point_id)
        .scalar()
        or 0
    )
    latest_narrative = _normalize(latest.get("narrative_score"))

    prediction = "stable"
    if (
        velocity_trend > velocity_threshold
        and narrative_trend > narrative_threshold
    ):
        prediction = "likely_to_spike"
    elif (
        velocity_rate > early_velocity_rate
        and latest_narrative <= early_narrative_ceiling
    ):
        prediction = "emerging_signal"
    elif velocity_trend < 0 and total_pings >= HIGH_PING_THRESHOLD:
        prediction = "plateauing"
    elif velocity_rate < 0:
        prediction = "declining"

    confidence = min(1.0, len(snapshots) / 5.0)

    if record_learning:
        record_prediction(
            db,
            drop_point_id,
            prediction,
            _normalize(latest.get("velocity_score")),
            latest_narrative,
        )

    return {
        "drop_point_id": drop_point_id,
        "prediction": prediction,
        "confidence": round(confidence, 3),
        "velocity_trend": round(velocity_trend, 4),
        "narrative_trend": round(narrative_trend, 4),
        "velocity_rate": round(velocity_rate, 4),
        "latest_narrative_score": round(latest_narrative, 4),
    }


def predict_drop_point(
    drop_point_id: str,
    db: Session,
    record_learning: bool = True,
) -> dict:
    return call_with_engine_breaker(
        "prediction_engine",
        fallback={
            "drop_point_id": drop_point_id,
            "status": "circuit_open",
            "prediction": "circuit_open",
            "confidence": 0.0,
            "velocity_trend": 0.0,
            "narrative_trend": 0.0,
            "velocity_rate": 0.0,
            "latest_narrative_score": 0.0,
        },
        fn=lambda: _predict_drop_point_internal(
            drop_point_id,
            db,
            record_learning=record_learning,
        ),
    )


def scan_drop_point_predictions(db: Session, limit: int = 50) -> List[dict]:
    candidate_ids = drop_point_ids_with_history(db)
    predictions: List[dict] = []
    for drop_point_id in candidate_ids[:limit]:
        prediction = predict_drop_point(drop_point_id, db, record_learning=False)
        if prediction.get("status"):
            continue
        predictions.append(prediction)
    return predictions


def prediction_summary(db: Session, limit: int = 50) -> dict:
    predictions = scan_drop_point_predictions(db, limit=limit)
    summary = {
        "total_predicted_spikes": 0,
        "total_declining": 0,
        "total_emerging_signals": 0,
    }
    for prediction in predictions:
        if prediction["prediction"] == "likely_to_spike":
            summary["total_predicted_spikes"] += 1
        if prediction["prediction"] == "declining":
            summary["total_declining"] += 1
        if prediction["prediction"] == "emerging_signal":
            summary["total_emerging_signals"] += 1
    return summary
