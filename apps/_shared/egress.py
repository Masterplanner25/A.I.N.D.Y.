"""Outbound connections to destinations a user chose reach public addresses only.

Two families of code connect where a user says:

- the automation connectors (webhook, CRM, social external delivery, email provider and SMTP),
  through :func:`public_urlopen` and :class:`PublicSMTP`;
- RippleTrace's content fetcher (ingest, feeds, citation checks), through
  :func:`public_requests_session`.

Without this module a destination could point at the stack itself (``postgres``, ``redis``,
``mailpit``, the api's own routes, a cloud metadata address), and the reply comes back to the
user in an automation log or as fetched text.

**The check happens at connect time, on the address actually connected.**
:func:`public_create_connection` resolves the host, refuses it unless EVERY address is public, and
connects to one of the addresses it checked. A check made earlier, followed by a library that
resolves again when it connects, is not enough: a hostname whose DNS answers differently the second
time (rebinding) gets through. Every redirect hop opens a new connection through the same function.

**Schemes:** :func:`public_urlopen` handles ``http`` and ``https`` only. urllib's default
opener also serves ``file://`` and ``ftp://``, which would read local files or bypass the
socket check. Environment proxies are ignored everywhere here: a proxy would move the connect.

The runtime's egress guard (``AINDY_EGRESS_ENFORCEMENT``) is a *domain allowlist*. That does
not fit here, because user webhooks and publisher URLs to any public host are the feature; the
danger is the private address, so that is what this refuses.

Moved from ``apps/automation/services/egress.py`` on 2026-11-07 so RippleTrace can use it too.
"""
from __future__ import annotations

import http.client
import ipaddress
import smtplib
import socket
from typing import Any
from urllib import request as urllib_request

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection as _U3HTTPConnection
from urllib3.connection import HTTPSConnection as _U3HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import ConnectTimeoutError, NameResolutionError, NewConnectionError


class BlockedDestination(PermissionError):
    """The destination resolves to an address that is not on the public internet."""


# IPv6 forms that carry an IPv4 address inside them. Python's `is_global` judges the IPv6
# prefix, not the IPv4 inside, so `64:ff9b::a00:1` (NAT64 for 10.0.0.1) reads as global. Where
# a network routes these, they reach the embedded address, so that address is what is judged.
_NAT64_PREFIXES = (
    ipaddress.ip_network("64:ff9b::/96"),  # RFC 6052 well-known prefix
    ipaddress.ip_network("64:ff9b:1::/48"),  # RFC 8215 local-use prefix
)


def _embedded_ipv4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip.sixtofour is not None:  # 2002::/16, 6to4
        return ip.sixtofour
    if ip.teredo is not None:  # 2001::/32; not global anyway, judged for completeness
        return ip.teredo[1]
    if any(ip in prefix for prefix in _NAT64_PREFIXES):
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def is_public_address(address: str) -> bool:
    """True only for a globally routable unicast address.

    An IPv6 address that embeds an IPv4 one (mapped, 6to4, Teredo, NAT64) must ALSO have a
    public IPv4 inside it.
    """
    ip = ipaddress.ip_address(str(address).split("%", 1)[0])
    if ip.version == 6:
        inner = _embedded_ipv4(ip)
        if inner is not None and not (inner.is_global and not inner.is_multicast):
            return False
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
    return bool(ip.is_global) and not ip.is_multicast


def public_create_connection(
    address: tuple[str, int],
    timeout: Any = socket._GLOBAL_DEFAULT_TIMEOUT,  # noqa: SLF001 - the stdlib's own sentinel
    source_address: Any = None,
    socket_options: Any = None,
    **_ignored: Any,
) -> socket.socket:
    """``socket.create_connection``, refusing any destination that is not public.

    ``timeout`` may be a number, ``None`` (blocking) or any library's "use the default"
    sentinel (the stdlib's and urllib3's differ); anything that is not a number or ``None``
    leaves the socket's default.
    """
    host, port = address
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not infos:
        raise BlockedDestination(f"outbound_destination_unresolved:{host}")
    for *_rest, sockaddr in infos:
        if not is_public_address(sockaddr[0]):
            raise BlockedDestination(f"outbound_destination_not_public:{host}")

    last_error: OSError | None = None
    for family, socktype, proto, _canonname, sockaddr in infos:
        sock = socket.socket(family, socktype, proto)
        try:
            for option in socket_options or ():
                sock.setsockopt(*option)
            if timeout is None or (isinstance(timeout, (int, float)) and not isinstance(timeout, bool)):
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            last_error = exc
            sock.close()
    raise last_error or OSError(f"outbound_connect_failed:{host}")


# ── urllib (automation connectors) ────────────────────────────────────────────────────────
#
# `HTTPConnection.__init__` assigns `self._create_connection = socket.create_connection` on the
# INSTANCE, so a class attribute would be shadowed and the guard never called. Set it after.
# HTTPSConnection.connect() calls the plain connect() first, so the TLS socket wraps a checked one.


class _PublicHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._create_connection = public_create_connection


class _PublicHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._create_connection = public_create_connection


class _PublicHTTPHandler(urllib_request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_PublicHTTPConnection, req)


class _PublicHTTPSHandler(urllib_request.HTTPSHandler):
    def https_open(self, req):
        kwargs: dict[str, Any] = {"context": self._context}
        if hasattr(self, "_check_hostname"):  # Python 3.11; gone in 3.12
            kwargs["check_hostname"] = self._check_hostname
        return self.do_open(_PublicHTTPSConnection, req, **kwargs)


def _build_opener() -> urllib_request.OpenerDirector:
    # Built by hand, not with build_opener(): that one adds the file, ftp and data handlers back.
    opener = urllib_request.OpenerDirector()
    for handler in (
        urllib_request.ProxyHandler({}),
        urllib_request.UnknownHandler(),
        _PublicHTTPHandler(),
        _PublicHTTPSHandler(),
        urllib_request.HTTPDefaultErrorHandler(),
        urllib_request.HTTPRedirectHandler(),
        urllib_request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    return opener


_OPENER = _build_opener()


def public_urlopen(req: urllib_request.Request | str, timeout: float = 15):
    """``urlopen`` for user-chosen URLs: http(s) only, public addresses only, redirects included."""
    url = req.full_url if isinstance(req, urllib_request.Request) else str(req)
    scheme = url.split(":", 1)[0].strip().lower()
    if scheme not in {"http", "https"}:
        raise BlockedDestination(f"outbound_scheme_not_allowed:{scheme or 'none'}")
    return _OPENER.open(req, timeout=timeout)


class PublicSMTP(smtplib.SMTP):
    """``smtplib.SMTP`` whose connection refuses any host that is not public."""

    def _get_socket(self, host, port, timeout):
        if timeout is not None and not timeout:
            raise ValueError("Non-blocking socket (timeout=0) is not supported")
        return public_create_connection((host, port), timeout, self.source_address)


# ── requests (RippleTrace's content fetcher) ──────────────────────────────────────────────
#
# urllib3 opens every connection in `HTTPConnection._new_conn`, through its own module-level
# `create_connection`. These subclasses open it through the guard instead, keeping urllib3's
# error mapping so `requests` still raises its usual exceptions. TLS (server name, certificate)
# is unchanged: HTTPSConnection wraps the socket `_new_conn` returns.


class _GuardedNewConn:
    def _new_conn(self) -> socket.socket:
        try:
            return public_create_connection(
                (self._dns_host, self.port),
                self.timeout,
                self.source_address,
                socket_options=self.socket_options,
            )
        except socket.gaierror as exc:
            raise NameResolutionError(self.host, self, exc) from exc
        except TimeoutError as exc:
            raise ConnectTimeoutError(self, f"Connection to {self.host} timed out.") from exc
        except OSError as exc:  # BlockedDestination included
            raise NewConnectionError(self, f"Failed to establish a new connection: {exc}") from exc


class _GuardedHTTPConnection(_GuardedNewConn, _U3HTTPConnection):
    pass


class _GuardedHTTPSConnection(_GuardedNewConn, _U3HTTPSConnection):
    pass


class _GuardedHTTPPool(HTTPConnectionPool):
    ConnectionCls = _GuardedHTTPConnection


class _GuardedHTTPSPool(HTTPSConnectionPool):
    ConnectionCls = _GuardedHTTPSConnection


class _PublicHTTPAdapter(HTTPAdapter):
    def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {"http": _GuardedHTTPPool, "https": _GuardedHTTPSPool}

    def proxy_manager_for(self, proxy, **proxy_kwargs):  # noqa: ARG002
        raise BlockedDestination("outbound_proxy_not_allowed")


def public_requests_session() -> requests.Session:
    """A ``requests`` session whose every connection goes through the guard.

    ``trust_env`` is off, so ``*_PROXY`` variables and ``.netrc`` are ignored.
    """
    session = requests.Session()
    session.trust_env = False
    adapter = _PublicHTTPAdapter()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session
