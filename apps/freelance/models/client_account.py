"""Commercial client/account entity for the freelance domain.

Phase 1 of the Freelancing evolution (`docs/domains/FREELANCING_SYSTEM.md`): give
the freelance layer a first-class client/account record so leads, clients, and
orders form one ``lead -> client -> order`` lineage instead of isolated rows.

A ``ClientAccount`` is owned by a freelancer ``user_id`` and is identified by the
client's email (one client per email per freelancer). When a client originates
from a leadgen result, ``lead_id`` records the originating lead by id — a soft
reference, not a hard FK, so the freelance domain does not couple its schema to
the search domain's ``leadgen_results`` table.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID

from AINDY.db.database import Base


class ClientAccount(Base):
    __tablename__ = "freelance_client_accounts"
    __table_args__ = (
        Index(
            "ux_freelance_client_accounts_user_email",
            "user_id",
            "email",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    email = Column(String, nullable=False, index=True)
    name = Column(String, nullable=True)
    company = Column(String, nullable=True)
    # Origin of the account: "manual" | "order" | "leadgen".
    source = Column(String, nullable=True, default="manual")
    # Soft reference to the originating leadgen_results.id (no cross-app FK).
    lead_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<ClientAccount(id={self.id}, email='{self.email}', source='{self.source}')>"
