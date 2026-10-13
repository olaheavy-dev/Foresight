"""The design fixture's paydays follow the uk pack rule, including bank holidays (docs/00 §10a)."""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import holidays

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "design" / "fixture"
sys.path.insert(0, str(FIXTURE_DIR))

import build_fixture  # noqa: E402

BANK_HOLIDAYS = holidays.country_holidays("GB", subdiv="ENG", years=[2026, 2027])


def test_march_2027_pay_moves_before_good_friday() -> None:
    assert date(2027, 3, 26) in BANK_HOLIDAYS  # Good Friday
    assert build_fixture.PAYDAYS[-1] == date(2027, 3, 25)


def test_every_payday_is_a_working_day_on_or_before_the_nominal_day() -> None:
    for pay in build_fixture.PAYDAYS:
        nominal = date(pay.year, pay.month, 18 if pay.month == 12 else 28)
        assert pay.weekday() < 5
        assert pay not in BANK_HOLIDAYS
        assert pay <= nominal
        # nothing between the payday and the nominal day is a working day
        d = pay + timedelta(days=1)
        while d <= nominal:
            assert d.weekday() >= 5 or d in BANK_HOLIDAYS, d
            d += timedelta(days=1)


def test_committed_fixture_matches_the_rule() -> None:
    fixture = json.loads((FIXTURE_DIR / "fixture.json").read_text(encoding="utf-8"))
    assert fixture["paydays"] == [p.isoformat() for p in build_fixture.PAYDAYS]
    for scenario, cycles in fixture["cycles"].items():
        ends = [c["cycle_end"] for c in cycles]
        expected = [(p - timedelta(days=1)).isoformat() for p in build_fixture.PAYDAYS]
        assert ends == expected, scenario
