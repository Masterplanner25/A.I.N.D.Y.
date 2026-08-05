from __future__ import annotations

from datetime import datetime, timezone
import json
import smtplib
from email.message import EmailMessage
from typing import Any
from urllib import parse as urllib_parse
from urllib import request as urllib_request


# Outbound connectors are registered with the runtime (FR-1 /
# MASTERPLAN-CONNECTOR-RUNTIME-1) and dispatched through
# ``connector_service.dispatch_connector`` — which runs each handler under its
# capability's authorization scope (recipient/domain allowlist, rate limit,
# socket-level egress guard, JIT credential vaulting), all opt-in and vacuous until an
# operator registers a policy. ``content_generation`` is internal-only (no outbound
# I/O), so it is handled locally rather than as a connector.
_OUTBOUND_CONNECTOR_TYPES = ("social", "crm", "email", "webhook", "stripe", "subscription")
SUPPORTED_AUTOMATION_TYPES = {*_OUTBOUND_CONNECTOR_TYPES, "content_generation"}


def register_automation_connectors(*, overwrite: bool = False) -> None:
    """Register the app's outbound connectors with the runtime (FR-1).

    Symmetric to the other ``register_*`` bootstrap steps. Each capability defaults to
    ``outbound.<type>``; enforcement stays vacuous until a ``CapabilityPolicy`` / secret
    scope is registered for it, so this changes dispatch routing only, not behavior.
    """
    from AINDY.platform_layer.registry import register_connector

    handlers = {
        "social": _social_connector,
        "crm": _crm_connector,
        "email": _email_connector,
        "webhook": _webhook_connector,
        "stripe": _stripe_connector,
        "subscription": _subscription_connector,
    }
    for connector_type, handler in handlers.items():
        register_connector(
            connector_type,
            handler,
            capability=f"outbound.{connector_type}",
            description=f"Masterplan automation outbound connector: {connector_type}",
            overwrite=overwrite,
        )


def execute_automation_action(payload: dict[str, Any], db) -> dict[str, Any]:
    automation_type = str(payload.get("automation_type") or "").strip()
    config = dict(payload.get("automation_config") or {})

    if automation_type not in SUPPORTED_AUTOMATION_TYPES:
        raise ValueError(f"unsupported_automation_type:{automation_type or 'unknown'}")

    # Internal-only: no outbound I/O, so not a connector.
    if automation_type == "content_generation":
        return _execute_content_generation(payload, config)

    # Outbound: route through the runtime's capability-enforced connector boundary
    # instead of a hardcoded if/elif ladder.
    from AINDY.platform_layer.connector_service import dispatch_connector

    user_id = payload.get("user_id")
    envelope = dispatch_connector(
        automation_type,
        {"payload": payload, "config": config},
        user_id=str(user_id) if user_id else None,
        db=db,
    )
    if envelope.get("success"):
        return envelope["result"]

    error = envelope.get("error") or f"{automation_type}_connector_failed"
    if envelope.get("denied"):
        # Capability / policy / rate denial — distinct from a validation or transport error.
        raise PermissionError(error)
    # Handler validation errors (e.g. ``social_content_required``) surface here as the
    # message string; re-raise as ValueError to preserve the pre-FR-1 caller contract.
    raise ValueError(error)


def _auth_headers(config: dict[str, Any], *, header_key: str = "auth_header", key_key: str = "api_key") -> dict[str, str]:
    """Build outbound headers with a JSON content-type and optional auth.

    Accepts either a full ``auth_header`` (used verbatim) or an ``api_key``
    (sent as a Bearer token). Extra ``headers`` in config are merged in.
    """
    headers: dict[str, str] = {"Content-Type": "application/json"}
    headers.update({str(k): str(v) for k, v in (config.get("headers") or {}).items()})
    if config.get(header_key):
        headers["Authorization"] = str(config.get(header_key))
    elif config.get(key_key):
        headers["Authorization"] = f"Bearer {config.get(key_key)}"
    return headers


def _http_json(endpoint: str, body: Any, headers: dict[str, str], method: str) -> dict[str, Any]:
    """POST/PUT a JSON body and return a compact {status_code, body} result."""
    req = urllib_request.Request(
        str(endpoint),
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method=method,
    )
    with urllib_request.urlopen(req, timeout=15) as resp:
        return {
            "status_code": getattr(resp, "status", 200),
            "body": resp.read().decode("utf-8", errors="ignore")[:2000],
        }


def _social_connector(action: dict[str, Any], ctx) -> dict[str, Any]:
    payload = action["payload"]
    config = action["config"]
    content = str(config.get("content") or payload.get("task_name") or "").strip()
    if not content:
        raise ValueError("social_content_required")

    from AINDY.db.mongo_setup import MONGO_DB_NAME, require_mongo_client

    mongo = require_mongo_client("automation_execution_service")
    social_db = mongo[MONGO_DB_NAME]
    posts = social_db["posts"]
    post_id = str(config.get("post_id") or "")
    now = datetime.now(timezone.utc)
    tags = config.get("tags") or ["masterplan", "automation"]
    document = {
        "user_id": str(payload.get("user_id") or ""),
        "content": content,
        "visibility": config.get("visibility", "private"),
        "tags": tags,
        "created_at": now,
        "updated_at": now,
        "origin": "masterplan_automation",
        "task_id": payload.get("task_id"),
        "masterplan_id": payload.get("masterplan_id"),
    }
    inserted = posts.insert_one(document)
    result = {
        "automation_type": "social",
        "status": "completed",
        "post_id": str(inserted.inserted_id),
        "content": content,
        "requested_post_id": post_id or None,
        "delivery": "internal",
    }

    # Additive external delivery: when an external target is configured, also
    # publish the post to that surface (e.g. a real social API / bridge). The
    # internal feed post above is always written regardless.
    external_endpoint = config.get("external_endpoint") or config.get("external_url")
    if external_endpoint:
        headers = _auth_headers(
            config, header_key="external_auth_header", key_key="external_api_key"
        )
        if config.get("external_headers"):
            headers.update({str(k): str(v) for k, v in config["external_headers"].items()})
        method = str(config.get("external_method") or "POST").upper()
        body = config.get("external_body")
        if body is None:
            body = {
                "content": content,
                "visibility": config.get("visibility", "private"),
                "tags": tags,
                "user_id": str(payload.get("user_id") or ""),
            }
        external_response = ctx.call(
            service_name="social",
            endpoint=str(external_endpoint),
            method=f"http.{method.lower()}",
            extra={"purpose": "social_external_delivery"},
            operation=lambda: _http_json(external_endpoint, body, headers, method),
        )
        result["delivery"] = "internal+external"
        result["external_response"] = external_response

    return result


def _crm_connector(action: dict[str, Any], ctx) -> dict[str, Any]:
    payload = action["payload"]
    config = action["config"]
    crm_action = config.get("action", "record_follow_up")
    contact = config.get("contact")
    details = config.get("details") or config.get("notes")
    endpoint = config.get("endpoint") or config.get("url") or config.get("crm_url")

    # No external CRM target configured — record the intent internally (the
    # historical stub behavior), so plan items without a CRM endpoint still work.
    if not endpoint:
        return {
            "automation_type": "crm",
            "status": "recorded",
            "delivery": "internal",
            "action": crm_action,
            "contact": contact,
            "details": details,
            "task_id": payload.get("task_id"),
        }

    headers = _auth_headers(config)
    method = str(config.get("method") or "POST").upper()
    body = config.get("body")
    if body is None:
        body = {
            "action": crm_action,
            "contact": contact,
            "details": details,
            "task_name": payload.get("task_name"),
            "user_id": str(payload.get("user_id") or ""),
            "metadata": config.get("metadata") or {},
        }
    response = ctx.call(
        service_name="crm",
        endpoint=str(endpoint),
        method=f"http.{method.lower()}",
        extra={"purpose": "crm_sync", "action": crm_action, "contact": contact},
        operation=lambda: _http_json(endpoint, body, headers, method),
    )
    return {
        "automation_type": "crm",
        "status": "completed",
        "delivery": "external",
        "action": crm_action,
        "contact": contact,
        "details": details,
        "task_id": payload.get("task_id"),
        "response": response,
    }


def _email_connector(action: dict[str, Any], ctx) -> dict[str, Any]:
    # User-authored automations only. aindy-runtime 2.0.0 also routed its own transactional
    # mail (verification, password reset) through this connector type, which forced a
    # shape-multiplexing branch here (FR-9). 2.0.1 moved that to a reserved
    # `transactional_email` type an app connector cannot intercept, so this is
    # single-purpose again and the runtime delivers its own mail over AINDY_SMTP_*.
    payload = action["payload"]
    config = action["config"]
    subject = str(config.get("subject") or payload.get("task_name") or "A.I.N.D.Y. automated message")
    body = str(config.get("body") or config.get("content") or "")
    recipient = config.get("recipient")
    if not recipient:
        raise ValueError("email_recipient_required")
    sender = str(config.get("sender") or config.get("from") or "no-reply@aindy.local")
    smtp_host = config.get("smtp_host")
    smtp_port = int(config.get("smtp_port") or 587)
    smtp_username = config.get("smtp_username")
    smtp_password = config.get("smtp_password")
    smtp_starttls = bool(config.get("smtp_starttls", True))
    provider_url = config.get("provider_url")

    if smtp_host:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = sender
        message["To"] = recipient
        message.set_content(body)

        def _send_smtp():
            with smtplib.SMTP(str(smtp_host), smtp_port, timeout=15) as smtp:
                if smtp_starttls:
                    smtp.starttls()
                if smtp_username:
                    smtp.login(str(smtp_username), str(smtp_password or ""))
                smtp.send_message(message)
            return {"transport": "smtp", "host": smtp_host, "port": smtp_port}

        response = ctx.call(
            service_name="smtp",
            endpoint=f"{smtp_host}:{smtp_port}",
            method="smtp.send",
            extra={"purpose": "email_delivery", "recipient": recipient},
            operation=_send_smtp,
        )
    elif provider_url:
        headers = {"Content-Type": "application/json"}
        if config.get("auth_header"):
            headers["Authorization"] = str(config.get("auth_header"))

        def _send_provider():
            req = urllib_request.Request(
                str(provider_url),
                data=json.dumps(
                    {
                        "to": recipient,
                        "from": sender,
                        "subject": subject,
                        "body": body,
                    }
                ).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib_request.urlopen(req, timeout=15) as resp:
                return {
                    "transport": "api",
                    "status_code": getattr(resp, "status", 200),
                    "body": resp.read().decode("utf-8", errors="ignore")[:2000],
                }

        response = ctx.call(
            service_name="email_api",
            endpoint=str(provider_url),
            method="http.post",
            extra={"purpose": "email_delivery", "recipient": recipient},
            operation=_send_provider,
        )
    else:
        raise ValueError("email_delivery_transport_required")

    return {
        "automation_type": "email",
        "status": "completed",
        "recipient": recipient,
        "subject": subject,
        "body": body,
        "response": response,
    }


def _webhook_connector(action: dict[str, Any], ctx) -> dict[str, Any]:
    payload = action["payload"]
    config = action["config"]
    webhook_url = config.get("url") or config.get("webhook_url")
    if not webhook_url:
        raise ValueError("webhook_url_required")
    method = str(config.get("method") or "POST").upper()
    headers = dict(config.get("headers") or {})
    headers.setdefault("Content-Type", "application/json")
    body = config.get("body")
    if body is None:
        body = {
            "task_name": payload.get("task_name"),
            "user_id": payload.get("user_id"),
            "content": config.get("content"),
            "metadata": config.get("metadata") or {},
        }

    def _send_webhook():
        req = urllib_request.Request(
            str(webhook_url),
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method=method,
        )
        with urllib_request.urlopen(req, timeout=15) as resp:
            return {
                "status_code": getattr(resp, "status", 200),
                "body": resp.read().decode("utf-8", errors="ignore")[:2000],
            }

    response = ctx.call(
        service_name="webhook",
        endpoint=str(webhook_url),
        method=f"http.{method.lower()}",
        extra={"purpose": "webhook_delivery"},
        operation=_send_webhook,
    )
    return {
        "automation_type": "webhook",
        "status": "completed",
        "response": response,
    }


def _stripe_connector(action: dict[str, Any], ctx) -> dict[str, Any]:
    payload = action["payload"]
    config = action["config"]
    from AINDY.config import settings

    stripe_key = config.get("stripe_secret_key") or settings.STRIPE_SECRET_KEY
    if not stripe_key:
        raise ValueError(
            "stripe_secret_key not configured. Set STRIPE_SECRET_KEY in environment "
            "or provide stripe_secret_key in delivery_config."
        )

    amount_raw = config.get("amount") or (payload.get("automation_config") or {}).get("amount")
    if amount_raw is None:
        metadata = config.get("metadata") or {}
        price_float = float(metadata.get("price") or config.get("price") or 0.0)
        amount_cents = int(round(price_float * 100))
    else:
        amount_cents = int(amount_raw)

    if amount_cents <= 0:
        raise ValueError("stripe_payment_amount_required: amount must be > 0 cents")

    currency = str(config.get("currency") or "usd").lower()
    product_name = str(
        config.get("product_name")
        or payload.get("task_name")
        or "Freelance Service"
    )
    customer_email = config.get("customer_email") or config.get("recipient")

    def _stripe_post(path: str, form_data: dict[str, Any]) -> dict[str, Any]:
        encoded = urllib_parse.urlencode(form_data).encode("utf-8")
        req = urllib_request.Request(
            f"https://api.stripe.com{path}",
            data=encoded,
            headers={
                "Authorization": f"Bearer {stripe_key}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with urllib_request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _create_payment_link() -> dict[str, Any]:
        product = _stripe_post(
            "/v1/products",
            {
                "name": product_name,
                "description": str(config.get("description") or product_name)[:500],
            },
        )
        product_id = product["id"]

        price = _stripe_post(
            "/v1/prices",
            {
                "product": product_id,
                "unit_amount": str(amount_cents),
                "currency": currency,
            },
        )
        price_id = price["id"]

        link_data = {
            "line_items[0][price]": price_id,
            "line_items[0][quantity]": "1",
        }
        if customer_email:
            link_data["customer_creation"] = "always"
            link_data["customer_email"] = str(customer_email)

        link = _stripe_post("/v1/payment_links", link_data)
        return {
            "product_id": product_id,
            "price_id": price_id,
            "payment_link_id": link["id"],
            "payment_link_url": link["url"],
        }

    response = ctx.call(
        service_name="stripe",
        endpoint="/v1/payment_links",
        method="stripe.payment_links.create",
        extra={
            "purpose": "freelance_payment_link",
            "customer_email": customer_email,
            "amount_cents": amount_cents,
            "currency": currency,
        },
        operation=_create_payment_link,
    )

    return {
        "automation_type": "stripe",
        "status": "completed",
        "payment_link_id": response["payment_link_id"],
        "payment_link_url": response["payment_link_url"],
        "product_id": response["product_id"],
        "price_id": response["price_id"],
        "amount_cents": amount_cents,
        "currency": currency,
        "customer_email": customer_email,
    }


def _subscription_connector(action: dict[str, Any], ctx) -> dict[str, Any]:
    """Create a Stripe customer + recurring subscription."""
    payload = action["payload"]
    config = action["config"]
    from AINDY.config import settings as _settings

    stripe_key = config.get("stripe_secret_key") or _settings.STRIPE_SECRET_KEY
    if not stripe_key:
        raise ValueError(
            "stripe_secret_key not configured. Set STRIPE_SECRET_KEY "
            "or provide stripe_secret_key in delivery_config."
        )
    customer_email = config.get("customer_email") or config.get("recipient")
    if not customer_email:
        raise ValueError("customer_email required for subscription billing")

    amount_raw = config.get("amount")
    if amount_raw is None:
        meta = config.get("metadata") or {}
        price_float = float(meta.get("price") or config.get("price") or 0.0)
        amount_cents = int(round(price_float * 100))
    else:
        amount_cents = int(amount_raw)
    if amount_cents <= 0:
        raise ValueError("stripe_subscription_amount_required: amount must be > 0 cents")

    currency = str(config.get("currency") or "usd").lower()
    interval = str(config.get("interval") or "month").lower()
    if interval not in {"month", "year", "week", "day"}:
        raise ValueError(
            f"Invalid billing interval '{interval}'. Use: month, year, week, day"
        )
    product_name = str(
        config.get("product_name")
        or payload.get("task_name")
        or "Freelance Subscription"
    )
    metadata = config.get("metadata") or {}

    def _stripe_post_sub(path, form_data, *, stripe_key):
        encoded = urllib_parse.urlencode(form_data).encode("utf-8")
        req = urllib_request.Request(
            f"https://api.stripe.com{path}",
            data=encoded,
            headers={
                "Authorization": f"Bearer {stripe_key}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with urllib_request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _do_create() -> dict[str, Any]:
        customer = _stripe_post_sub(
            "/v1/customers",
            {
                "email": customer_email,
                "metadata[order_id]": str(metadata.get("order_id") or ""),
            },
            stripe_key=stripe_key,
        )
        customer_id = customer["id"]

        product = _stripe_post_sub(
            "/v1/products",
            {"name": product_name},
            stripe_key=stripe_key,
        )
        product_id = product["id"]

        price = _stripe_post_sub(
            "/v1/prices",
            {
                "product": product_id,
                "unit_amount": str(amount_cents),
                "currency": currency,
                "recurring[interval]": interval,
            },
            stripe_key=stripe_key,
        )
        price_id = price["id"]

        sub_data = {
            "customer": customer_id,
            "items[0][price]": price_id,
            "payment_behavior": "default_incomplete",
            "expand[]": "latest_invoice.payment_intent",
        }
        if metadata:
            for key, value in metadata.items():
                sub_data[f"metadata[{key}]"] = str(value)
        subscription = _stripe_post_sub(
            "/v1/subscriptions",
            sub_data,
            stripe_key=stripe_key,
        )
        period_end = subscription.get("current_period_end")
        return {
            "customer_id": customer_id,
            "subscription_id": subscription["id"],
            "subscription_status": subscription.get("status", "incomplete"),
            "price_id": price_id,
            "current_period_end": period_end,
        }

    response = ctx.call(
        service_name="stripe",
        endpoint="/v1/subscriptions",
        method="stripe.subscriptions.create",
        extra={
            "purpose": "freelance_subscription",
            "customer_email": customer_email,
            "amount_cents": amount_cents,
            "interval": interval,
        },
        operation=_do_create,
    )
    return {
        "automation_type": "subscription",
        "status": "completed",
        **response,
        "amount_cents": amount_cents,
        "currency": currency,
        "interval": interval,
        "customer_email": customer_email,
    }


def _execute_content_generation(payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    prompt = str(config.get("prompt") or payload.get("task_name") or "").strip()
    if not prompt:
        raise ValueError("content_prompt_required")
    tone = str(config.get("tone") or "operational")
    generated = config.get("template") or f"[{tone}] {prompt}"
    return {
        "automation_type": "content_generation",
        "status": "completed",
        "prompt": prompt,
        "generated_content": generated,
        "format": config.get("format", "text"),
    }


# ── automation log access ─────────────────────────────────────────────────────

def get_automation_log(db, log_id: str, user_id: str) -> Any | None:
    """
    Fetch an AutomationLog row by id.

    Returns the row if it exists (ownership is not enforced at the DB level —
    the replay endpoint validates the execution_token instead).
    Returns None when no row matches log_id.
    """
    from apps.automation.models import AutomationLog

    return db.query(AutomationLog).filter(AutomationLog.id == log_id).first()
