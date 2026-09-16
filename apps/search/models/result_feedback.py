"""
SEARCH RESULT FEEDBACK
------------------------------------
Part of: A.I.N.D.Y. – Search v4 (outcome→query weighting)

The outcome signal search never had. `search_score` is a *quality* composite; this
captures whether a result actually *worked* — both implicit (click / convert / dwell /
dismiss) and explicit (thumbs_up / thumbs_down), since not every user thumbs. Deduped
per (user, query, result_ref, signal); aggregated into a per-query outcome weight the
ranking can later consume (the §8 feedback loop).
"""

import uuid

from sqlalchemy import Column, String, Float, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from AINDY.db.database import Base


class SearchResultFeedback(Base):
    __tablename__ = "search_result_feedback"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)

    query = Column(String, nullable=False, index=True)        # normalized query the result was served for
    history_id = Column(String, nullable=True, index=True)    # SearchHistory.id (optional link)
    result_ref = Column(String, nullable=False, index=True)   # stable result key (url / lead id / research id)

    kind = Column(String(16), nullable=False)                 # implicit | explicit
    signal = Column(String(32), nullable=False)               # click|convert|dwell|dismiss|thumbs_up|thumbs_down
    weight = Column(Float, nullable=False, default=0.0, server_default="0")       # per-signal weight (recorded for auditability)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<SearchResultFeedback(result_ref='{self.result_ref}', signal='{self.signal}')>"
