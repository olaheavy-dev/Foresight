from __future__ import annotations

from datetime import date

import pytest

from backend.finance_core.locale import (
    DateFormat,
    LocalePackError,
    holiday_dates,
    infer_date_format,
    infer_number_format,
    load_locale_pack,
    parse_date,
)

PACK_YAML = """
key: uk
country: GB
subdivision: ENG
default_currency: GBP
locale: en-GB
date_order: DMY
numbers: {decimal_sep: ".", group_sep: ",", grouping: thousands}
narration_codes: {DD: direct_debit}
"""


@pytest.fixture
def pack():  # type: ignore[no-untyped-def]
    return load_locale_pack(PACK_YAML)


def test_pack_loads_data_and_keeps_extra(pack) -> None:  # type: ignore[no-untyped-def]
    assert pack.country == "GB"
    assert pack.default_currency == "GBP"
    assert pack.extra["narration_codes"] == {"DD": "direct_debit"}
    assert pack.month_names["sept"] == 9


def test_pack_missing_keys_is_an_error() -> None:
    with pytest.raises(LocalePackError):
        load_locale_pack("key: uk\n")


def test_england_holidays(pack) -> None:  # type: ignore[no-untyped-def]
    days = holiday_dates(pack, [2026])
    assert date(2026, 12, 25) in days
    assert date(2026, 12, 28) in days  # Boxing Day substitute (26 Dec is a Saturday)


@pytest.mark.parametrize(
    ("samples", "exp", "dec", "grp", "grouping"),
    [
        (["1,234.56", "12.50"], 2, ".", ",", "thousands"),
        (["1.234,56", "12,50"], 2, ",", ".", "thousands"),
        (["1,15,000.00", "2,340.00"], 2, ".", ",", "lakh"),
        (["12,800", "300"], 0, ".", ",", "thousands"),
    ],
)
def test_number_format_inference(samples, exp, dec, grp, grouping) -> None:  # type: ignore[no-untyped-def]
    fmt, question = infer_number_format(samples, exp)
    assert question is None
    assert fmt is not None
    assert (fmt.decimal_sep, fmt.group_sep, fmt.grouping) == (dec, grp, grouping)


def test_inconsistent_separators_ask() -> None:
    fmt, question = infer_number_format(["1,234.56", "1.234,56"], 2)
    assert fmt is None
    assert question is not None
    assert question.kind == "decimal_separator"


def test_date_order_inference(pack) -> None:  # type: ignore[no-untyped-def]
    assert infer_date_format(["13/10/2026", "01/11/2026"], pack)[0] == DateFormat("DMY")
    assert infer_date_format(["10/13/2026"], pack)[0] == DateFormat("MDY")
    assert infer_date_format(["2026-10-13"], pack)[0] == DateFormat("YMD")
    fmt, _ = infer_date_format(["2 Sept 2026", "11 Oct 2026"], pack)
    assert fmt == DateFormat("DMY", month_text=True)


def test_ambiguous_dates_ask_with_locale_preselected(pack) -> None:  # type: ignore[no-untyped-def]
    fmt, question = infer_date_format(["03/04/2026", "05/06/2026"], pack)
    assert fmt is None
    assert question is not None
    assert question.kind == "date_order"
    assert question.preselected == "DMY"


def test_saved_format_wins(pack) -> None:  # type: ignore[no-untyped-def]
    saved = DateFormat("MDY")
    assert infer_date_format(["03/04/2026"], pack, saved=saved) == (saved, None)


def test_parse_dates(pack) -> None:  # type: ignore[no-untyped-def]
    assert parse_date("2 Sept 2026", DateFormat("DMY", True), pack.month_names) == date(2026, 9, 2)
    assert parse_date("11/10/2025", DateFormat("DMY")) == date(2025, 10, 11)
    assert parse_date("01 Sep 26", DateFormat("DMY", True)) == date(2026, 9, 1)
    assert parse_date("2026-10-12", DateFormat("YMD")) == date(2026, 10, 12)
