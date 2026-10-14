"""Outbound-connection guard for eval runs (docs/05 §3.1 rule 2, docs/09 ORC-13).

While installed, Python-level name lookups and socket connects are allowed only to the Mesh API,
the Telegram Bot API, the configured SMTP host and loopback; anything else raises `EgressBlocked`.
PostgreSQL is reached through libpq (C), not Python sockets, so the database is unaffected, which
matches the rule: the database is internal to the app network, not egress.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from backend.settings import get_settings

ALLOWED_HOSTS = frozenset({"api.meshapi.ai", "api.telegram.org"})


class EgressBlocked(ConnectionError):
    """An outbound connection to a host outside the allow-list."""


def allowed_hosts() -> frozenset[str]:
    smtp = (getattr(get_settings(), "smtp_host", "") or "").strip().lower()
    return ALLOWED_HOSTS | ({smtp} if smtp else set())


def _is_loopback(host: str) -> bool:
    if host in {"localhost", ""}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@contextmanager
def egress_guard() -> Iterator[list[str]]:
    """Install the guard; yields the list of blocked attempts (host:port), for reporting."""
    allowed = allowed_hosts()
    resolved: set[str] = set()
    blocked: list[str] = []
    real_getaddrinfo = socket.getaddrinfo
    real_connect = socket.socket.connect

    def getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
        name = (host.decode() if isinstance(host, bytes) else str(host or "")).lower()
        if not (_is_loopback(name) or name in allowed):
            blocked.append(f"{name}:{port}")
            raise EgressBlocked(f"outbound connection to {name} is not allowed")
        infos = real_getaddrinfo(host, port, *args, **kwargs)
        resolved.update(str(info[4][0]) for info in infos)
        return infos

    def connect(self: socket.socket, address: Any) -> Any:
        if self.family in (socket.AF_INET, socket.AF_INET6):
            host = str(address[0])
            if not (_is_loopback(host) or host in resolved or host in allowed):
                blocked.append(f"{host}:{address[1]}")
                raise EgressBlocked(f"outbound connection to {host} is not allowed")
        return real_connect(self, address)

    socket.getaddrinfo = getaddrinfo  # type: ignore[assignment]
    socket.socket.connect = connect  # type: ignore[method-assign]
    try:
        yield blocked
    finally:
        socket.getaddrinfo = real_getaddrinfo  # type: ignore[assignment]
        socket.socket.connect = real_connect  # type: ignore[method-assign]


__all__ = ["ALLOWED_HOSTS", "EgressBlocked", "allowed_hosts", "egress_guard"]
