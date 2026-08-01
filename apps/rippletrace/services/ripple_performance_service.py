"""RippleTrace's contribution to the Infinity support loop, and to goal attainment.

Every other feeder domain answers "how is the work performing?" from its own vantage:
social from engagement, search from result quality, freelance from revenue. RippleTrace's
vantage is the only one that reports **reach beyond your own audience** — whether anything
you published was picked up somewhere else.

Signals follow the ``{type, reason, ...context}`` shape the loop already consumes from
social/search/freelance, so nothing downstream needs to learn a new format.

Two thresholds are used, and neither is invented here:

* ``SUCCESS_NARRATIVE_THRESHOLD`` is imported from ``strategy_engine`` — the bar the
  domain *already* uses to decide a drop point succeeded. Picking a second, different
  number for "this did well" would mean the loop and the strategy builder disagree about
  what success is.
* "No echo" is not a threshold at all. It requires ``mentions_checked_at`` to be set, so
  it reports *searched and found nothing* rather than *never looked* — those are
  different facts and only the first is a signal.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from apps.rippletrace.models import DropPointDB, PingDB, PlaybookDB
from apps.rippletrace.services.strategy_engine import SUCCESS_NARRATIVE_THRESHOLD

logger = logging.getLogger(__name__)

# Two platforms can be you plus one aggregator. Three is the point at which a piece has
# demonstrably travelled rather than merely been syndicated.
CROSS_PLATFORM_SPREAD_THRESHOLD = 3


def _as_uuid(user_id: Any) -> uuid.UUID | None:
    if not user_id:
        return None
    try:
        return uuid.UUID(str(user_id))
    except (TypeError, ValueError):
        return None


def _scoped(query, owner: uuid.UUID | None):
    return query.filter(DropPointDB.user_id == owner) if owner else query


def get_ripple_performance_signals(
    db: Session, *, user_id: str | None = None, limit: int = 3
) -> list[dict[str, Any]]:
    """Advisory signals about how published content is travelling.

    Returns at most ``limit`` signals, strongest first. An empty list is a valid answer
    and means "nothing worth saying" — it is not an error, and the loop treats a missing
    source and a quiet source identically.
    """
    owner = _as_uuid(user_id)
    signals: list[dict[str, Any]] = []

    try:
        best = (
            _scoped(
                db.query(DropPointDB).filter(
                    DropPointDB.narrative_score >= SUCCESS_NARRATIVE_THRESHOLD
                ),
                owner,
            )
            .order_by(DropPointDB.narrative_score.desc())
            .first()
        )
        if best is not None:
            signals.append(
                {
                    "type": "success",
                    "reason": "content_reached_beyond_own_audience",
                    "narrative_score": float(best.narrative_score or 0.0),
                    "spread_score": float(best.spread_score or 0.0),
                    "platform": best.platform,
                    "content": str(best.title or "")[:120],
                }
            )

        spread_count = (
            _scoped(
                db.query(func.count(DropPointDB.id)).filter(
                    DropPointDB.spread_score >= CROSS_PLATFORM_SPREAD_THRESHOLD
                ),
                owner,
            ).scalar()
            or 0
        )
        if spread_count >= 2:
            signals.append(
                {
                    "type": "pattern",
                    "reason": "repeating_cross_platform_spread",
                    "count": int(spread_count),
                    "min_platforms": CROSS_PLATFORM_SPREAD_THRESHOLD,
                }
            )

        # Published, searched, and nothing came back. Requires mentions_checked_at so a
        # never-searched drop point is never reported as a failure.
        silent = (
            _scoped(
                db.query(DropPointDB).filter(
                    DropPointDB.mentions_checked_at.isnot(None),
                    ~db.query(PingDB)
                    .filter(PingDB.drop_point_id == DropPointDB.id)
                    .exists(),
                ),
                owner,
            )
            .order_by(DropPointDB.mentions_checked_at.desc())
            .first()
        )
        if silent is not None:
            signals.append(
                {
                    "type": "failure",
                    "reason": "published_without_echo",
                    "narrative_score": 0.0,
                    "platform": silent.platform,
                    "content": str(silent.title or "")[:120],
                    "checked_at": silent.mentions_checked_at.isoformat()
                    if silent.mentions_checked_at
                    else None,
                }
            )
    except Exception as exc:
        # A degraded feeder must never break the loop; an empty signal list is the
        # documented "nothing to say" answer and every consumer already handles it.
        logger.warning("[rippletrace] performance signals unavailable: %s", exc)
        return []

    return signals[: max(0, int(limit))]


# Canonical goal-attainment unit -> how to count it.
GOAL_METRIC_UNITS = ("playbooks",)


def get_goal_metric(db: Session, *, unit: str, user_id: str | None = None) -> dict[str, Any]:
    """Cumulative counters for MasterPlan goal attainment.

    **Scope caveat, reported rather than hidden:** playbooks are global. ``PlaybookDB``
    has no ``user_id``, and the strategies they derive from are built by
    ``build_strategies`` from *all* successful drop points without an owner filter — the
    learning layer of this domain is global by construction. The response therefore
    carries ``scope: "global"`` so a caller can see that a multi-user deployment would be
    counting other people's playbooks. Correcting it means owning the strategy builder,
    which is a larger change than a goal resolver should make.
    """
    normalized = (unit or "").strip().lower()
    if normalized not in GOAL_METRIC_UNITS:
        return {"supported": False, "unit": normalized, "value": 0.0}

    try:
        count = db.query(func.count(PlaybookDB.id)).scalar() or 0
    except Exception as exc:
        logger.warning("[rippletrace] goal metric %r unavailable: %s", normalized, exc)
        return {"supported": False, "unit": normalized, "value": 0.0, "reason": "degraded"}

    return {
        "supported": True,
        "unit": normalized,
        "value": float(count),
        "scope": "global",
    }
