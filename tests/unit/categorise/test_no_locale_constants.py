"""Locale knowledge lives in the pack, never in engine code (roadmap LOC-01 acceptance)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENGINE_DIRS = [
    ROOT / "backend" / "finance_core" / "categorise",
    ROOT / "backend" / "finance_core" / "detect",
    ROOT / "backend" / "finance_core" / "calendar.py",
]
# Representative locale tokens: UK payment codes, merchants, payers, the country code.
FORBIDDEN = [
    "DEB",
    "BGC",
    "FPO",
    "FPI",
    "DD",
    "STO",
    "BACS",
    "DELIVEROO",
    "TESCO",
    "LEMFI",
    "KLARNA",
    "NETFLIX",
    "SKY",
    "HMRC",
    "DWP",
    "GB",
    "GBP",
    "ENG",
]


def _code_strings(path: Path) -> list[str]:
    """String literals in the file (docstrings and comments are allowed to mention examples)."""
    text = path.read_text(encoding="utf-8")
    text = re.sub(r'"""[\s\S]*?"""', "", text)
    text = re.sub(r"#.*", "", text)
    return re.findall(r"\"([^\"\n]*)\"|'([^'\n]*)'", text)  # type: ignore[return-value]


def test_no_locale_constants_in_engine_code() -> None:
    offenders = []
    files = [p for d in ENGINE_DIRS for p in ([d] if d.is_file() else d.rglob("*.py"))]
    for path in files:
        for groups in _code_strings(path):
            literal = next((g for g in groups if g), "")
            for token in FORBIDDEN:
                if re.search(rf"(?<![A-Za-z]){token}(?![A-Za-z])", literal):
                    offenders.append(f"{path.relative_to(ROOT)}: '{literal}' contains {token}")
    assert offenders == []
