"""What a published piece answers, stored once per version of its text (ARTICLE_ANSWERS_SPEC §2, phase B2).

The SEO tool asks the same question of a draft on a button (phase A). Here the answer is kept for a
piece the owner has published, keyed by the text it was read from (`content_hash`), so a piece whose
text changes is read again and an unchanged one never is.

**New pieces only** (decision 3, owner, 2026-11-08): the migration marked every stored piece
``skipped``. An older piece gets answers when the owner asks.
"""

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID

from AINDY.db.database import Base


class PieceAnswersDB(Base):
    __tablename__ = "piece_answers"
    __table_args__ = (
        UniqueConstraint("drop_point_id", "content_hash", name="uq_piece_answers_drop_point_hash"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    drop_point_id = Column(String, nullable=False, index=True)
    # The drop point's content_hash when it was read. A newer hash means the answers are stale.
    content_hash = Column(String(64), nullable=False)
    answers = Column(JSON, nullable=False)
    raised = Column(JSON, nullable=False)
    answer_range = Column(JSON, nullable=False)
    model = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
