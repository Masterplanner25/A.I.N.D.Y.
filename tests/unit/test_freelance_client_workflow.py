"""Freelance Phase 3 — client workflow automation (multi-step lifecycle flows).

Covers the two chained flows added in Phase 3 (`docs/domains/FREELANCING_SYSTEM.md`):

  * ``freelance_client_onboarding``  — lead -> client + order -> delivery dispatch
  * ``freelance_order_fulfillment``  — deliver order -> refresh revenue metrics

The flow nodes are pure ``(state, context)`` functions; these drive them directly
and thread state exactly as the runtime flow engine does (``state.update(patch)`` on
SUCCESS), so the multi-step contract — each step reading what the previous produced —
is exercised on the SQLite app-profile harness.
"""

from __future__ import annotations

import uuid

import pytest

from apps.freelance.flows import freelance_flows as flows
from apps.freelance.models.freelance import FreelanceOrder
from apps.freelance.services import freelance_service

pytestmark = pytest.mark.app_profile


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


def _run_chain(nodes, state, context):
    """Execute nodes in order, merging each SUCCESS output_patch into state as the
    runtime flow engine does; returns (final_state, results)."""
    results = []
    for node in nodes:
        result = node(state, context)
        results.append(result)
        if result["status"] == "SUCCESS":
            state.update(result.get("output_patch", {}))
        else:
            break
    return state, results


def _intake(lead_id, **overrides):
    payload = {
        "lead_id": lead_id,
        "client_email": "ceo@northwind.example",
        "service_type": "inbound marketing retainer",
        "price": 2500.0,
        "auto_generate_delivery": False,
    }
    payload.update(overrides)
    return payload


class TestOnboardingNodes:

    def test_intake_node_creates_client_and_order(self, db_session):
        uid = str(uuid.uuid4())
        lead = _make_lead(db_session, uid)
        ctx = {"db": db_session, "user_id": uid}

        result = flows.freelance_onboarding_intake_node({"intake": _intake(lead.id)}, ctx)

        assert result["status"] == "SUCCESS"
        patch = result["output_patch"]
        assert patch["order_id"] is not None
        assert patch["client_id"] is not None
        onboarding = patch["_onboarding"]
        assert onboarding["lead_id"] == lead.id
        assert onboarding["client"]["source"] == "leadgen"
        assert onboarding["order"]["service_type"] == "inbound marketing retainer"

    def test_intake_node_missing_lead_is_404(self, db_session):
        uid = str(uuid.uuid4())
        ctx = {"db": db_session, "user_id": uid}
        result = flows.freelance_onboarding_intake_node({"intake": _intake(999999)}, ctx)
        assert result["status"] == "FAILURE"
        assert result["error"].startswith("HTTP_404")

    def test_intake_node_does_not_auto_generate_delivery(self, db_session, monkeypatch):
        # The intake step must never dispatch delivery — that is the dispatch step's job.
        uid = str(uuid.uuid4())
        lead = _make_lead(db_session, uid)
        called = {"queue": False}

        def _boom(*a, **k):
            called["queue"] = True
            return {}

        monkeypatch.setattr(freelance_service, "queue_delivery_generation", _boom)
        flows.freelance_onboarding_intake_node(
            {"intake": _intake(lead.id, auto_generate_delivery=True)}, {"db": db_session, "user_id": uid}
        )
        assert called["queue"] is False

    def test_dispatch_node_deferred_for_manual_delivery(self, db_session):
        ctx = {"db": db_session, "user_id": str(uuid.uuid4())}
        state = {"order_id": 1, "intake": _intake(1, auto_generate_delivery=False)}
        result = flows.freelance_onboarding_dispatch_node(state, ctx)
        assert result["status"] == "SUCCESS"
        assert result["output_patch"]["_onboarding_dispatch"]["delivery"] == "deferred"

    def test_dispatch_node_queues_when_requested(self, db_session, monkeypatch):
        ctx = {"db": db_session, "user_id": str(uuid.uuid4())}
        monkeypatch.setattr(
            freelance_service, "queue_delivery_generation", lambda *a, **k: {"automation_log_id": "log-1"}
        )
        state = {"order_id": 7, "intake": _intake(7, auto_generate_delivery=True)}
        result = flows.freelance_onboarding_dispatch_node(state, ctx)
        assert result["output_patch"]["_onboarding_dispatch"]["delivery"] == "queued"

    def test_dispatch_failure_is_non_fatal(self, db_session, monkeypatch):
        # Client + order already committed -> a dispatch error must not fail the flow.
        ctx = {"db": db_session, "user_id": str(uuid.uuid4())}

        def _raise(*a, **k):
            raise ValueError("order not deliverable")

        monkeypatch.setattr(freelance_service, "queue_delivery_generation", _raise)
        state = {"order_id": 7, "intake": _intake(7, auto_generate_delivery=True)}
        result = flows.freelance_onboarding_dispatch_node(state, ctx)
        assert result["status"] == "SUCCESS"
        assert result["output_patch"]["_onboarding_dispatch"]["delivery"] == "dispatch_failed"

    def test_summarize_node_assembles_envelope(self, db_session):
        state = {
            "_onboarding": {"lead_id": 3, "client": {"id": 1}, "order": {"id": 2}},
            "_onboarding_dispatch": {"delivery": "queued", "dispatch": {}},
        }
        result = flows.freelance_onboarding_summarize_node(state, {})
        data = result["output_patch"]["freelance_client_onboarding_result"]["data"]
        assert data["lead_id"] == 3
        assert data["delivery"] == "queued"
        assert data["next_action"] == "delivery_generating"

    def test_full_onboarding_chain_threads_state(self, db_session):
        uid = str(uuid.uuid4())
        lead = _make_lead(db_session, uid)
        ctx = {"db": db_session, "user_id": uid}
        state = {"intake": _intake(lead.id), "idempotency_key": "idem-onboard-1"}

        final, results = _run_chain(
            [
                flows.freelance_onboarding_intake_node,
                flows.freelance_onboarding_dispatch_node,
                flows.freelance_onboarding_summarize_node,
            ],
            state,
            ctx,
        )

        assert [r["status"] for r in results] == ["SUCCESS", "SUCCESS", "SUCCESS"]
        data = final["freelance_client_onboarding_result"]["data"]
        assert data["lead_id"] == lead.id
        assert data["order"]["id"] == final["order_id"]        # order minted at step 1 flows through
        assert data["delivery"] == "deferred"                  # manual delivery
        assert data["next_action"] == "await_manual_delivery"
        # the order really exists and is client-linked
        order = db_session.query(FreelanceOrder).filter(FreelanceOrder.id == final["order_id"]).one()
        assert order.client_id == final["client_id"]


class TestFulfillmentNodes:

    def _seed_order(self, db, uid):
        from apps.freelance.schemas.freelance import FreelanceOrderCreate

        return freelance_service.create_order(
            db,
            FreelanceOrderCreate(
                client_name="Acme", client_email="buyer@acme.io",
                service_type="landing page", project_details="build it", price=1000.0,
            ),
            user_id=uid,
        )

    def test_deliver_node_attaches_output(self, db_session):
        uid = str(uuid.uuid4())
        order = self._seed_order(db_session, uid)
        ctx = {"db": db_session, "user_id": uid}

        result = flows.freelance_fulfillment_deliver_node(
            {"order_id": order.id, "ai_output": "the deliverable"}, ctx
        )
        assert result["status"] == "SUCCESS"
        assert result["output_patch"]["order_id"] == order.id
        assert result["output_patch"]["_fulfillment_order"]["ai_output"] == "the deliverable"

    def test_deliver_node_missing_order_is_404(self, db_session):
        ctx = {"db": db_session, "user_id": str(uuid.uuid4())}
        result = flows.freelance_fulfillment_deliver_node({"order_id": 999999, "ai_output": "x"}, ctx)
        assert result["status"] == "FAILURE"
        assert result["error"].startswith("HTTP_404")

    def test_full_fulfillment_chain(self, db_session):
        uid = str(uuid.uuid4())
        order = self._seed_order(db_session, uid)
        ctx = {"db": db_session, "user_id": uid}
        state = {"order_id": order.id, "ai_output": "final deliverable"}

        final, results = _run_chain(
            [flows.freelance_fulfillment_deliver_node, flows.freelance_fulfillment_metrics_node],
            state,
            ctx,
        )

        assert [r["status"] for r in results] == ["SUCCESS", "SUCCESS"]
        data = final["freelance_order_fulfillment_result"]["data"]
        assert data["order"]["id"] == order.id
        assert data["order"]["ai_output"] == "final deliverable"
        assert "metrics" in data  # revenue metrics refreshed in the same flow
