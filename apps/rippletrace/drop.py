from sqlalchemy import Column, String, DateTime, Text, Float, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from AINDY.db.database import Base


class DropPointDB(Base):
    __tablename__ = "drop_points"
    id = Column(String, primary_key=True, index=True)
    title = Column(String)
    platform = Column(String)
    url = Column(String, nullable=True)
    date_dropped = Column(DateTime)
    core_themes = Column(Text)
    tagged_entities = Column(Text)
    intent = Column(String)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    narrative_score = Column(Float, nullable=True)
    velocity_score = Column(Float, nullable=True)
    spread_score = Column(Float, nullable=True)
    # Last time the web was searched for echoes of this drop point. Separate from the
    # score columns because "we looked and found nothing" and "we never looked" are
    # different states, and only the second is worth spending another search on.
    mentions_checked_at = Column(DateTime(timezone=True), nullable=True)


class PingDB(Base):
    __tablename__ = "pings"
    id = Column(String, primary_key=True, index=True)
    drop_point_id = Column(String, ForeignKey("drop_points.id"))
    ping_type = Column(String)
    source_platform = Column(String)
    date_detected = Column(DateTime)
    connection_summary = Column(Text, nullable=True)
    external_url = Column(String, nullable=True)
    reaction_notes = Column(Text, nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    strength = Column(Float, default=1.0, nullable=False)
    connection_type = Column(String, default="direct", nullable=False)

    # ★ Whether this page was checked and actually cites the drop point
    # (RIPPLE-PINGS-NOT-ECHOES-1). Detection's search provider is an answer engine: it returns
    # the sources it used to answer, which are topically related by construction and almost
    # never the piece searched for. Measured 2026-09-07: 1 of 256 pings pointed at a URL
    # plausibly connected to the author.
    #
    #   verified    — the page was fetched and contains the drop point's URL or title
    #   unverified  — it could not be fetched, or predates this column
    #
    # Only `verified` pings score. `unverified` is deliberately not "assume no": "we looked and
    # it does not cite you" and "we could not look" are different answers, and publishers who
    # refuse scripted requests (401/403/405/406/429/451) produce the second constantly.
    #
    # There is no `rejected` value in the table. A candidate that demonstrably fails
    # verification is never written — a page that does not cite you is not a ripple.
    verification = Column(String(16), default="unverified", nullable=False, index=True)
    verification_note = Column(Text, nullable=True)
