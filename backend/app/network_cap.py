"""A daily allowance per network for guests' AI work (hardening, 16 Oct 2026).

Per-profile limits (ask.py, proactive.py) reset when a visitor clears cookies and starts a new
guest profile, so on their own they let one network spend the whole day's Mesh budget. Guests'
questions and manual proactive checks are therefore also counted per network per UTC day.
Signed-in Google accounts keep only the per-profile limits.

The network is the visitor's address as the edge proxy saw it: `X-Forwarded-For` read from the
right, skipping private, loopback and link-local hops (the containers between Caddy and the
API), so the first public address is the one Caddy wrote. Caddy replaces any `X-Forwarded-For`
a client sends, so the value can't be spoofed through it. IPv4 is grouped by /24 and IPv6 by
/48, so one household or office counts once. No address is stored: only an HMAC of the day and
the network, kept in memory, which forgets everything at the end of the day or on a restart.
When no public address is found (local development, a misconfigured proxy), nothing is counted:
a mistake here can never lock out every visitor at once.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from fastapi import Request

from backend.settings import get_settings


def client_network(request: Request) -> str | None:
    """The visitor's network (an IPv4 /24 or IPv6 /48), or None when none is public."""
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",")]
    if request.client is not None:
        hops.append(request.client.host)
    for raw in reversed(hops):
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if not ip.is_global:
            continue  # a container hop (or a private network) between the edge and the API
        prefix = 24 if ip.version == 4 else 48
        return str(ipaddress.ip_network(f"{ip}/{prefix}", strict=False))
    return None


@dataclass
class NetworkAllowance:
    lock: threading.Lock = field(default_factory=threading.Lock)
    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    day: date | None = None

    def _key(self, network: str, kind: str, today: date) -> str:
        settings = get_settings()
        secret = (settings.session_secret or settings.google_oauth_client_secret).encode()
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

    def reset(self) -> None:
        with self.lock:
            self.counts.clear()
            self.day = None


allowance = NetworkAllowance()

REFUSED = (
    "Today’s guest allowance for your network is used. Sign in with Google to keep going, "
    "or come back tomorrow."
)
