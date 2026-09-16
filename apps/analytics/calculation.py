from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from AINDY.db.database import Base


class CalculationResult(Base):
    """SQLAlchemy model for storing calculated metric results."""

    __tablename__ = "calculation_results"

    id = Column(Integer, primary_key=True, index=True)
    metric_name = Column(String, index=True)
    result_value = Column(Float)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=func.now(), server_default=func.now())

    
