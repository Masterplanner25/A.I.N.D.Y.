"""
FREELANCE PRICING MODELS
------------------------------------
Part of: A.I.N.D.Y. – Freelance Revenue Intelligence Loop

The review found freelance's "economic intelligence" asleep: feedback and revenue
were recorded but never fed back into pricing. These two tables close that loop —
the third and final instance of the compute->consume gap (after ARM auto-tune and
Search's Execution Layer), built on the same guarded-consumer template.

  * ``PricingRecommendation`` — the tracked, revertible artifact: what the loop
    recommended for a service type, the signals behind it, and a snapshot of the
    prior price so any applied run can be reverted exactly.
  * ``ServicePrice`` — the apply target: the studio's own default price per service
    type. Applying a recommendation writes here. It is an *internal default for
    future quotes* — it never changes existing orders and never charges a customer.
"""

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    JSON,
    ForeignKey,
    Index,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from AINDY.db.database import Base


class ServicePrice(Base):
    """The studio's current default price for a service type (per user).

    The apply target of the Revenue Intelligence Loop and a read seam for intake /
    quoting. One row per (user_id, service_type).
    """

    __tablename__ = "freelance_service_prices"
    __table_args__ = (
        Index(
            "ux_freelance_service_prices_user_service",
            "user_id",
            "service_type",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    service_type = Column(String, nullable=False, index=True)
    current_price = Column(Float, nullable=False, default=0.0, server_default="0")
    source = Column(String(16), nullable=False, default="manual", server_default="manual")  # manual | auto
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<ServicePrice(service_type='{self.service_type}', current_price={self.current_price})>"


class PricingRecommendation(Base):
    """One recommendation run for a service type — the audit + revert record."""

    __tablename__ = "freelance_pricing_recommendations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    service_type = Column(String, nullable=False, index=True)

    sample_size = Column(Integer, nullable=True)
    baseline_price = Column(Float, nullable=True)
    recommended_price = Column(Float, nullable=True)
    multiplier = Column(Float, nullable=True)
    direction = Column(String(16), nullable=True)   # increase | decrease | hold
    rationale = Column(String, nullable=True)
    signals = Column(JSON, nullable=True)           # snapshot of the stats behind it

    status = Column(String(16), nullable=False, default="recommended", index=True, server_default="recommended")  # recommended | applied | reverted
    prior_price = Column(Float, nullable=True)      # ServicePrice value before apply — revert target
    trigger = Column(String(16), nullable=False, default="manual", server_default="manual")  # manual | agent | scheduler

    applied_at = Column(DateTime(timezone=True), nullable=True)
    reverted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # --- Learning close: judge the change against REALIZED revenue, then learn ---
    # After an observation window the applied change is scored on expected revenue per lead
    # (baseline_price × acceptance_rate) vs its signals snapshot; a degraded change is
    # auto-reverted, and the verdict feeds a learned per-service revenue-direction bias.
    # NULL outcome = not yet evaluated (pending).
    outcome = Column(String(16), nullable=True, index=True)   # improved | degraded | neutral | NULL(pending)
    outcome_delta = Column(Float, nullable=True)              # Δ(revenue_score) now vs apply-time snapshot
    outcome_snapshot = Column(JSON, nullable=True)            # service stats at evaluation time (audit)
    evaluated_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<PricingRecommendation(service_type='{self.service_type}', status='{self.status}')>"
