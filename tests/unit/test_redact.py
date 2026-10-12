from __future__ import annotations

from backend.mesh.mesh_client import redact


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
