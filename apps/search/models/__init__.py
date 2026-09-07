"""Search app models."""

from apps.search.models.leadgen_model import LeadGenResult
from apps.search.models.lead_action import LeadAction
from apps.search.models.research_results import ResearchResult
from apps.search.models.result_feedback import SearchResultFeedback
from apps.search.models.search_history import SearchHistory
from apps.search.models.seo_draft import SeoDraft, SeoDraftAnalysis

__all__ = [
    "LeadGenResult",
    "LeadAction",
    "ResearchResult",
    "SearchResultFeedback",
    "SearchHistory",
    "SeoDraft",
    "SeoDraftAnalysis",
]


def register_models() -> None:
    return None
