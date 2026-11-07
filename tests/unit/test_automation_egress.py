"""User-chosen automation destinations reach public addresses only, and Stripe's server key
is the operator's alone.

Any signed-in user writes a task's `automation_config`. Before this guard the webhook, CRM,
social-external and email connectors connected wherever it said, including the stack's own
services, and the reply came back in the automation log; urllib's default opener also served
`file://`. These tests drive the real opener and socket path, faking only DNS.
"""

from __future__ import annotations

import http.server
import threading
from types import SimpleNamespace

import pytest

import AINDY.platform_layer.external_call_service as ecs
import apps.automation.services.automation_execution_service as aes
from apps._shared import egress

pytestmark = pytest.mark.app_profile


@pytest.fixture(autouse=True)
def _register_connectors():
    aes.register_automation_connectors(overwrite=True)


@pytest.fixture
def run_operations(monkeypatch):
    """Let ctx.call run its operation; the guard under test is inside the operation."""

    def fake_authorized(*, operation, **_kw):
        return operation()

    monkeypatch.setattr(ecs, "authorized_external_call", fake_authorized)


# ── Address classification ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.5",
        "172.18.0.3",  # a compose network
        "192.168.0.122",
        "169.254.169.254",  # cloud metadata
        "100.64.0.1",  # carrier-grade NAT
        "0.0.0.0",
        "::1",
        "fe80::1",
        "fd00::1",
        "::ffff:127.0.0.1",  # IPv4-mapped loopback
        "224.0.0.1",
        "64:ff9b::a00:1",  # NAT64 (well-known prefix) for 10.0.0.1
        "64:ff9b::7f00:1",  # NAT64 for 127.0.0.1
        "64:ff9b:1::a00:1",  # NAT64 local-use prefix
        "2002:a00:1::1",  # 6to4 for 10.0.0.1
        "2002:a9fe:a9fe::1",  # 6to4 for 169.254.169.254
    ],
)
def test_non_public_addresses_are_refused(address):
    assert egress.is_public_address(address) is False


@pytest.mark.parametrize(
    "address",
    # No 6to4 (2002::/16) case here: Python 3.11.10+ marks the whole prefix non-global, so even a
    # 6to4 address carrying a public IPv4 is refused on the deployed 3.11.18. Older 3.11 read it as
    # global, which is why the embedded-address check exists; refusing it is the safe outcome on both.
    ["93.184.215.14", "8.8.8.8", "2606:4700:4700::1111", "64:ff9b::808:808"],
)
def test_public_addresses_are_allowed(address):
    assert egress.is_public_address(address) is True


def _fake_dns(monkeypatch, table: dict[str, str]):
    real = egress.socket.getaddrinfo

    def fake_getaddrinfo(host, port, *args, **kwargs):
        if host in table:
            return real(table[host], port, *args, **kwargs)
        return real(host, port, *args, **kwargs)

    monkeypatch.setattr(egress.socket, "getaddrinfo", fake_getaddrinfo)


def test_connection_to_a_private_name_is_refused_before_connecting(monkeypatch):
    _fake_dns(monkeypatch, {"postgres": "172.18.0.2"})
    with pytest.raises(egress.BlockedDestination, match="not_public:postgres"):
        egress.public_create_connection(("postgres", 5432), 1)


def test_a_name_with_any_private_address_is_refused(monkeypatch):
    def mixed(host, port, *a, **k):
        import socket

        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", port)),
        ]

    monkeypatch.setattr(egress.socket, "getaddrinfo", mixed)
    with pytest.raises(egress.BlockedDestination):
        egress.public_create_connection(("rebind.example", 80), 1)


# ── The opener ────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x", "data:,hi", "gopher://x"])
def test_non_http_schemes_are_refused(url):
    with pytest.raises(egress.BlockedDestination, match="scheme_not_allowed"):
        egress.public_urlopen(url, timeout=1)


def test_loopback_url_is_refused():
    with pytest.raises(Exception) as excinfo:
        egress.public_urlopen("http://127.0.0.1:8000/health", timeout=1)
    assert "not_public" in str(excinfo.value)


class _RedirectToInternal(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib name
        self.send_response(302)
        self.send_header("Location", "http://internal.test/secret")
        self.end_headers()

    def log_message(self, *_a):
        pass


def test_a_redirect_to_a_private_address_is_refused(monkeypatch):
    """A public URL that redirects inward is stopped at the second connect."""
    server = http.server.HTTPServer(("127.0.0.1", 0), _RedirectToInternal)
    port = server.server_address[1]
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    try:
        _fake_dns(monkeypatch, {"public.test": "127.0.0.1", "internal.test": "10.0.0.7"})
        # Stand-in: treat this test server's loopback address as the "public" one.
        real_is_public = egress.is_public_address
        monkeypatch.setattr(
            egress, "is_public_address", lambda a: a == "127.0.0.1" or real_is_public(a)
        )
        with pytest.raises(Exception) as excinfo:
            egress.public_urlopen(f"http://public.test:{port}/", timeout=5)
        assert "not_public:internal.test" in str(excinfo.value)
    finally:
        server.server_close()
        thread.join(timeout=5)


def test_smtp_to_a_private_host_is_refused(monkeypatch):
    _fake_dns(monkeypatch, {"mailpit": "172.18.0.9"})
    with pytest.raises(egress.BlockedDestination, match="not_public:mailpit"):
        egress.PublicSMTP("mailpit", 1025, timeout=1)


# ── requests (RippleTrace's content fetcher) ──────────────────────────────────────────


class _Ok(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib name
        body = b"<html><title>ok</title></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_a):
        pass


def test_the_requests_session_refuses_a_private_name(monkeypatch):
    import requests

    _fake_dns(monkeypatch, {"mailpit": "172.18.0.9"})
    with egress.public_requests_session() as session, pytest.raises(requests.ConnectionError) as excinfo:
        session.get("http://mailpit:8025/api/v1/messages", timeout=2)
    assert "not_public:mailpit" in str(excinfo.value)


def test_the_requests_session_still_fetches_a_public_page(monkeypatch):
    """A real request end to end through the guarded pool (the test server stands in for public)."""
    server = http.server.HTTPServer(("127.0.0.1", 0), _Ok)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    try:
        _fake_dns(monkeypatch, {"public.test": "127.0.0.1"})
        real_is_public = egress.is_public_address
        monkeypatch.setattr(egress, "is_public_address", lambda a: a == "127.0.0.1" or real_is_public(a))
        with egress.public_requests_session() as session:
            response = session.get(f"http://public.test:{server.server_address[1]}/", timeout=5)
        assert response.status_code == 200 and "ok" in response.text
    finally:
        server.server_close()
        thread.join(timeout=5)


def test_the_requests_session_ignores_proxy_variables(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://10.0.0.1:3128")
    monkeypatch.setenv("HTTPS_PROXY", "http://10.0.0.1:3128")
    with egress.public_requests_session() as session:
        assert session.trust_env is False


def test_content_fetch_refuses_a_rebinding_hostname(monkeypatch):
    """The early check sees a public address; the connect sees a private one. The connect wins."""
    import socket

    import AINDY.platform_layer.external_call_service as ecs
    from apps.rippletrace.services import content_fetch

    answers = iter(["93.184.215.14", "10.0.0.7", "10.0.0.7", "10.0.0.7"])
    real = socket.getaddrinfo

    def rebinding(host, port, *args, **kwargs):
        if host == "rebind.test":
            return real(next(answers), port, *args, **kwargs)
        return real(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", rebinding)
    monkeypatch.setattr(ecs, "perform_external_call", lambda *, operation, **_kw: operation())

    with pytest.raises(content_fetch.ContentFetchError) as excinfo:
        content_fetch.fetch_url("http://rebind.test/feed")
    assert "not_public:rebind.test" in str(excinfo.value)


def test_content_fetch_uses_the_guarded_session():
    import inspect

    from apps.rippletrace.services import content_fetch

    assert "public_requests_session()" in inspect.getsource(content_fetch.fetch_url)


# ── The connectors use the guard ──────────────────────────────────────────────────────


def test_the_connectors_use_the_guarded_opener_and_smtp():
    assert aes._open_user_url is egress.public_urlopen
    assert aes._SMTP is egress.PublicSMTP


def test_webhook_to_the_stack_itself_fails_without_a_response(run_operations, monkeypatch):
    _fake_dns(monkeypatch, {"api": "172.18.0.4"})
    with pytest.raises(ValueError, match="not_public:api"):
        aes.execute_automation_action(
            {
                "automation_type": "webhook",
                "user_id": "u1",
                "automation_config": {"url": "http://api:8000/platform/keys", "method": "GET"},
            },
            None,
        )


def test_webhook_file_url_is_refused(run_operations):
    with pytest.raises(ValueError, match="scheme_not_allowed"):
        aes.execute_automation_action(
            {
                "automation_type": "webhook",
                "user_id": "u1",
                "automation_config": {"url": "file:///etc/passwd"},
            },
            None,
        )


# ── Stripe's server key ───────────────────────────────────────────────────────────────


@pytest.fixture
def server_stripe_key(monkeypatch):
    from AINDY.config import settings

    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "sk_server")


def test_a_non_operator_cannot_use_the_server_stripe_key(server_stripe_key, monkeypatch):
    monkeypatch.setattr(aes, "_is_operator", lambda ctx: False)
    with pytest.raises(PermissionError, match="stripe_secret_key_required"):
        aes._stripe_key({}, SimpleNamespace(user_id="u1", db=object()))


def test_an_operator_uses_the_server_stripe_key(server_stripe_key, monkeypatch):
    monkeypatch.setattr(aes, "_is_operator", lambda ctx: True)
    assert aes._stripe_key({}, SimpleNamespace(user_id="u1", db=object())) == "sk_server"


def test_an_automation_may_bring_its_own_stripe_key(server_stripe_key, monkeypatch):
    monkeypatch.setattr(aes, "_is_operator", lambda ctx: False)
    assert aes._stripe_key({"stripe_secret_key": "sk_own"}, SimpleNamespace()) == "sk_own"


def test_no_server_key_means_no_key(monkeypatch):
    from AINDY.config import settings

    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", None)
    assert aes._stripe_key({}, SimpleNamespace(user_id="u1", db=object())) is None


@pytest.mark.parametrize(
    "ctx",
    [SimpleNamespace(user_id=None, db=object()), SimpleNamespace(user_id="u1", db=None),
     SimpleNamespace(user_id="not-a-uuid", db=object())],
)
def test_is_operator_fails_closed(ctx):
    assert aes._is_operator(ctx) is False


def test_stripe_connector_refuses_a_non_operator_end_to_end(run_operations, server_stripe_key, monkeypatch):
    monkeypatch.setattr(aes, "_is_operator", lambda ctx: False)
    with pytest.raises((PermissionError, ValueError), match="stripe_secret_key_required"):
        aes.execute_automation_action(
            {
                "automation_type": "subscription",
                "user_id": "u1",
                "automation_config": {"customer_email": "x@example.com", "amount": 100},
            },
            None,
        )
