"""Importers contain no bank-specific code: banks differ only in profile data (docs/00 §3)."""

from __future__ import annotations

from pathlib import Path

IMPORTERS = Path(__file__).resolve().parents[3] / "backend" / "finance_core" / "importers"
BANK_NAMES = ("monzo", "revolut", "lloyds", "barclays", "hsbc", "starling", "nationwide")
DATA_FILE = "builtin_profiles.py"


def test_no_bank_names_outside_profile_data() -> None:
    offenders = []
    for path in IMPORTERS.glob("*.py"):
        if path.name == DATA_FILE:
            continue
        text = path.read_text(encoding="utf-8").lower()
        offenders += [f"{path.name}: {b}" for b in BANK_NAMES if b in text]
    assert offenders == []
