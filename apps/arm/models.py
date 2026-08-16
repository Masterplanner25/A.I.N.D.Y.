import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Float, Text, DateTime, Boolean, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from AINDY.db.database import Base


# -------------------------------------------------------
#  AnalysisResult — full audit record for each ARM analysis
# -------------------------------------------------------
class AnalysisResult(Base):
    """
    Stores the complete record of each ARM reasoning analysis session.
    Supports audit trails, Infinity Algorithm metrics, and replay.
    """

    __tablename__ = "analysis_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    file_path = Column(String)
    file_type = Column(String)
    analysis_type = Column(String, default="analyze")   # analyze | generate | audit
    prompt_used = Column(Text)
    model_used = Column(String)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    execution_seconds = Column(Float)
    result_summary = Column(Text)
    result_full = Column(Text)
    task_priority = Column(Float)                        # Infinity Algorithm TP score
    status = Column(String, default="success")           # success | failed | blocked
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationship — one analysis can spawn many code generations
    generations = relationship(
        "CodeGeneration", back_populates="analysis", cascade="all, delete-orphan"
    )


# -------------------------------------------------------
#  CodeGeneration — record for each code gen / refactor
# -------------------------------------------------------
class CodeGeneration(Base):
    """
    Stores every code generation or refactoring operation performed by ARM.
    Links back to the analysis session that preceded it (optional).
    """

    __tablename__ = "code_generations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    analysis_id = Column(
        UUID(as_uuid=True),
        ForeignKey("analysis_results.id", ondelete="SET NULL"),
        nullable=True,
    )
    generation_type = Column(String, default="generate")  # refactor | generate | explain
    original_code = Column(Text)
    generated_code = Column(Text)
    language = Column(String)
    model_used = Column(String)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    execution_seconds = Column(Float)
    quality_notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationship back to analysis
    analysis = relationship("AnalysisResult", back_populates="generations")


# -------------------------------------------------------
#  Removed 2026-08-16: ARMRun, ARMLog, ARMConfig
# -------------------------------------------------------
# Three models inherited from the original DeepSeek Analyzer port and never
# wired to anything: zero non-model references across apps/, zero rows in every
# environment checked. ARMRun/ARMLog duplicated what `analysis_results` and the
# runtime's own observability already record; ARMConfig (table `arm_configs`)
# was a dead twin of ArmConfig (table `arm_config`) below — the live, per-user
# one used by arm_config_dao and bootstrap. The near-identical class names are
# exactly why the dead one survived this long.
#
# The TABLES are intentionally left in place. MIGRATION_POLICY.md is
# additive-only ("removing a column requires coordinating model code, migration
# and all query sites simultaneously — additive changes reduce blast radius"),
# and three empty tables cost nothing. Drop them in a deliberate cleanup if ever.


class ArmConfig(Base):
    __tablename__ = "arm_config"

    id = Column(String(36), primary_key=True, default="default")
    model = Column(String(128), nullable=False, default="gpt-4o")
    analysis_model = Column(String(128), nullable=False, default="gpt-4o")
    generation_model = Column(String(128), nullable=False, default="gpt-4o")
    temperature = Column(Float, nullable=False, default=0.2)
    generation_temperature = Column(Float, nullable=False, default=0.4)
    max_chunk_tokens = Column(Integer, nullable=False, default=4000)
    max_output_tokens = Column(Integer, nullable=False, default=2000)
    retry_limit = Column(Integer, nullable=False, default=3)
    retry_delay_seconds = Column(Integer, nullable=False, default=2)
    max_file_size_bytes = Column(Integer, nullable=False, default=100_000)
    allowed_extensions = Column(JSON, nullable=False, default=list)
    task_complexity_default = Column(Integer, nullable=False, default=3)
    task_urgency_default = Column(Integer, nullable=False, default=5)
    resource_cost_default = Column(Integer, nullable=False, default=2)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


# -------------------------------------------------------
#  ArmAutoTuneLog — audit trail for self-tuning config changes
# -------------------------------------------------------
class ArmAutoTuneLog(Base):
    """
    One row per auto-tune run: what the guarded consumer applied from the
    suggestion engine's ``auto_apply_safe`` set, what it skipped and why, plus a
    full snapshot of the config *before* the change so a run can be reverted
    exactly. This is the closed half of ARM's Reflect -> Adjust loop — the layer
    that actually consumes ``auto_apply_safe`` instead of only recommending it.

    ``user_id`` mirrors the ``arm_config`` row key (a user UUID string, or the
    ``"default"`` singleton), not a ``users.id`` FK — config is keyed the same way.
    """

    __tablename__ = "arm_autotune_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(36), nullable=False, index=True)     # arm_config key ('default' | user uuid)
    trigger = Column(String(16), nullable=False, default="manual")  # manual | agent | scheduler
    applied = Column(JSON, nullable=False, default=list)         # [{param, old, new, metric, reason, risk}]
    skipped = Column(JSON, nullable=False, default=list)         # [{param, suggested, reason}]
    prior_config = Column(JSON, nullable=False, default=dict)    # snapshot before apply — revert target
    resulting_config = Column(JSON, nullable=False, default=dict)  # snapshot after apply
    metrics_snapshot = Column(JSON, nullable=False, default=dict)
    reverted = Column(Boolean, nullable=False, default=False)
    reverted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # --- Learning close (Reflect -> Adjust -> LEARN) ---
    # After an observation window, the applied change is judged against its metrics_snapshot:
    # a degraded outcome is auto-reverted and its key enters the gate's penalty box; the
    # verdict biases future auto-tune decisions. NULL outcome = not yet evaluated (pending).
    outcome = Column(String(16), nullable=True, index=True)   # improved | degraded | neutral | NULL(pending)
    outcome_delta = Column(Float, nullable=True)              # health delta (now - snapshot) at evaluation
    outcome_snapshot = Column(JSON, nullable=True)            # metrics at evaluation time (audit)
    evaluated_at = Column(DateTime(timezone=True), nullable=True)


def register_models() -> None:
    _ = (AnalysisResult, CodeGeneration, ArmConfig, ArmAutoTuneLog)
    return None
