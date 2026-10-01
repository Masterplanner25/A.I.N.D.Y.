"""Masterplan app ORM models."""

from apps.masterplan.goal_state import GoalState
from apps.masterplan.goals import Goal
from apps.masterplan.masterplan import GenesisSessionDB, MasterPlan
from apps.masterplan.strategy_layer import PlanObjective, PlanPhase, PlanStrategy
from apps.masterplan.work_model import (
    ResolutionAnswer,
    ResolutionRun,
    Work,
    WorkDraft,
    WorkLink,
    WorkObjective,
    WorkPresence,
    WorkProposalDismissal,
    WorkRevision,
)
from apps.masterplan.market_model import (
    MarketEntity,
    MarketEvidence,
    MarketProposal,
    MarketRevision,
    MarketSegment,
    SegmentWork,
)

__all__ = [
    "GenesisSessionDB",
    "Goal",
    "GoalState",
    "MarketEntity",
    "MarketEvidence",
    "MarketProposal",
    "MarketRevision",
    "MarketSegment",
    "MasterPlan",
    "PlanObjective",
    "PlanPhase",
    "PlanStrategy",
    "ResolutionAnswer",
    "ResolutionRun",
    "SegmentWork",
    "Work",
    "WorkDraft",
    "WorkLink",
    "WorkObjective",
    "WorkPresence",
    "WorkProposalDismissal",
    "WorkRevision",
]


def register_models() -> None:
    return None
