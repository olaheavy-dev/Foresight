"""A daily allowance per network for guests' AI work (hardening, 16 Oct 2026).

Per-profile limits (ask.py, proactive.py) reset when a visitor clears cookies and starts a new
guest profile, so on their own they let one network spend the whole day's Mesh budget. Guests'
questions and manual proactive checks are therefore also counted per network per UTC day.
Signed-in Google accounts keep only the per-profile limits.

The network is the visitor's address as the edge saw it: `X-Forwarded-For` read from the right,
skipping private, loopback and link-local hops (the containers between the proxy and the API)
and any configured trusted proxies, so the first public address is the one the proxy wrote; the
proxy replaces any `X-Forwarded-For` a client sends. Behind a CDN, `CLIENT_IP_HEADER` names the
header the CDN sets instead (the origin must accept traffic from the CDN alone). IPv4 is grouped
by /24 and IPv6 by /48, so one household or office counts once. No address is stored: only an
HMAC of the day and the network, kept in memory and never written anywhere; it's cleared on the
first count after midnight (UTC) or on a restart.
When no public address is found (local development, a misconfigured proxy), nothing is counted:
a mistake here can never lock out every visitor at once.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from fastapi import Request

from backend.settings import get_settings


def client_network(request: Request) -> str | None:
    """The visitor's network (an IPv4 /24 or IPv6 /48), or None when none is public.

    With `CLIENT_IP_HEADER` set (a CDN in front of the proxy, e.g. CF-Connecting-IP), that
    header names the visitor. Otherwise `X-Forwarded-For` is read from the right, skipping
    private hops and any `TRUSTED_PROXY_CIDRS`, so a public CDN or proxy is never taken for the
    visitor and doesn't make everyone behind it share one allowance (#59 review)."""
    settings = get_settings()
    if settings.client_ip_header:
        return _network(request.headers.get(settings.client_ip_header, "").strip())
    trusted = _trusted(settings.trusted_proxy_cidrs)
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",")]
    if request.client is not None:
        hops.append(request.client.host)
    for raw in reversed(hops):
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if not ip.is_global or any(ip in net for net in trusted):
            continue  # a container hop, a private network, or a trusted proxy
        return _network(raw)
    return None


def _network(raw: str) -> str | None:
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return None
    if not ip.is_global:
        return None
    prefix = 24 if ip.version == 4 else 48
    return str(ipaddress.ip_network(f"{ip}/{prefix}", strict=False))


def _trusted(cidrs: str) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    out = []
    for part in cidrs.split(","):
        if part.strip():
            out.append(ipaddress.ip_network(part.strip(), strict=False))
    return out


_PROCESS_KEY = secrets.token_bytes(32)


@dataclass
class NetworkAllowance:
    lock: threading.Lock = field(default_factory=threading.Lock)
    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    day: date | None = None

    def _key(self, network: str, kind: str, today: date) -> str:
        settings = get_settings()
        # No configured secret (a guest-only setup): a random key for this process, so the code
        # can't be reversed by trying every network (#59 review). Counts are per process anyway.
        secret = (settings.session_secret or settings.google_oauth_client_secret).encode() or (
            _PROCESS_KEY
        )
        return hmac.new(secret, f"{today}|{kind}|{network}".encode(), hashlib.sha256).hexdigest()

    def take(self, request: Request, kind: str, limit: int, now: datetime | None = None) -> bool:
        """Count one use of `kind` for the request's network; False when today's are used."""
        network = client_network(request)
        if network is None or limit <= 0:
            return True
        today = (now or datetime.now(timezone.utc)).date()
        with self.lock:
            if self.day != today:  # a new day: yesterday's counts are forgotten
                self.counts.clear()
                self.day = today
            key = self._key(network, kind, today)
            if self.counts[key] >= limit:
                return False
            self.counts[key] += 1
            return True

    def give_back(self, request: Request, kind: str, now: datetime | None = None) -> None:
        """Return one use counted today for work that never started (a run that failed to
        start), so it doesn't use up the network's day."""
        network = client_network(request)
        if network is None:
            return
        today = (now or datetime.now(timezone.utc)).date()
        with self.lock:
            key = self._key(network, kind, today)
            if self.day == today and self.counts.get(key, 0) > 0:
                self.counts[key] -= 1

    def reset(self) -> None:
        with self.lock:
            self.counts.clear()
            self.day = None


allowance = NetworkAllowance()

REFUSED = (
    "Today’s guest allowance for your network is used. Sign in with Google to keep going, "
    "or come back tomorrow."
)
