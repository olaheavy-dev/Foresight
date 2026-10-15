"""Keep secrets out of the access log (AGENTS.md rule 1: OAuth secrets never appear in logs).

Google's sign-in callback carries a one-time authorization `code` and the `state` in its query
string, and uvicorn's access log prints the full path. The code is short-lived, single-use and
bound to our PKCE verifier, but it is still a credential, so the query of every `/api/auth/`
request is replaced before the line is written.
"""

from __future__ import annotations

import logging

REDACTED_PREFIXES = ("/api/auth/",)


def redact_path(full_path: str) -> str:
    path, sep, _query = full_path.partition("?")
    if sep and path.startswith(REDACTED_PREFIXES):
        return f"{path}?[redacted]"
    return full_path


class RedactAuthQuery(logging.Filter):
    """For uvicorn's access logger, whose args are (client, method, full_path, version, status)."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            record.args = (args[0], args[1], redact_path(args[2]), args[3], args[4])
        return True


def install() -> None:
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, RedactAuthQuery) for f in access.filters):
        access.addFilter(RedactAuthQuery())
