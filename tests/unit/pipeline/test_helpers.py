"""Pure pipeline helpers: ids, pack loading and row ↔ engine-type conversions."""

from __future__ import annotations

from datetime import date

from backend.finance_core.importers.builtin_profiles import BUILTIN_PROFILES
from backend.finance_core.types import (
    Cadence,
    FlowKind,
    IncomeStream,
    PaydayRule,
    Provenance,
    RecurringObligation,
)
from backend.pipeline import ledger, packs
from backend.storage.ids import new_id, ulid


def test_ids_are_prefixed_and_time_sortable() -> None:
    assert new_id("txn").startswith("txn_")
    assert len(new_id("txn")) == 30
    assert ulid(1_000) < ulid(2_000) < ulid(10**12)
    assert len({new_id("calc") for _ in range(1000)}) == 1000


def test_uk_pack_loads_for_gb_workspaces() -> None:
    pack = packs.locale_pack("GB")
    assert (pack.key, pack.country, pack.subdivision) == ("uk", "GB", "ENG")
    assert (pack.default_currency, pack.date_order) == ("GBP", "DMY")
    holidays = packs.holidays("GB", (date(2027, 1, 1),))
    assert date(2027, 3, 26) in holidays  # Good Friday 2027


def test_format_profiles_round_trip_through_json() -> None:
    for profile in BUILTIN_PROFILES:
        assert ledger.profile(ledger.profile_json(profile)) == profile


def test_detections_round_trip_through_rows() -> None:
    stream = IncomeStream(
        key="inc_employer", source="EMPLOYER LTD", amount_minor=200000, currency="GBP",
        cadence=Cadence.MONTHLY,
        payday_rule=PaydayRule("fixed_day", day_of_month=25, december_day=20),
        provenance=Provenance.DETECTED, member_ids=("txn_a", "txn_b"),
    )  # fmt: skip
    assert ledger.income_stream(ledger.income_row(stream)) == stream
    four_weekly = PaydayRule("four_weekly", anchor_date=date(2026, 9, 4))
    assert ledger.payday_rule(ledger.payday_rule_json(four_weekly)) == four_weekly

    obligation = RecurringObligation(
        key="rob_rent", label="Rent", category_key="housing.rent", flow_kind=FlowKind.SPENDING,
        amount_minor=-90000, currency="GBP", cadence=Cadence.MONTHLY, anchor_day=1,
        active_months=frozenset({1, 2, 3}), member_ids=("txn_c",), is_commitment=False,
    )  # fmt: skip
    assert ledger.obligation(ledger.obligation_row(obligation)) == obligation
