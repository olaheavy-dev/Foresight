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


def test_loopback_is_allowed_and_the_guard_is_removed_after() -> None:
    assert ALLOWED_HOSTS == {"api.telegram.org"}  # the model provider's host is added per provider
    with egress_guard() as blocked:
        socket.getaddrinfo("localhost", 5432)
    assert blocked == []
    assert socket.getaddrinfo.__module__ == "socket"


def test_the_configured_provider_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Under MODEL_PROVIDER=openai, a live or recording ORC-13 run reaches OpenAI (Codex, #67)."""
    from backend.settings import get_settings
    from evals.egress import allowed_hosts

    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    get_settings.cache_clear()
    try:
        model_hosts = allowed_hosts() & {"api.openai.com", "api.meshapi.ai"}
        assert model_hosts == {"api.openai.com"}  # never the retired gateway too (Codex, #67)
        with egress_guard() as blocked:
            try:
                socket.getaddrinfo("api.openai.com", 443)
            except socket.gaierror:
                pass  # offline is fine: the guard let the lookup through
        assert blocked == []
    finally:
        get_settings.cache_clear()


def test_a_mesh_connection_is_blocked_under_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.settings import get_settings

    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    get_settings.cache_clear()
    try:
        with egress_guard() as blocked, pytest.raises(EgressBlocked):
            socket.getaddrinfo("api.meshapi.ai", 443)
        assert blocked == ["api.meshapi.ai:443"]
    finally:
        get_settings.cache_clear()
