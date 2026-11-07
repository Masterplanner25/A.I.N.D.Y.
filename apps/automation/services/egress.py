"""Outbound connections to destinations a user chose reach public addresses only.

The automation connectors (webhook, CRM, social external delivery, email provider and SMTP)
connect wherever the task's ``automation_config`` says, and any signed-in user writes that
config. Without this module a config could point at the stack itself (``postgres``,
``redis``, the api's own routes, a cloud metadata address) and read the answer back from the
automation log.

**The check happens at connect time.** :func:`public_create_connection` resolves the host,
refuses it unless EVERY address is public, and connects to one of the addresses it checked.
A hostname that resolves differently between a check and the connect cannot slip past, and
every redirect hop opens a new connection through it.

**Schemes:** :func:`public_urlopen` handles ``http`` and ``https`` only. urllib's default
opener also serves ``file://`` and ``ftp://``, which would read local files or bypass the
socket check.

The runtime's egress guard (``AINDY_EGRESS_ENFORCEMENT``) is a *domain allowlist*. That does
not fit here, because user webhooks to any public host are the feature; the danger is the
private address, so that is what this refuses.
"""
from __future__ import annotations

import http.client
import ipaddress
import smtplib
import socket
from typing import Any
from urllib import request as urllib_request


class BlockedDestination(PermissionError):
    """The destination resolves to an address that is not on the public internet."""


def is_public_address(address: str) -> bool:
    """True only for a globally routable unicast address (IPv4-mapped IPv6 judged as IPv4)."""
    ip = ipaddress.ip_address(str(address).split("%", 1)[0])
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return bool(ip.is_global) and not ip.is_multicast


def public_create_connection(
    address: tuple[str, int],
    timeout: Any = socket._GLOBAL_DEFAULT_TIMEOUT,  # noqa: SLF001 - the stdlib's own sentinel
    source_address: Any = None,
    **_ignored: Any,
) -> socket.socket:
    """``socket.create_connection``, refusing any destination that is not public."""
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
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:  # noqa: SLF001
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            last_error = exc
            sock.close()
    raise last_error or OSError(f"outbound_connect_failed:{host}")


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
    # Built by hand, not with build_opener(): that one adds the file, ftp and data handlers
    # back. ProxyHandler({}) ignores *_PROXY variables, which would move the connect to a proxy.
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
