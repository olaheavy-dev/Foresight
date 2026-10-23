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


def test_behind_a_cdn_the_edges_header_or_trusted_ranges_name_the_visitor(
    monkeypatch: Any,
) -> None:
    """#59 review: behind a public CDN the rightmost public hop is the CDN, which would make
    everyone behind it share one allowance. A configured header, or trusted proxy ranges,
    name the visitor instead."""
    from backend.settings import get_settings

    cdn_edge = "104.16.0.10"  # a public CDN address in front of the proxy
    chain = f"81.2.69.160, {cdn_edge}"
    assert _net(chain) == "104.16.0.0/24"  # unconfigured: the CDN is taken for the visitor

    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "104.16.0.0/13, 2400:cb00::/32")
    get_settings.cache_clear()
    assert _net(chain) == "81.2.69.0/24"

    monkeypatch.delenv("TRUSTED_PROXY_CIDRS")
    monkeypatch.setenv("CLIENT_IP_HEADER", "CF-Connecting-IP")
    get_settings.cache_clear()
    req: Any = _Req(chain)
    req.headers["CF-Connecting-IP"] = "81.2.69.161"
    assert client_network(req) == "81.2.69.0/24"
    req.headers["CF-Connecting-IP"] = "10.0.0.1"
    assert client_network(req) == "104.16.0.0/24"  # not a public value: X-Forwarded-For instead
    get_settings.cache_clear()


def test_a_configured_header_that_never_arrives_still_counts_the_visitor(monkeypatch: Any) -> None:
    """23 Oct 2026: CLIENT_IP_HEADER=CF-Connecting-IP on a server Cloudflare doesn't proxy. No
    request carries the header, and a request with no network isn't counted, so the guest cap was
    lifted for everyone. Without the header the visitor comes from X-Forwarded-For as usual."""
    from backend.settings import get_settings

    monkeypatch.setenv("CLIENT_IP_HEADER", "CF-Connecting-IP")
    get_settings.cache_clear()
    try:
        assert _net("81.2.69.160, 172.18.0.5") == "81.2.69.0/24"
        cap = NetworkAllowance()
        visitor: Any = _Req("81.2.69.160")
        assert cap.take(visitor, "question", 1)
        assert not cap.take(visitor, "question", 1)  # the second question is refused
    finally:
        get_settings.cache_clear()


def test_a_use_that_never_started_is_given_back() -> None:
    cap = NetworkAllowance()
    req: Any = _Req("81.2.69.160")
    now = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
    assert cap.take(req, "question", 1, now=now)
    assert not cap.take(req, "question", 1, now=now)
    cap.give_back(req, "question", now=now)  # the run failed to start
    assert cap.take(req, "question", 1, now=now)


def test_without_a_configured_secret_the_code_uses_a_random_process_key(monkeypatch: Any) -> None:
    """#59 review: an empty HMAC key would let anyone enumerate the few possible networks."""
    import hashlib
    import hmac as hmac_mod

    from backend.settings import get_settings

    monkeypatch.setenv("SESSION_SECRET", "")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
    get_settings.cache_clear()
    cap = NetworkAllowance()
    day = datetime(2026, 10, 17, tzinfo=timezone.utc).date()
    key = cap._key("81.2.69.0/24", "question", day)
    public = hmac_mod.new(b"", f"{day}|question|81.2.69.0/24".encode(), hashlib.sha256).hexdigest()
    assert key != public
    get_settings.cache_clear()


def test_an_ipv4_mapped_address_is_grouped_as_the_ipv4_it_carries() -> None:
    """#59 review: ::ffff:81.2.69.160 is the IPv4 visitor 81.2.69.160, so its /24, never ::/48
    shared by every such visitor."""
    assert _net("::ffff:81.2.69.160") == "81.2.69.0/24"
    assert _net("::ffff:10.0.0.1") is None  # a private IPv4 carried the same way counts nothing
