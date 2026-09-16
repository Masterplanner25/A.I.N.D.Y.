"""
Infinity expectation model — the learned REFLECT calibrator (Phase 0, shadow).

The REFLECT step scores each decision's prediction accuracy against an *expected*
master-score that is, today, a hardcoded ``master + OFFSET[decision_type]``. These
two tables back a learned replacement that runs in SHADOW: it predicts the expected
score alongside the heuristic and logs both against the realized score, so we can
measure whether the learned model beats the heuristic before it ever drives anything.

Both tables are pooled (no ``user_id``) — the model is trained across users with the
KPI sub-scores as features, per the scope's pooled-first decision. Nothing here
touches canonical scoring; the shadow ledger is write-only observability.
"""
import uuid

from sqlalchemy import Column, String, Float, Integer, DateTime, JSON
from sqlalchemy.sql import func

from AINDY.db.database import Base


class InfinityExpectationModel(Base):
    """One fitted ridge model per ``decision_type`` (pooled across users)."""

    __tablename__ = "infinity_expectation_models"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    decision_type = Column(String, nullable=False, unique=True, index=True)

    coefficients = Column(JSON, nullable=False)     # [w1..wN, bias] — inspectable
    feature_keys = Column(JSON, nullable=False)     # ordered feature names for coefficients
    feature_version = Column(Integer, nullable=False, default=1, server_default="1")

    sample_size = Column(Integer, nullable=False, default=0, server_default="0")
    holdout_mae = Column(Float, nullable=True)      # MAE on the held-out split at fit time

    trained_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class InfinityExpectationPrediction(Base):
    """Shadow ledger: one row per matured decision.

    Written at REFLECT time when the realized score is known, so each row is a
    complete training example (features + actual) AND a soak datapoint
    (learned vs heuristic vs actual). ``learned_expected`` is null until a model
    for that decision_type has been trained.
    """

    __tablename__ = "infinity_expectation_predictions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    loop_adjustment_id = Column(String, nullable=True, index=True)
    decision_type = Column(String, nullable=False, index=True)

    features = Column(JSON, nullable=False)         # decision-time feature vector
    learned_expected = Column(Float, nullable=True)  # null when no model existed yet
    heuristic_expected = Column(Float, nullable=True)
    actual_score = Column(Float, nullable=True)      # realized master score

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
