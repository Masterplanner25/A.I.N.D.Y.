"""Who may reach the routes that act beyond the caller's own data.

Starting a release handoff and deciding its gate use the stack's GitHub tokens, so they need an operator:
owning the handoff row proves nothing, because anyone could create that row. The Stripe webhook has no user
at all, so its signature is the only check, and without a secret it must refuse rather than skip that check.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid

import pytest

pytestmark = pytest.mark.app_profile

RELEASE_WRITES = [
    ("/apps/releases", {"tag": "v9.9.9"}),
    ("/apps/releases/some-handoff/approve", {}),
    ("/apps/releases/some-handoff/reject", {}),
]
WEBHOOK = "/apps/freelance/webhook/stripe"
SECRET = "whsec_test"
EVENT = json.dumps({"id": "evt_test", "type": "invoice.paid", "data": {"object": {}}}).encode()


def _signed_up_token(client) -> str:
    email = f"authz-{uuid.uuid4().hex[:8]}@aindy.test"
    password = "IntegrationTest1!"
    registered = client.post("/auth/register", json={"email": email, "password": password})
    assert registered.status_code in (200, 201, 202), registered.text[:300]
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text[:300]
    body = login.json()
    token = body.get("access_token") or (body.get("data") or {}).get("access_token")
    assert token, body
    return token


@pytest.fixture
def release_calls(monkeypatch):
    from apps.automation.services import release_handoff_service as rh

    calls = []
    monkeypatch.setattr(rh, "start_handoff", lambda *a, **k: calls.append("start") or {"id": "h1"})
    monkeypatch.setattr(rh, "decide", lambda *a, **k: calls.append("decide") or {"id": "h1"})
    return calls


@pytest.fixture
def stripe_events(monkeypatch):
    from apps.freelance.services import idempotency, webhook_service

    handled = []
    monkeypatch.setattr(idempotency, "claim_webhook_event", lambda *a, **k: True)
    monkeypatch.setattr(idempotency, "mark_webhook_outcome", lambda *a, **k: None)
    monkeypatch.setattr(webhook_service, "handle_stripe_event", lambda db, event: handled.append(event) or "ok")
    return handled


def _set_secret(monkeypatch, value: str) -> None:
    from AINDY.config import settings

    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", value)


def _signature(secret: str, payload: bytes) -> str:
    stamp = int(time.time())
    digest = hmac.new(secret.encode(), f"{stamp}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={stamp},v1={digest}"


@pytest.mark.parametrize("path, body", RELEASE_WRITES)
def test_a_signed_up_user_cannot_touch_a_release(client, release_calls, path, body):
    token = _signed_up_token(client)
    refused = client.post(path, json=body, headers={"Authorization": f"Bearer {token}"})
    assert refused.status_code == 403, refused.text[:300]
    assert release_calls == []


@pytest.mark.parametrize("path, body", RELEASE_WRITES)
def test_an_operator_reaches_the_release_service(app, client, release_calls, path, body):
    from AINDY.services.auth_service import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {"sub": str(uuid.uuid4()), "is_admin": True}
    answered = client.post(path, json=body)
    assert answered.status_code == 200, answered.text[:300]
    assert len(release_calls) == 1


def test_a_webhook_is_refused_when_no_secret_is_set(client, monkeypatch, stripe_events):
    _set_secret(monkeypatch, "")
    refused = client.post(WEBHOOK, content=EVENT)
    assert refused.status_code == 503, refused.text[:300]
    assert stripe_events == []


def test_a_signature_cannot_stand_in_for_a_missing_secret(client, monkeypatch, stripe_events):
    _set_secret(monkeypatch, "")
    refused = client.post(WEBHOOK, content=EVENT, headers={"stripe-signature": _signature("", EVENT)})
    assert refused.status_code == 503, refused.text[:300]
    assert stripe_events == []


def test_with_a_secret_an_unsigned_or_forged_webhook_is_refused(client, monkeypatch, stripe_events):
    _set_secret(monkeypatch, SECRET)
    assert client.post(WEBHOOK, content=EVENT).status_code == 400
    forged = client.post(WEBHOOK, content=EVENT, headers={"stripe-signature": _signature("wrong", EVENT)})
    assert forged.status_code == 400, forged.text[:300]
    assert stripe_events == []


def test_with_a_secret_a_signed_webhook_is_handled(client, monkeypatch, stripe_events):
    _set_secret(monkeypatch, SECRET)
    answered = client.post(WEBHOOK, content=EVENT, headers={"stripe-signature": _signature(SECRET, EVENT)})
    assert answered.status_code == 200, answered.text[:300]
    assert [event["id"] for event in stripe_events] == ["evt_test"]
