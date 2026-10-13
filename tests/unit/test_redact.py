from __future__ import annotations

import pytest

from backend.mesh.redact import redact_text as redact


def test_masks_identifiers_but_keeps_merchant_text() -> None:
    card = " ".join(["4111", "1111", "1111", "1111"])
    text = f"DELIVEROO card {card} ref 41234567 to a.person@example.com via name@okicici"
    out = redact(text)
    assert "DELIVEROO" in out
    assert card not in out
    assert "41234567" not in out
    assert "example.com" not in out
    assert "okicici" not in out


def test_dates_are_not_mistaken_for_sort_codes() -> None:
    assert redact("12-10-2026") == "12-10-2026"


@pytest.mark.parametrize(
    "identifier",
    [
        "07700 900123",
        "07700900123",
        "+44 7700 900123",
        "+44 (0)20 7946 0000",
        "0161 496 0000",
        "+91 98765 43210",
        "98765 43210",
        "4123 4567",
    ],
)
def test_phone_and_grouped_account_numbers_are_masked(identifier: str) -> None:
    """Review finding: these formats used to reach Mesh unchanged."""
    out = redact(f"call {identifier} about the payment")
    assert identifier not in out
    assert "call" in out
    assert "about the payment" in out


@pytest.mark.parametrize("safe", ["£1,284.50", "12-10-2026", "2 Sept 2026"])
def test_amounts_and_dates_survive(safe: str) -> None:
    assert safe in redact(f"row {safe} end")


def test_retrieval_references_and_ni_numbers_are_masked() -> None:
    """Stricter than the retired text-only patterns: references never reach Mesh (docs/05 §7.3)."""
    out = redact("UPI/DR/412345678901 and NI QQ123456C")
    assert "412345678901" not in out
    assert "QQ123456C" not in out
