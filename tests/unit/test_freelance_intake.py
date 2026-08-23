"""Freelance Phase 1 — lead -> client -> order lineage.

Covers the commercial intake path added in the Freelancing evolution
(`docs/domains/FREELANCING_SYSTEM.md`, Phase 1): a `ClientAccount` entity, orders
auto-linked to clients on creation, lead->client->order conversion, and client
lineage queries. Runs on the SQLite app-profile harness.
"""

from __future__ import annotations

import uuid

import pytest

from apps.freelance.models.client_account import ClientAccount
from apps.freelance.models.freelance import FreelanceOrder
from apps.freelance.schemas.freelance import FreelanceOrderCreate
from apps.freelance.services import freelance_service, intake_service

pytestmark = pytest.mark.app_profile


def _order_create(**overrides) -> FreelanceOrderCreate:
    payload = {
        "client_name": "Acme Co",
        "client_email": "buyer@acme.io",
        "service_type": "landing page",
        "project_details": "build a landing page",
        "price": 1000.0,
    }
    payload.update(overrides)
    return FreelanceOrderCreate(**payload)


def test_create_order_links_a_client_account(db_session):
    db = db_session
    user_id = str(uuid.uuid4())

    order = freelance_service.create_order(db, _order_create(), user_id=user_id)

    assert order.client_id is not None
    client = db.query(ClientAccount).filter(ClientAccount.id == order.client_id).one()
    assert client.email == "buyer@acme.io"
    assert client.source == "order"
    assert str(client.user_id) == user_id


def test_orders_sharing_an_email_reuse_one_client(db_session):
    db = db_session
    user_id = str(uuid.uuid4())

    o1 = freelance_service.create_order(db, _order_create(), user_id=user_id)
    o2 = freelance_service.create_order(
        db, _order_create(service_type="logo design", price=250.0), user_id=user_id
    )
    o3 = freelance_service.create_order(
        db, _order_create(client_email="other@beta.io", client_name="Beta"), user_id=user_id
    )

    assert o1.client_id == o2.client_id  # same email -> same client
    assert o3.client_id != o1.client_id  # different email -> different client
    clients = db.query(ClientAccount).filter(ClientAccount.user_id == uuid.UUID(user_id)).all()
    assert len(clients) == 2


def test_get_or_create_client_does_not_downgrade_source(db_session):
    db = db_session
    user_id = str(uuid.uuid4())

    leadgen_client = intake_service.get_or_create_client(
        db, user_id, email="lead@acme.io", company="Acme", source="leadgen", lead_id=42
    )
    # A later order for the same email must not reset a leadgen origin to "order".
    same = intake_service.get_or_create_client(db, user_id, email="lead@acme.io", source="order")
    assert same.id == leadgen_client.id
    assert same.source == "leadgen"
    assert same.lead_id == 42


def test_client_lineage_and_listing(db_session):
    db = db_session
    user_id = str(uuid.uuid4())
    o1 = freelance_service.create_order(db, _order_create(), user_id=user_id)
    freelance_service.create_order(db, _order_create(service_type="seo", price=500.0), user_id=user_id)

    lineage = intake_service.get_client_lineage(db, user_id, o1.client_id)
    assert lineage["email"] == "buyer@acme.io"
    assert lineage["order_count"] == 2
    assert lineage["total_order_value"] == pytest.approx(1500.0)
    assert {row["service_type"] for row in lineage["orders"]} == {"landing page", "seo"}

    listing = intake_service.list_clients(db, user_id)
    assert len(listing) == 1
    assert listing[0]["order_count"] == 2

    # lineage is user-scoped
    with pytest.raises(ValueError):
        intake_service.get_client_lineage(db, str(uuid.uuid4()), o1.client_id)


def _make_lead(db, user_id):
    from apps.search.models import LeadGenResult

    lead = LeadGenResult(
        query="b2b saas marketing agencies",
        user_id=uuid.UUID(user_id),
        company="Northwind Agency",
        url="https://northwind.example",
        context="Hiring for inbound marketing help",
        fit_score=0.8,
        intent_score=0.7,
        data_quality_score=0.9,
        overall_score=0.8,
        reasoning="Active hiring signal + strong fit",
    )
    db.add(lead)
    db.flush()
    return lead


def test_get_lead_by_id_public_accessor(db_session):
    from apps.search.public import get_lead_by_id

    db = db_session
    user_id = str(uuid.uuid4())
    lead = _make_lead(db, user_id)

    assert get_lead_by_id(db, lead.id, user_id).id == lead.id
    assert get_lead_by_id(db, lead.id).id == lead.id            # unscoped
    assert get_lead_by_id(db, lead.id, str(uuid.uuid4())) is None  # wrong owner
    assert get_lead_by_id(db, 999999, user_id) is None            # missing


def test_convert_lead_to_order_builds_linked_client_and_order(db_session):
    db = db_session
    user_id = str(uuid.uuid4())
    lead = _make_lead(db, user_id)

    result = intake_service.convert_lead_to_order(
        db,
        user_id,
        lead_id=lead.id,
        client_email="ceo@northwind.example",
        service_type="inbound marketing retainer",
        price=2500.0,
    )

    client = result["client"]
    order = result["order"]
    assert result["lead_id"] == lead.id
    # lead -> client lineage
    assert client.source == "leadgen"
    assert client.lead_id == lead.id
    assert client.company == "Northwind Agency"
    # client -> order lineage
    assert order.client_id == client.id
    assert order.service_type == "inbound marketing retainer"
    # lead context carried into the order without re-entry
    assert "Northwind Agency" in (order.project_details or "")
    assert "northwind.example" in (order.project_details or "")

    # the lineage query ties it all together
    lineage = intake_service.get_client_lineage(db, user_id, client.id)
    assert lineage["lead_id"] == lead.id
    assert lineage["order_count"] == 1


def test_convert_lead_to_order_missing_lead_raises(db_session):
    db = db_session
    user_id = str(uuid.uuid4())
    with pytest.raises(ValueError):
        intake_service.convert_lead_to_order(
            db, user_id, lead_id=123456, client_email="x@y.io", service_type="x"
        )
