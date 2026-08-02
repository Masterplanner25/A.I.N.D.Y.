"""Centralized support-state snapshot (Infinity Support System — Step 1).

The Infinity orchestrator previously assembled its support inputs (memory, KPI
metrics, memory signals, system state, goals, task graph, social signals) ad hoc
inside `execute`. This service gathers them once into a single normalized
`SupportState` snapshot so Infinity receives one consistent state object instead
of re-deriving it inline.

Gathering fidelity matches the prior orchestrator behavior exactly: memory /
metrics / memory_signals propagate on failure (no swallow), while system_state /
goals / task_graph / social_signals / support_metrics fall back to safe defaults.
Inputs are pulled through the existing `dependency_adapter` syscall seam + the
`goals.rank` job — no runtime edits.

`support_metrics` is the runtime observability + execution rollup (Support System
Steps 3 & 4) fetched via `sys.v1.observability.support_metrics` (aindy-runtime
>=1.6.0); it degrades to `{}` on an older runtime that lacks the syscall.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from AINDY.platform_layer.registry import get_job

from apps.analytics.services.integration import dependency_adapter

logger = logging.getLogger(__name__)


@dataclass
class SupportState:
    """One normalized snapshot of the Infinity support inputs."""

    user_id: str
    memory: Any
    metrics: Any
    memory_signals: list
    system_state: dict
    goals: list
    task_graph: dict
    social_signals: list
    support_metrics: dict = field(default_factory=dict)
    search_signals: list = field(default_factory=list)
    freelance_signals: list = field(default_factory=list)
    ripple_signals: list = field(default_factory=list)

    @property
    def loop_context(self) -> dict[str, Any]:
        """The loop_context dict the orchestrator/loop consume."""
        return {
            "user_id": self.user_id,
            "memory": self.memory,
            "metrics": self.metrics,
            "memory_signals": self.memory_signals,
            "system_state": self.system_state,
            "goals": self.goals,
            "task_graph": self.task_graph,
            "social_signals": self.social_signals,
            "search_signals": self.search_signals,
            "freelance_signals": self.freelance_signals,
            "ripple_signals": self.ripple_signals,
            "support_metrics": self.support_metrics,
        }

    def summary(self) -> dict[str, Any]:
        """Compact counts for the `loop.started` observability event."""
        return {
            "user_id": self.user_id,
            "memory_count": len(self.memory or []),
            "memory_signal_count": len(self.memory_signals or []),
            "health_status": (self.system_state or {}).get("health_status"),
            "goal_count": len(self.goals or []),
            "ready_task_count": len((self.task_graph or {}).get("ready") or []),
            "blocked_task_count": len((self.task_graph or {}).get("blocked") or []),
            "social_signal_count": len(self.social_signals or []),
            "search_signal_count": len(self.search_signals or []),
            "freelance_signal_count": len(self.freelance_signals or []),
            "ripple_signal_count": len(self.ripple_signals or []),
            "has_metrics": self.metrics is not None,
            "platform_health_status": (
                (self.support_metrics or {}).get("observability") or {}
            ).get("platform_health_status"),
            "infinity_event_total": (
                (self.support_metrics or {}).get("infinity_events") or {}
            ).get("total"),
        }


def gather_support_state(db, user_id, trigger_event) -> SupportState:
    """Assemble the support-state snapshot for one Infinity run."""
    memory_nodes = dependency_adapter.fetch_recent_memory(user_id, db, context="infinity_loop")
    metrics = dependency_adapter.fetch_user_metrics(user_id, db)
    memory_signals = dependency_adapter.fetch_memory_signals(
        user_id=user_id,
        trigger_event=str(trigger_event or "manual"),
        db=db,
    )

    try:
        system_state = dependency_adapter.fetch_system_state(db)
    except Exception as exc:
        logger.warning("[SupportState] system state lookup failed for %s: %s", user_id, exc)
        system_state = {}

    rank_goals = get_job("goals.rank")
    try:
        goals = rank_goals(db, user_id, system_state=system_state) if callable(rank_goals) else []
    except Exception as exc:
        logger.warning("[SupportState] goal ranking failed for %s: %s", user_id, exc)
        goals = []

    try:
        task_graph = dependency_adapter.fetch_task_graph_context(db, user_id)
    except Exception as exc:
        logger.warning("[SupportState] task graph lookup failed for %s: %s", user_id, exc)
        task_graph = {}

    try:
        social_signals = dependency_adapter.fetch_social_performance_signals(user_id=str(user_id))
    except Exception as exc:
        logger.warning("[SupportState] social signal lookup failed for %s: %s", user_id, exc)
        social_signals = []

    try:
        search_signals = dependency_adapter.fetch_search_performance_signals(user_id=str(user_id))
    except Exception as exc:
        logger.warning("[SupportState] search signal lookup failed for %s: %s", user_id, exc)
        search_signals = []

    try:
        freelance_signals = dependency_adapter.fetch_freelance_performance_signals(user_id=str(user_id))
    except Exception as exc:
        logger.warning("[SupportState] freelance signal lookup failed for %s: %s", user_id, exc)
        freelance_signals = []

    try:
        ripple_signals = dependency_adapter.fetch_ripple_performance_signals(
            user_id=str(user_id), db=db
        )
    except Exception as exc:
        logger.warning("[SupportState] ripple signal lookup failed for %s: %s", user_id, exc)
        ripple_signals = []

    try:
        support_metrics = dependency_adapter.fetch_observability_support_metrics(
            user_id=str(user_id), db=db
        )
    except Exception as exc:
        logger.warning("[SupportState] support metrics lookup failed for %s: %s", user_id, exc)
        support_metrics = {}

    return SupportState(
        user_id=str(user_id),
        memory=memory_nodes,
        metrics=metrics,
        memory_signals=memory_signals,
        system_state=system_state,
        goals=goals,
        task_graph=task_graph,
        social_signals=social_signals,
        support_metrics=support_metrics,
        search_signals=search_signals,
        freelance_signals=freelance_signals,
        ripple_signals=ripple_signals,
    )
