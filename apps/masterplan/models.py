"""Masterplan app ORM models."""

from apps.masterplan.goal_state import GoalState
from apps.masterplan.goals import Goal
from apps.masterplan.masterplan import GenesisSessionDB, MasterPlan
from apps.masterplan.strategy_layer import PlanObjective, PlanPhase, PlanStrategy
from apps.masterplan.work_model import Work, WorkLink, WorkObjective, WorkProposalDismissal, WorkRevision

__all__ = [
    "GenesisSessionDB",
    "Goal",
    "GoalState",
    "MasterPlan",
    "PlanObjective",
    "PlanPhase",
    "PlanStrategy",
    "Work",
    "WorkLink",
    "WorkObjective",
    "WorkProposalDismissal",
    "WorkRevision",
]


def register_models() -> None:
    return None
