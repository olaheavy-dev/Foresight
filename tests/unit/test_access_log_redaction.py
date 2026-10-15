"""OAuth codes never reach the access log (backend/app/logs.py)."""

from __future__ import annotations

import logging

from backend.app.logs import RedactAuthQuery, redact_path

CALLBACK = "/api/auth/google/callback?state=abc&code=4%2F0AXsecret&scope=openid"


def test_auth_queries_are_redacted_and_other_paths_kept() -> None:
    assert redact_path(CALLBACK) == "/api/auth/google/callback?[redacted]"
    assert redact_path("/api/auth/providers") == "/api/auth/providers"
    assert redact_path("/api/transactions?q=deliveroo") == "/api/transactions?q=deliveroo"


def test_the_filter_rewrites_uvicorn_access_records() -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4:5", "GET", CALLBACK, "1.1", 303),
        None,
    )
    assert RedactAuthQuery().filter(record)
    line = record.getMessage()
    assert "secret" not in line
    assert "code=" not in line
    assert "/api/auth/google/callback?[redacted]" in line
