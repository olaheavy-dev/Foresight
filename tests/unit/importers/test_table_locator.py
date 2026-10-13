"""The table locator on invented layouts (fictional banks and data, not the C1–C4 holdout)."""

from __future__ import annotations

from backend.finance_core.importers.table_locator import (
    is_amount_cell,
    is_date_cell,
    is_transaction_row,
    locate_tables,
)

# Header words the synonym lists don't know; an address preamble above the table.
PREAMBLE = (
    "Quarry Lane Mutual,,,\n"
    "12 Example Road,,,\n"
    "Account ending 0000,,,\n"
    ",,,\n"
    "Booked,Counterparty text,Outgoings,Incomings,Left over\n"
    "03/09/26,CORNER SHOP,4.20,,95.80\n"
    "04/09/26,EMPLOYER PLC,,1500.00,1595.80\n"
    "06/09/26,WATER CO,31.00,,1564.80\n"
)

# Two tables, CR/DR suffixes, totals block after each.
TWO_TABLES = (
    "Everyday account,,,,\n"
    "Ref,On,Item,Sum,Bal\n"
    "A1,2026-09-01,BAKERY,3.10 DR,96.90 CR\n"
    "A2,2026-09-02,REFUND,5.00 CR,101.90 CR\n"
    "Totals for period,,,8.10,\n"
    ",,,,\n"
    "Rainy day account,,,,\n"
    "Ref,On,Item,Sum,Bal\n"
    "B1,2026-09-01,INTEREST,0.12 CR,500.12 CR\n"
    "B2,2026-09-30,INTEREST,0.13 CR,500.25 CR\n"
    "Totals for period,,,0.25,\n"
)

# Semicolons and comma decimals.
SEMICOLON = "Tag;Zweck;Soll;Haben\n" "01.09.2026;MIETE;1.234,50;\n" "02.09.2026;GEHALT;;2.100,00\n"


def test_cells_recognise_dates_and_amounts() -> None:
    for text in ("07/10/26", "2026-10-07", "07.10.2026", "7 Oct 2026", "07-Oct-26", "2 Sept 2026"):
        assert is_date_cell(text), text
    for text in ("12.40", "(12.40)", "-£1,234.56", "1.234,50", "3.10 DR", "0.12 CR", "1500"):
        assert is_amount_cell(text), text
    for text in ("CORNER SHOP", "07/10/26", "Balance", ""):
        assert not is_amount_cell(text), text
    assert is_transaction_row(["03/09/26", "CORNER SHOP", "4.20", "", "95.80"])
    assert not is_transaction_row(["Totals for period", "", "", "8.10", ""])


def test_unknown_headers_after_a_preamble_are_found_by_shape() -> None:
    (table,) = locate_tables(PREAMBLE)
    assert table.header_row == 4
    assert table.headers[:3] == ("Booked", "Counterparty text", "Outgoings")
    assert [r for r, _ in table.rows] == [5, 6, 7]


def test_two_tables_with_totals_are_split_and_totals_excluded() -> None:
    tables = locate_tables(TWO_TABLES)
    assert [(t.header_row, [r for r, _ in t.rows]) for t in tables] == [
        (1, [2, 3]),
        (7, [8, 9]),
    ]
    assert [t.title for t in tables] == ["Everyday account", "Rainy day account"]


def test_semicolon_comma_decimal_table_is_found() -> None:
    (table,) = locate_tables(SEMICOLON)
    assert table.headers == ("Tag", "Zweck", "Soll", "Haben")
    assert len(table.rows) == 2


def test_summary_rows_without_dates_are_not_tables() -> None:
    text = (
        "Product,Opening,Out,In,Closing\n"
        "Current,100.00,20.00,280.00,360.00\n"
        "Savings,50.00,0.00,0.00,50.00\n"
    )
    assert locate_tables(text) == []
