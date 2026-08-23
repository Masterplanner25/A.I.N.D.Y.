"""Commercial intake service — lead -> client -> order lineage.

Phase 1 of the Freelancing evolution (`docs/domains/FREELANCING_SYSTEM.md`). This
service owns the commercial entry path: it resolves/creates `ClientAccount`
records, links orders to clients, converts discovered leads into client orders
without re-entry of core context, and exposes client lineage for querying
commercial state.

The freelance layer orchestrates here; it reads leads through the search
domain's public surface (`apps.search.public.get_lead_by_id`) rather than
reaching into search internals.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from apps.freelance.models.client_account import ClientAccount
from apps.freelance.models.freelance import FreelanceOrder

logger = logging.getLogger(__name__)


def _normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def _user_uuid(user_id: Any) -> uuid.UUID | None:
    if not user_id:
        return None
    return uuid.UUID(str(user_id))


def get_or_create_client(
    db: Session,
    user_id: Any,
    *,
    email: str,
    name: str | None = None,
    company: str | None = None,
    source: str = "manual",
    lead_id: int | None = None,
) -> ClientAccount:
    """Return the client for ``(user_id, email)``, creating it if absent.

    On an existing client, only *fills in* missing name/company/lead_id — it
    never downgrades a richer origin (e.g. a "leadgen" client is not reset to
    "order" the next time an order is placed for the same email).
    """
    normalized_email = _normalize_email(email)
    if not normalized_email:
        raise ValueError("client email is required to resolve a client account")
    user_uuid = _user_uuid(user_id)

    client = (
        db.query(ClientAccount)
        .filter(ClientAccount.user_id == user_uuid, ClientAccount.email == normalized_email)
        .first()
    )
    if client:
        changed = False
        if name and not client.name:
            client.name = name
            changed = True
        if company and not client.company:
            client.company = company
            changed = True
        if lead_id is not None and client.lead_id is None:
            client.lead_id = int(lead_id)
            if client.source in (None, "manual", "order"):
                client.source = "leadgen"
            changed = True
        if changed:
            db.add(client)
            db.flush()
        return client

    client = ClientAccount(
        user_id=user_uuid,
        email=normalized_email,
        name=name,
        company=company,
        source=source,
        lead_id=int(lead_id) if lead_id is not None else None,
    )
    db.add(client)
    db.flush()
    return client


def link_order_to_client(db: Session, order: FreelanceOrder, *, source: str = "order") -> ClientAccount | None:
    """Resolve and attach a client to ``order`` from its email/name. Idempotent."""
    if order is None or not order.client_email:
        return None
    client = get_or_create_client(
        db,
        order.user_id,
        email=order.client_email,
        name=order.client_name,
        source=source,
    )
    if order.client_id != client.id:
        order.client_id = client.id
        db.add(order)
        db.flush()
    return client


def _client_stats(db: Session, client_id: int, user_uuid: uuid.UUID | None) -> dict[str, Any]:
    query = db.query(FreelanceOrder).filter(FreelanceOrder.client_id == client_id)
    if user_uuid is not None:
        query = query.filter(FreelanceOrder.user_id == user_uuid)
    orders = query.all()
    delivered = [o for o in orders if str(o.status or "").lower() in {"delivered", "completed"}]
    return {
        "order_count": len(orders),
        "delivered_count": len(delivered),
        "total_order_value": round(sum(float(o.price or 0.0) for o in orders), 2),
    }


def _client_to_dict(client: ClientAccount) -> dict[str, Any]:
    return {
        "id": client.id,
        "email": client.email,
        "name": client.name,
        "company": client.company,
        "source": client.source,
        "lead_id": client.lead_id,
        "created_at": client.created_at.isoformat() if client.created_at else None,
    }


def list_clients(db: Session, user_id: Any) -> list[dict[str, Any]]:
    user_uuid = _user_uuid(user_id)
    clients = (
        db.query(ClientAccount)
        .filter(ClientAccount.user_id == user_uuid)
        .order_by(ClientAccount.created_at.desc())
        .all()
    )
    result: list[dict[str, Any]] = []
    for client in clients:
        entry = _client_to_dict(client)
        entry.update(_client_stats(db, client.id, user_uuid))
        result.append(entry)
    return result


def get_client_lineage(db: Session, user_id: Any, client_id: int) -> dict[str, Any]:
    """Return a client plus its full order lineage (and originating lead ref)."""
    user_uuid = _user_uuid(user_id)
    client = (
        db.query(ClientAccount)
        .filter(ClientAccount.id == int(client_id), ClientAccount.user_id == user_uuid)
        .first()
    )
    if not client:
        raise ValueError(f"client {client_id} not found")

    orders = (
        db.query(FreelanceOrder)
        .filter(FreelanceOrder.client_id == client.id, FreelanceOrder.user_id == user_uuid)
        .order_by(FreelanceOrder.created_at.desc())
        .all()
    )
    order_rows = [
        {
            "id": o.id,
            "service_type": o.service_type,
            "status": o.status,
            "price": float(o.price or 0.0),
            "delivery_status": o.delivery_status,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }
        for o in orders
    ]

    entry = _client_to_dict(client)
    entry.update(_client_stats(db, client.id, user_uuid))
    entry["orders"] = order_rows
    return entry


def convert_lead_to_order(
    db: Session,
    user_id: Any,
    *,
    lead_id: int,
    client_email: str,
    service_type: str,
    client_name: str | None = None,
    price: float = 0.0,
    project_details: str | None = None,
    delivery_type: str = "manual",
    delivery_config: dict | None = None,
    auto_generate_delivery: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Convert a discovered lead into a client + freelance order.

    Carries the lead's company/url/context/reasoning into the order's project
    details so commercial context is not re-entered, records the originating
    ``lead_id`` on the client, and returns the linked client + order.
    """
    from apps.search.public import get_lead_by_id

    lead = get_lead_by_id(db, lead_id, user_id)
    if lead is None:
        raise ValueError(f"lead {lead_id} not found")

    company = getattr(lead, "company", None)
    client = get_or_create_client(
        db,
        user_id,
        email=client_email,
        name=client_name or company,
        company=company,
        source="leadgen",
        lead_id=int(getattr(lead, "id", lead_id)),
    )

    if not project_details:
        parts = [f"Lead-sourced engagement for {company or 'prospect'}."]
        if getattr(lead, "url", None):
            parts.append(f"URL: {lead.url}")
        if getattr(lead, "context", None):
            parts.append(f"Context: {lead.context}")
        if getattr(lead, "reasoning", None):
            parts.append(f"Lead reasoning: {lead.reasoning}")
        project_details = "\n".join(parts)

    # Build the order via the existing creation path so all order-side behavior
    # (idempotency, memory capture, delivery wiring) is reused unchanged.
    from apps.freelance.schemas.freelance import FreelanceOrderCreate
    from apps.freelance.services import freelance_service

    order_create = FreelanceOrderCreate(
        client_name=client_name or company or client_email,
        client_email=client_email,
        service_type=service_type,
        project_details=project_details,
        price=price,
        delivery_type=delivery_type,
        delivery_config=delivery_config,
        auto_generate_delivery=auto_generate_delivery,
    )
    created = freelance_service.create_order(
        db,
        order_create,
        user_id=str(user_id) if user_id else None,
        idempotency_key=idempotency_key,
        return_created=False,
    )

    # Ensure the order is attributed to the lead-sourced client even if the
    # create path resolved/created the account under a different origin.
    if created.client_id != client.id:
        created.client_id = client.id
        db.add(created)
        db.flush()

    return {"client": client, "order": created, "lead_id": int(getattr(lead, "id", lead_id))}


def list_actioned_leads(db: Session, user_id: Any, limit: int = 50) -> list[dict[str, Any]]:
    """Leads the Search Execution Layer has drafted outreach for, ready to convert.

    Search owns the actioned leads; freelance consumes them through the search public
    surface (``apps.search.public.list_actioned_leads``) rather than reaching into
    search internals. Returns a compact, conversion-ready view.
    """
    from apps.search.public import list_actioned_leads as _search_list_actioned_leads

    actions = _search_list_actioned_leads(db, user_id, limit=limit)
    return [
        {
            "action_id": action.id,
            "lead_id": action.lead_id,
            "company": action.company,
            "url": action.url,
            "status": action.status,
            "channel": action.channel,
            "draft_subject": action.draft_subject,
            "created_at": action.created_at.isoformat() if action.created_at else None,
        }
        for action in actions
    ]


def convert_actioned_lead(
    db: Session,
    user_id: Any,
    *,
    action_id: int,
    client_email: str,
    service_type: str,
    client_name: str | None = None,
    price: float = 0.0,
    project_details: str | None = None,
    delivery_type: str = "manual",
    delivery_config: dict | None = None,
    auto_generate_delivery: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Convert a Search-actioned lead into a client + order.

    Resolves the ``LeadAction`` (search public surface) to its originating lead, then
    reuses ``convert_lead_to_order`` so the full lead -> client -> order lineage — and
    the ServicePrice default when no price is supplied — applies unchanged. This is
    the seam that completes the lead -> outreach -> client -> priced-order chain.
    """
    from apps.search.public import get_lead_action

    action = get_lead_action(db, action_id, user_id)
    if action is None:
        raise ValueError(f"lead action {action_id} not found")
    if action.lead_id is None:
        raise ValueError(f"lead action {action_id} has no linked lead to convert")

    result = convert_lead_to_order(
        db,
        user_id,
        lead_id=action.lead_id,
        client_email=client_email,
        service_type=service_type,
        client_name=client_name or action.company,
        price=price,
        project_details=project_details,
        delivery_type=delivery_type,
        delivery_config=delivery_config,
        auto_generate_delivery=auto_generate_delivery,
        idempotency_key=idempotency_key,
    )
    result["action_id"] = action_id
    return result
