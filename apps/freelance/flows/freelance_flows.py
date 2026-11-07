from AINDY.runtime.flow_helpers import register_flow, register_nodes, register_single_node_flows


def freelance_order_create_node(state, context):
    try:
        from apps.freelance.schemas.freelance import FreelanceOrderCreate, FreelanceOrderResponse
        from apps.freelance.services import freelance_service

        db = context.get("db")
        user_id = str(context.get("user_id"))
        order = FreelanceOrderCreate(**state.get("order", {}))
        created, was_created = freelance_service.create_order(
            db,
            order,
            user_id=user_id,
            idempotency_key=state.get("idempotency_key"),
            return_created=True,
        )
        return {"status": "SUCCESS", "output_patch": {"freelance_order_create_result": {
            "data": {
                **FreelanceOrderResponse.model_validate(created).model_dump(mode="json"),
                "_idempotency": {"created": was_created},
            },
        }}}
    except ValueError as e:
        return {"status": "FAILURE", "error": f"HTTP_422:{e}"}
    except Exception as e:
        return {"status": "FAILURE", "error": f"HTTP_500:Failed to create order: {e}"}


def freelance_order_deliver_node(state, context):
    try:
        import uuid as _uuid
        from apps.freelance.models.freelance import FreelanceOrder
        from apps.freelance.schemas.freelance import FreelanceOrderResponse
        from apps.freelance.services import freelance_service

        db = context.get("db")
        user_id = str(context.get("user_id"))
        order_id = state.get("order_id")
        ai_output = state.get("ai_output")
        order = db.query(FreelanceOrder).filter(
            FreelanceOrder.id == order_id,
            FreelanceOrder.user_id == _uuid.UUID(user_id),
        ).first()
        if not order:
            return {"status": "FAILURE", "error": "HTTP_404:Order not found"}
        delivered = freelance_service.deliver_order(db, order_id, ai_output, generated_by_ai=False)
        return {"status": "SUCCESS", "output_patch": {"freelance_order_deliver_result": {
            "data": FreelanceOrderResponse.model_validate(delivered).model_dump(mode="json"),
        }}}
    except Exception as e:
        return {"status": "FAILURE", "error": f"HTTP_500:Failed to deliver order: {e}"}


def freelance_delivery_update_node(state, context):
    try:
        from apps.freelance.schemas.freelance import FreelanceOrderResponse
        from apps.freelance.services import freelance_service

        db = context.get("db")
        user_id = str(context.get("user_id"))
        try:
            updated = freelance_service.update_delivery_config(
                db=db, order_id=state.get("order_id"), user_id=user_id,
                delivery_type=state.get("delivery_type"), delivery_config=state.get("delivery_config"),
            )
        except ValueError as e:
            return {"status": "FAILURE", "error": f"HTTP_404:{e}"}
        return {"status": "SUCCESS", "output_patch": {"freelance_delivery_update_result":
            FreelanceOrderResponse.model_validate(updated).model_dump(mode="json")
        }}
    except Exception as e:
        return {"status": "FAILURE", "error": f"HTTP_500:Failed to update delivery configuration: {e}"}


def freelance_feedback_collect_node(state, context):
    try:
        from apps.freelance.schemas.freelance import FeedbackCreate, FeedbackResponse
        from apps.freelance.services import freelance_service

        db = context.get("db")
        user_id = str(context.get("user_id"))
        feedback = FeedbackCreate(**state.get("feedback", {}))
        try:
            collected = freelance_service.collect_feedback(db, feedback, user_id=user_id)
        except ValueError as e:
            return {"status": "FAILURE", "error": f"HTTP_404:{e}"}
        return {"status": "SUCCESS", "output_patch": {"freelance_feedback_collect_result": {
            "data": FeedbackResponse.model_validate(collected).model_dump(mode="json"),
        }}}
    except Exception as e:
        return {"status": "FAILURE", "error": f"HTTP_500:Failed to collect feedback: {e}"}


def freelance_orders_list_node(state, context):
    try:
        from apps.freelance.schemas.freelance import FreelanceOrderResponse
        from apps.freelance.services import freelance_service

        db = context.get("db")
        user_id = str(context.get("user_id"))
        orders = freelance_service.get_all_orders(db, user_id=user_id)
        return {"status": "SUCCESS", "output_patch": {"freelance_orders_list_result": [
            FreelanceOrderResponse.model_validate(o).model_dump(mode="json") for o in orders
        ]}}
    except Exception as e:
        return {"status": "FAILURE", "error": str(e)}


def freelance_feedback_list_node(state, context):
    try:
        from apps.freelance.schemas.freelance import FeedbackResponse
        from apps.freelance.services import freelance_service

        db = context.get("db")
        user_id = str(context.get("user_id"))
        items = freelance_service.get_all_feedback(db, user_id=user_id)
        return {"status": "SUCCESS", "output_patch": {"freelance_feedback_list_result": [
            FeedbackResponse.model_validate(i).model_dump(mode="json") for i in items
        ]}}
    except Exception as e:
        return {"status": "FAILURE", "error": str(e)}


def freelance_metrics_latest_node(state, context):
    try:
        from apps.freelance.schemas.freelance import RevenueMetricsResponse
        from apps.freelance.services import freelance_service

        db = context.get("db")
        metric = freelance_service.get_latest_metrics(db, str(context.get("user_id")))
        if not metric:
            return {"status": "FAILURE", "error": "HTTP_404:No revenue metrics found"}
        return {"status": "SUCCESS", "output_patch": {"freelance_metrics_latest_result":
            RevenueMetricsResponse.model_validate(metric).model_dump(mode="json")
        }}
    except Exception as e:
        return {"status": "FAILURE", "error": str(e)}


def freelance_metrics_update_node(state, context):
    try:
        from apps.freelance.schemas.freelance import RevenueMetricsResponse
        from apps.freelance.services import freelance_service

        db = context.get("db")
        user_id = str(context.get("user_id"))
        metric = freelance_service.update_revenue_metrics(db, user_id=user_id)
        return {"status": "SUCCESS", "output_patch": {"freelance_metrics_update_result":
            RevenueMetricsResponse.model_validate(metric).model_dump(mode="json")
        }}
    except Exception as e:
        return {"status": "FAILURE", "error": f"HTTP_500:Metrics update failed: {e}"}


def freelance_delivery_generate_node(state, context):
    try:
        import uuid as _uuid
        from apps.freelance.models.freelance import FreelanceOrder
        from apps.freelance.services import freelance_service

        db = context.get("db")
        user_id = str(context.get("user_id"))
        order_id = state.get("order_id")
        order = db.query(FreelanceOrder).filter(
            FreelanceOrder.id == order_id,
            FreelanceOrder.user_id == _uuid.UUID(user_id),
        ).first()
        if not order:
            return {"status": "FAILURE", "error": "HTTP_404:Order not found"}
        try:
            dispatch = freelance_service.queue_delivery_generation(db, order_id=order_id, user_id=user_id)
        except (LookupError, ValueError) as e:
            return {"status": "FAILURE", "error": f"HTTP_404:{e}"}
        return {"status": "SUCCESS", "output_patch": {"freelance_delivery_generate_result": dispatch}}
    except Exception as e:
        return {"status": "FAILURE", "error": f"HTTP_500:Failed to queue freelance delivery generation: {e}"}


def freelance_refund_node(state, context):
    try:
        from apps.freelance.schemas.freelance import RefundResponse
        from apps.freelance.services import freelance_service

        db = context.get("db")
        user_id = str(context.get("user_id"))
        order_id = state.get("order_id")
        reason = state.get("reason")
        try:
            order, was_created = freelance_service.issue_refund(
                db,
                order_id,
                user_id=user_id,
                reason=reason,
                idempotency_key=state.get("idempotency_key"),
                return_created=True,
            )
        except ValueError as e:
            return {"status": "FAILURE", "error": f"HTTP_422:{e}"}
        amount_cents = int(round(float(order.price or 0.0) * 100)) if order.price is not None else None
        return {
            "status": "SUCCESS",
            "output_patch": {
                "freelance_refund_result": {
                    "data": RefundResponse(
                        order_id=order.id,
                        refund_id=str(order.refund_id or ""),
                        status=str(order.status or "refunded"),
                        payment_status=str(order.payment_status or "refunded"),
                        refunded_at=order.refunded_at,
                        reason=order.refund_reason,
                        amount_cents=amount_cents,
                    ).model_dump(mode="json") | {"_idempotency": {"created": was_created}},
                }
            },
        }
    except RuntimeError as e:
        return {"status": "FAILURE", "error": f"HTTP_500:{e}"}
    except Exception as e:
        return {"status": "FAILURE", "error": f"HTTP_500:Refund failed: {e}"}


def freelance_subscription_cancel_node(state, context):
    try:
        from apps.freelance.schemas.freelance import SubscriptionStatusResponse
        from apps.freelance.services import freelance_service

        db = context.get("db")
        user_id = str(context.get("user_id"))
        order_id = state.get("order_id")
        reason = state.get("reason")
        try:
            order = freelance_service.cancel_subscription(
                db,
                order_id,
                user_id=user_id,
                reason=reason,
            )
        except ValueError as e:
            return {"status": "FAILURE", "error": f"HTTP_422:{e}"}
        return {
            "status": "SUCCESS",
            "output_patch": {
                "freelance_subscription_cancel_result": {
                    "data": SubscriptionStatusResponse(
                        order_id=order.id,
                        status=str(order.status or "subscription_cancelled"),
                        subscription_status=order.subscription_status,
                        subscription_period_end=order.subscription_period_end,
                        reason=reason,
                    ).model_dump(mode="json"),
                }
            },
        }
    except RuntimeError as e:
        return {"status": "FAILURE", "error": f"HTTP_500:{e}"}
    except Exception as e:
        return {"status": "FAILURE", "error": f"HTTP_500:Subscription cancel failed: {e}"}


def freelance_clients_list_node(state, context):
    try:
        from apps.freelance.services import intake_service

        db = context.get("db")
        user_id = str(context.get("user_id"))
        clients = intake_service.list_clients(db, user_id)
        return {"status": "SUCCESS", "output_patch": {"freelance_clients_list_result": clients}}
    except Exception as e:
        return {"status": "FAILURE", "error": str(e)}


def freelance_client_lineage_node(state, context):
    try:
        from apps.freelance.services import intake_service

        db = context.get("db")
        user_id = str(context.get("user_id"))
        try:
            lineage = intake_service.get_client_lineage(db, user_id, state.get("client_id"))
        except ValueError as e:
            return {"status": "FAILURE", "error": f"HTTP_404:{e}"}
        return {"status": "SUCCESS", "output_patch": {"freelance_client_lineage_result": {"data": lineage}}}
    except Exception as e:
        return {"status": "FAILURE", "error": f"HTTP_500:Failed to load client lineage: {e}"}


def freelance_intake_from_lead_node(state, context):
    try:
        from apps.freelance.schemas.freelance import (
            ClientAccountResponse,
            FreelanceOrderResponse,
        )
        from apps.freelance.services import intake_service

        db = context.get("db")
        user_id = str(context.get("user_id"))
        intake = state.get("intake", {})
        try:
            result = intake_service.convert_lead_to_order(
                db,
                user_id,
                lead_id=intake.get("lead_id"),
                client_email=intake.get("client_email"),
                service_type=intake.get("service_type"),
                client_name=intake.get("client_name"),
                price=intake.get("price") or 0.0,
                project_details=intake.get("project_details"),
                delivery_type=intake.get("delivery_type") or "manual",
                delivery_config=intake.get("delivery_config"),
                auto_generate_delivery=bool(intake.get("auto_generate_delivery")),
                idempotency_key=state.get("idempotency_key"),
            )
        except ValueError as e:
            return {"status": "FAILURE", "error": f"HTTP_404:{e}"}
        return {
            "status": "SUCCESS",
            "output_patch": {
                "freelance_intake_from_lead_result": {
                    "data": {
                        "lead_id": result["lead_id"],
                        "client": ClientAccountResponse.model_validate(result["client"]).model_dump(mode="json"),
                        "order": FreelanceOrderResponse.model_validate(result["order"]).model_dump(mode="json"),
                    },
                }
            },
        }
    except Exception as e:
        return {"status": "FAILURE", "error": f"HTTP_500:Failed to convert lead to order: {e}"}


# --------------------------------------------------------------------------- #
# Phase 3 — client workflow automation (multi-step lifecycle flows)
#
# The single-node flows above expose each freelance operation atomically. These
# multi-step flows chain them into end-to-end client workflows, threading state
# forward (a node's ``output_patch`` merges into the run state, so a later step
# reads what an earlier one produced — e.g. the order id minted at intake drives
# delivery dispatch). Each step is its own observable FlowHistory entry.
# --------------------------------------------------------------------------- #
def freelance_onboarding_intake_node(state, context):
    """Onboarding step 1 — convert a qualified lead into a client + order.

    Delivery is deliberately NOT auto-generated here; the flow owns dispatch as an
    explicit downstream step (``freelance_onboarding_dispatch_node``) so onboarding
    stays observable even when the caller set ``auto_generate_delivery``.
    """
    try:
        from apps.freelance.schemas.freelance import (
            ClientAccountResponse,
            FreelanceOrderResponse,
        )
        from apps.freelance.services import intake_service

        db = context.get("db")
        user_id = str(context.get("user_id"))
        intake = state.get("intake", {})
        try:
            result = intake_service.convert_lead_to_order(
                db,
                user_id,
                lead_id=intake.get("lead_id"),
                client_email=intake.get("client_email"),
                service_type=intake.get("service_type"),
                client_name=intake.get("client_name"),
                price=intake.get("price") or 0.0,
                project_details=intake.get("project_details"),
                delivery_type=intake.get("delivery_type") or "manual",
                delivery_config=intake.get("delivery_config"),
                auto_generate_delivery=False,  # the dispatch step owns this
                idempotency_key=state.get("idempotency_key"),
            )
        except ValueError as e:
            return {"status": "FAILURE", "error": f"HTTP_404:{e}"}
        order = result["order"]
        client = result["client"]
        return {
            "status": "SUCCESS",
            "output_patch": {
                # threaded forward for the dispatch + summarize steps
                "order_id": order.id,
                "client_id": client.id,
                "_onboarding": {
                    "lead_id": result["lead_id"],
                    "client": ClientAccountResponse.model_validate(client).model_dump(mode="json"),
                    "order": FreelanceOrderResponse.model_validate(order).model_dump(mode="json"),
                },
            },
        }
    except Exception as e:
        return {"status": "FAILURE", "error": f"HTTP_500:Onboarding intake failed: {e}"}


def freelance_onboarding_dispatch_node(state, context):
    """Onboarding step 2 — dispatch delivery generation when the intake asked for it.

    Resilient: a dispatch failure is recorded (not raised) because the client and
    order are already committed — failing the flow would misreport a successful
    onboarding. Manual-delivery intakes are marked ``deferred``.
    """
    try:
        from apps.freelance.services import freelance_service

        db = context.get("db")
        user_id = str(context.get("user_id"))
        order_id = state.get("order_id")
        wants_delivery = bool((state.get("intake") or {}).get("auto_generate_delivery"))

        if not wants_delivery:
            dispatch = {"delivery": "deferred", "dispatch": None}
        else:
            try:
                envelope = freelance_service.queue_delivery_generation(
                    db, order_id=order_id, user_id=user_id
                )
                dispatch = {"delivery": "queued", "dispatch": envelope}
            except (LookupError, ValueError) as e:
                dispatch = {"delivery": "dispatch_failed", "dispatch": None, "error": f"HTTP_404:{e}"}
            except Exception as e:  # pragma: no cover - defensive; onboarding still succeeded
                dispatch = {"delivery": "dispatch_failed", "dispatch": None, "error": str(e)}

        return {"status": "SUCCESS", "output_patch": {"_onboarding_dispatch": dispatch}}
    except Exception as e:
        return {"status": "FAILURE", "error": f"HTTP_500:Onboarding dispatch failed: {e}"}


_ONBOARDING_NEXT_ACTION = {
    "queued": "delivery_generating",
    "deferred": "await_manual_delivery",
    "dispatch_failed": "retry_delivery_dispatch",
}


def freelance_onboarding_summarize_node(state, context):
    """Onboarding step 3 — assemble the consolidated onboarding envelope."""
    try:
        onboarding = state.get("_onboarding") or {}
        dispatch = state.get("_onboarding_dispatch") or {}
        delivery = dispatch.get("delivery", "deferred")
        return {
            "status": "SUCCESS",
            "output_patch": {
                "freelance_client_onboarding_result": {
                    "data": {
                        "lead_id": onboarding.get("lead_id"),
                        "client": onboarding.get("client"),
                        "order": onboarding.get("order"),
                        "delivery": delivery,
                        "delivery_error": dispatch.get("error"),
                        "next_action": _ONBOARDING_NEXT_ACTION.get(delivery, "await_manual_delivery"),
                    },
                },
            },
        }
    except Exception as e:
        return {"status": "FAILURE", "error": f"HTTP_500:Onboarding summarize failed: {e}"}


def freelance_fulfillment_deliver_node(state, context):
    """Fulfillment step 1 — attach the deliverable output to an order."""
    try:
        import uuid as _uuid
        from apps.freelance.models.freelance import FreelanceOrder
        from apps.freelance.schemas.freelance import FreelanceOrderResponse
        from apps.freelance.services import freelance_service

        db = context.get("db")
        user_id = str(context.get("user_id"))
        order_id = state.get("order_id")
        order = db.query(FreelanceOrder).filter(
            FreelanceOrder.id == order_id,
            FreelanceOrder.user_id == _uuid.UUID(user_id),
        ).first()
        if not order:
            return {"status": "FAILURE", "error": "HTTP_404:Order not found"}
        delivered = freelance_service.deliver_order(
            db, order_id, state.get("ai_output"), generated_by_ai=bool(state.get("generated_by_ai"))
        )
        return {
            "status": "SUCCESS",
            "output_patch": {
                "order_id": delivered.id,
                "_fulfillment_order": FreelanceOrderResponse.model_validate(delivered).model_dump(mode="json"),
            },
        }
    except Exception as e:
        return {"status": "FAILURE", "error": f"HTTP_500:Fulfillment delivery failed: {e}"}


def freelance_fulfillment_metrics_node(state, context):
    """Fulfillment step 2 — refresh revenue metrics so they reflect the delivery."""
    try:
        from apps.freelance.schemas.freelance import RevenueMetricsResponse
        from apps.freelance.services import freelance_service

        db = context.get("db")
        user_id = str(context.get("user_id"))
        metric = freelance_service.update_revenue_metrics(db, user_id=user_id)
        return {
            "status": "SUCCESS",
            "output_patch": {
                "freelance_order_fulfillment_result": {
                    "data": {
                        "order": state.get("_fulfillment_order"),
                        "metrics": RevenueMetricsResponse.model_validate(metric).model_dump(mode="json"),
                    },
                },
            },
        }
    except Exception as e:
        return {"status": "FAILURE", "error": f"HTTP_500:Fulfillment metrics update failed: {e}"}


def register() -> None:
    register_nodes(
        {
            "freelance_clients_list_node": freelance_clients_list_node,
            "freelance_client_lineage_node": freelance_client_lineage_node,
            "freelance_intake_from_lead_node": freelance_intake_from_lead_node,
            "freelance_order_create_node": freelance_order_create_node,
            "freelance_order_deliver_node": freelance_order_deliver_node,
            "freelance_delivery_update_node": freelance_delivery_update_node,
            "freelance_feedback_collect_node": freelance_feedback_collect_node,
            "freelance_orders_list_node": freelance_orders_list_node,
            "freelance_feedback_list_node": freelance_feedback_list_node,
            "freelance_metrics_latest_node": freelance_metrics_latest_node,
            "freelance_metrics_update_node": freelance_metrics_update_node,
            "freelance_delivery_generate_node": freelance_delivery_generate_node,
            "freelance_refund_node": freelance_refund_node,
            "freelance_subscription_cancel_node": freelance_subscription_cancel_node,
            # Phase 3 — client workflow lifecycle steps
            "freelance_onboarding_intake_node": freelance_onboarding_intake_node,
            "freelance_onboarding_dispatch_node": freelance_onboarding_dispatch_node,
            "freelance_onboarding_summarize_node": freelance_onboarding_summarize_node,
            "freelance_fulfillment_deliver_node": freelance_fulfillment_deliver_node,
            "freelance_fulfillment_metrics_node": freelance_fulfillment_metrics_node,
        }
    )
    register_single_node_flows(
        {
            "freelance_clients_list": "freelance_clients_list_node",
            "freelance_client_lineage": "freelance_client_lineage_node",
            "freelance_intake_from_lead": "freelance_intake_from_lead_node",
            "freelance_order_create": "freelance_order_create_node",
            "freelance_order_deliver": "freelance_order_deliver_node",
            "freelance_delivery_update": "freelance_delivery_update_node",
            "freelance_feedback_collect": "freelance_feedback_collect_node",
            "freelance_orders_list": "freelance_orders_list_node",
            "freelance_feedback_list": "freelance_feedback_list_node",
            "freelance_metrics_latest": "freelance_metrics_latest_node",
            "freelance_metrics_update": "freelance_metrics_update_node",
            "freelance_delivery_generate": "freelance_delivery_generate_node",
            "freelance_refund": "freelance_refund_node",
            "freelance_subscription_cancel": "freelance_subscription_cancel_node",
        }
    )

    # Phase 3 — multi-step client workflow flows (chained, state-threaded).
    register_flow(
        "freelance_client_onboarding",
        {
            "start": "freelance_onboarding_intake_node",
            "edges": {
                "freelance_onboarding_intake_node": ["freelance_onboarding_dispatch_node"],
                "freelance_onboarding_dispatch_node": ["freelance_onboarding_summarize_node"],
            },
            "end": ["freelance_onboarding_summarize_node"],
        },
    )
    register_flow(
        "freelance_order_fulfillment",
        {
            "start": "freelance_fulfillment_deliver_node",
            "edges": {
                "freelance_fulfillment_deliver_node": ["freelance_fulfillment_metrics_node"],
            },
            "end": ["freelance_fulfillment_metrics_node"],
        },
    )
