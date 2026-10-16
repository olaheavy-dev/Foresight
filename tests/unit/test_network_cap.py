"""The per-network guest allowance (backend/app/network_cap.py): which address counts, the cap."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.app.network_cap import NetworkAllowance, client_network


class _Req:
    def __init__(self, xff: str = "", peer: str = "172.18.0.3") -> None:
        self.headers = {"x-forwarded-for": xff} if xff else {}
        self.client = type("C", (), {"host": peer})()


def _net(xff: str = "", peer: str = "172.18.0.3") -> str | None:
    req: Any = _Req(xff, peer)
    return client_network(req)


def test_the_first_public_address_from_the_right_is_the_visitors() -> None:
    assert _net("203.0.113.9") is None  # documentation range: not a global address
    assert _net("81.2.69.160") == "81.2.69.0/24"  # Caddy's value, then container hops
    assert _net("81.2.69.160, 172.18.0.5") == "81.2.69.0/24"
    # A value a client typed sits to the left of the one the edge wrote, so it never wins.
    assert _net("1.1.1.1, 81.2.69.160, 10.0.0.4") == "81.2.69.0/24"
    assert _net("2a00:1450:4009:81f::200e") == "2a00:1450:4009::/48"
    assert _net("not-an-ip, 81.2.69.7") == "81.2.69.0/24"


def test_no_public_address_counts_nothing_so_a_misconfiguration_never_locks_everyone_out() -> None:
    assert _net("", peer="127.0.0.1") is None
    assert _net("10.1.2.3, 172.18.0.5") is None
    cap = NetworkAllowance()
    req: Any = _Req("10.1.2.3")
    assert all(cap.take(req, "question", 1) for _ in range(5))


def test_the_cap_counts_per_network_and_kind_and_forgets_at_the_end_of_the_day() -> None:
    cap = NetworkAllowance()
    home: Any = _Req("81.2.69.160")
    same_network: Any = _Req("81.2.69.44")
    elsewhere: Any = _Req("82.165.10.1")
    day = datetime(2026, 10, 17, 9, tzinfo=timezone.utc)
    assert cap.take(home, "question", 2, day)
    assert cap.take(same_network, "question", 2, day)  # the same /24 shares the allowance
    assert not cap.take(home, "question", 2, day)
    assert cap.take(elsewhere, "question", 2, day)
    assert cap.take(home, "check", 2, day)  # each kind has its own count
    assert cap.take(home, "question", 2, datetime(2026, 10, 18, 0, 1, tzinfo=timezone.utc))
    assert all("81.2.69" not in key for key in cap.counts)  # no address is kept
