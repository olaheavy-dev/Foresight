"""The eval egress guard (docs/05 §3.1 rule 2, docs/09 ORC-13): no outbound connection except the
allow-listed hosts; loopback stays reachable."""

from __future__ import annotations

import socket

import pytest

from evals.egress import ALLOWED_HOSTS, EgressBlocked, egress_guard


def test_other_hosts_are_blocked_before_any_network_use() -> None:
    with egress_guard() as blocked, pytest.raises(EgressBlocked):
        socket.getaddrinfo("example.org", 443)
    assert blocked == ["example.org:443"]


def test_raw_ip_connects_outside_the_allow_list_are_blocked() -> None:
    with egress_guard() as blocked:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(EgressBlocked):
                sock.connect(("203.0.113.7", 443))  # TEST-NET-3, never routable
        finally:
            sock.close()
    assert blocked == ["203.0.113.7:443"]


def test_loopback_and_mesh_are_allowed_and_the_guard_is_removed_after() -> None:
    assert "api.meshapi.ai" in ALLOWED_HOSTS
    with egress_guard() as blocked:
        socket.getaddrinfo("localhost", 5432)
    assert blocked == []
    assert socket.getaddrinfo.__module__ == "socket"
