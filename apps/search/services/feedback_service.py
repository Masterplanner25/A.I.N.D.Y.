"""
Search result feedback — capture + aggregate (Search v4 §8).

Captures whether a result actually worked, from both signal families:
  * implicit — ``click`` (+0.3), ``dwell`` (+0.5), ``convert`` (+1.0), ``dismiss`` (-0.3)
  * explicit — ``thumbs_up`` (+1.0), ``thumbs_down`` (-1.0)

Feedback is deduped per (user, query, result_ref, signal) — a repeated click counts
once — and an explicit vote replaces the opposing one (latest opinion wins). The
aggregate (``get_result_outcome_weights``) sums per result_ref for a query, blending
implicit + explicit — the outcome signal ``search_score`` never provided. A later PR
consumes it to re-weight ranking (flag-gated).
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from AINDY.platform_layer.user_ids import parse_user_id
from apps.search.models.result_feedback import SearchResultFeedback

logger = logging.getLogger(__name__)

# Per-signal weights (recorded on each row for auditability).
SIGNAL_WEIGHTS: dict[str, float] = {
    # implicit
    "click": 0.3,
    "dwell": 0.5,
    "convert": 1.0,
    "dismiss": -0.3,
    # explicit
    "thumbs_up": 1.0,
    "thumbs_down": -1.0,
}
EXPLICIT_SIGNALS = {"thumbs_up", "thumbs_down"}


def _kind(signal: str) -> str:
    return "explicit" if signal in EXPLICIT_SIGNALS else "implicit"


def _normalized_query(query: str) -> str:
    return (query or "").strip()


def record_feedback(
    db: Session,
    *,
    user_id,
    query: str,
    result_ref: str,
    signal: str,
    history_id: str | None = None,
) -> dict:
    """Record one feedback event. Idempotent per (user, query, result_ref, signal)."""
    signal = (signal or "").strip().lower()
    if signal not in SIGNAL_WEIGHTS:
        raise ValueError(f"unknown feedback signal {signal!r}")
    if not result_ref:
        raise ValueError("result_ref is required")
    uid = parse_user_id(user_id)
    if uid is None:
        raise ValueError("a valid user_id is required")

    # Keep a history_id only if it is the caller's own search: it was stored as given, so a row
    # could point at another user's search history.
    if history_id:
        from apps.search.services.search_service import get_search_history_item

        if get_search_history_item(db, str(uid), history_id) is None:
            history_id = None

    nq = _normalized_query(query)
    kind = _kind(signal)
    weight = SIGNAL_WEIGHTS[signal]

    # Explicit: the latest vote wins — remove the opposing thumbs for this result/query.
    if signal in EXPLICIT_SIGNALS:
        opposite = "thumbs_down" if signal == "thumbs_up" else "thumbs_up"
        db.query(SearchResultFeedback).filter(
            SearchResultFeedback.user_id == uid,
            SearchResultFeedback.query == nq,
            SearchResultFeedback.result_ref == result_ref,
            SearchResultFeedback.signal == opposite,
        ).delete(synchronize_session=False)

    # Upsert per (user, query, result_ref, signal) — implicit dedup + recency bump.
    row = (
        db.query(SearchResultFeedback)
        .filter(
            SearchResultFeedback.user_id == uid,
            SearchResultFeedback.query == nq,
            SearchResultFeedback.result_ref == result_ref,
            SearchResultFeedback.signal == signal,
        )
        .first()
    )
    created = False
    if row is None:
        row = SearchResultFeedback(
            user_id=uid, query=nq, history_id=history_id,
            result_ref=result_ref, kind=kind, signal=signal, weight=weight,
        )
        db.add(row)
        created = True
    else:
        if history_id:
            row.history_id = history_id
        row.weight = weight  # keep weight current if the signal->weight map changes

    db.commit()
    return {
        "recorded": True,
        "created": created,
        "result_ref": result_ref,
        "signal": signal,
        "kind": kind,
        "weight": weight,
    }


def get_result_outcome_weights(db: Session, user_id, query: str) -> dict[str, float]:
    """Per-result outcome weight for a query — implicit + explicit summed. {} if none."""
    uid = parse_user_id(user_id)
    if uid is None:
        return {}
    nq = _normalized_query(query)
    rows = (
        db.query(SearchResultFeedback)
        .filter(SearchResultFeedback.user_id == uid, SearchResultFeedback.query == nq)
        .all()
    )
    weights: dict[str, float] = {}
    for row in rows:
        weights[row.result_ref] = round(weights.get(row.result_ref, 0.0) + float(row.weight or 0.0), 3)
    return weights
