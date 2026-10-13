"""csv_statement on small inline fixtures shaped like real exports (all data fictional)."""

from __future__ import annotations

from datetime import date

import pytest

from backend.finance_core.importers import blocking_questions, import_file
from backend.finance_core.locale import load_locale_pack
from backend.finance_core.types import ReconciliationStatus

UK = load_locale_pack(
    "key: uk\ncountry: GB\nsubdivision: ENG\ndefault_currency: GBP\n"
    "locale: en-GB\ndate_order: DMY\n"
)

MONZO = (
    "Transaction ID,Date,Time,Type,Name,Emoji,Category,Amount,Currency,Local amount,"
    "Local currency,Notes and #tags,Address,Receipt,Description,Category split,Money Out,Money In\n"
    "tx_001,11/10/2025,19:50:24,Card payment,Amazon,,Shopping,0.00,GBP,0.00,GBP,Active card check,"
    ",,AMAZON EU,,0.00,\n"
    "tx_002,23/10/2025,15:18:14,Bacs (Direct Credit),Acme Analytics Ltd,,Income,4050.00,GBP,"
    "4050.00,GBP,,,,ACME SALARY,,,4050.00\n"
    "tx_003,24/10/2025,08:02:10,Card payment,Deliveroo,,Eating out,-24.80,GBP,-24.80,GBP,,,,"
    "DELIVEROO,,-24.80,\n"
)

REVOLUT = (
    '"Current Accounts Summaries",,,,,,,,,,,\n,,,,,,,,,,,\n"Personal Account (GBP)",,,,,,,,,,,\n'
    ',,,,,,,,,,,\n"Transaction statement",,,,,,,,,,,\n'
    'Date,Description,Category,"Money in/out",Balance,"Tax withheld","Other taxes",Fees,,,,\n'
    '"1 Sept 2026","Card shop",Merchant,-£20.00,£60.78,£0.00,£0.00,£0.00,,,,\n'
    '"2 Sept 2026","Payment from A Person","Top up",£280.00,£340.78,£0.00,£0.00,£0.00,,,,\n'
    "Total,,,£260.00,,£0.00,£0.00,£0.00,,,,\n---------,,,,,,,,,,,\n"
    '"Personal Account (USD)",,,,,,,,,,,\n"Transaction statement",,,,,,,,,,,\n'
    'Date,Description,Category,"Money in/out","Money in/out",Balance,"Tax withheld",,,,,\n'
    'Total,,,"$0.00",£0.00,,"$0.00",,,,,\n'
)

GENERIC = (
    "Date,Description,Paid out,Paid in,Balance\n"
    "01/10/2026,RENT NORTHSIDE LETTINGS SO,1250.00,,934.50\n"
    "02/10/2026,TESCO STORES DEB,45.10,,889.40\n"
    "28/10/2026,ACME ANALYTICS BGC,,4050.00,4939.40\n"
)


def run(text: str, **kw):  # type: ignore[no-untyped-def]
    return import_file("statement.csv", text.encode(), pack=UK, home_currency="GBP", **kw)


def test_monzo_export_uses_the_builtin_profile() -> None:
    result = run(MONZO)
    assert len(result.tables) == 1
    table = result.tables[0]
    r = table.result
    assert r.format_profile_id == "builtin.monzo_csv.v1"
    assert [row.external_id for row in r.rows] == ["tx_002", "tx_003"]  # £0.00 check skipped
    assert r.rows[0].amount_minor == 405000
    assert r.rows[1].amount_minor == -2480
    assert r.rows[1].bank_category == "Eating out"
    assert r.rows[1].description == "Deliveroo"
    assert r.detected_currency == "GBP"
    assert r.currency_provenance == "column"
    # No balance column: never "reconciled"; one non-blocking balance question.
    assert r.reconciliation.status == ReconciliationStatus.NOT_RECONCILABLE
    assert [q.kind for q in r.questions] == ["balance_today"]
    assert blocking_questions(r) == ()
    assert any("zero-value" in w for w in r.warnings)


def test_revolut_consolidated_statement_finds_the_pocket_table() -> None:
    result = run(REVOLUT)
    assert len(result.tables) == 1  # the empty USD pocket is skipped
    assert any("empty table" in w for w in result.warnings)
    table = result.tables[0]
    assert table.title == "Personal Account (GBP)"
    r = table.result
    assert r.format_profile_id == "builtin.revolut_consolidated_csv.v1"
    assert [row.posted_on for row in r.rows] == [date(2026, 9, 1), date(2026, 9, 2)]
    assert r.rows[1].balance_after_minor == 34078
    assert r.reconciliation.status == ReconciliationStatus.RECONCILED


def test_unknown_bank_with_balance_is_mapped_and_reconciled() -> None:
    r = run(GENERIC).tables[0].result
    assert r.format_profile_id is not None
    assert r.format_profile_id.startswith("heuristic.")
    assert [row.amount_minor for row in r.rows] == [-125000, -4510, 405000]
    assert r.reconciliation.status == ReconciliationStatus.RECONCILED
    assert r.questions == ()


def test_newest_first_files_reconcile() -> None:
    header, *rows = GENERIC.strip().split("\n")
    r = run("\n".join([header, *reversed(rows)]) + "\n").tables[0].result
    assert r.reconciliation.status == ReconciliationStatus.RECONCILED


@pytest.mark.parametrize(
    ("description", "mutate"),
    [
        ("broken running balance", lambda t: t.replace("889.40", "889.41")),
        ("dropped row", lambda t: t.replace("02/10/2026,TESCO STORES DEB,45.10,,889.40\n", "")),
        ("wrong sign convention", lambda t: t.replace("Paid out,Paid in", "Paid in,Paid out")),
        ("shifted column", lambda t: t.replace("TESCO STORES DEB,45.10", "45.10,TESCO STORES DEB")),
    ],
)
def test_corrupted_statements_are_rejected_with_a_row(description: str, mutate) -> None:  # type: ignore[no-untyped-def]
    r = run(mutate(GENERIC)).tables[0].result
    assert r.reconciliation.status == ReconciliationStatus.FAILED, description
    assert r.rows == ()  # nothing is committed
    assert r.reconciliation.failures
    assert all("row" in f for f in r.reconciliation.failures)


def test_ambiguous_dollar_blocks_until_answered() -> None:
    text = "Date,Description,Amount\n15/10/2026,Coffee,-$3.50\n16/10/2026,Refund,$3.50\n"
    r = run(text).tables[0].result
    assert r.rows == ()
    assert [q.kind for q in blocking_questions(r)] == ["currency"]
    answered = run(text, answers={"currency": "CAD"}).tables[0]
    assert answered.result.detected_currency == "CAD"
    assert [row.amount_minor for row in answered.result.rows] == [-350, 350]


def test_ambiguous_dates_block_then_the_answer_is_saved_on_the_profile() -> None:
    text = "Date,Description,Amount\n03/04/2026,Coffee,-£3.50\n05/06/2026,Lunch,-£8.00\n"
    first = run(text).tables[0].result
    assert first.rows == ()
    q = blocking_questions(first)[0]
    assert q.kind == "date_order"
    assert q.preselected == "DMY"
    answered = run(text, answers={"date_order": "DMY"}).tables[0]
    assert answered.result.rows[0].posted_on == date(2026, 4, 3)
    assert answered.profile is not None
    # Re-importing the same layout with the saved profile asks nothing.
    again = run(text, saved_profiles=[answered.profile]).tables[0].result
    assert blocking_questions(again) == ()
    assert again.rows[0].posted_on == date(2026, 4, 3)


def test_euro_comma_decimals_and_semicolons() -> None:
    text = (
        "Date;Description;Amount;Balance\n"
        "12.10.2026;Café;-1.234,56 €;8.765,44 €\n"
        "13.10.2026;Gehalt;2.000,00 €;10.765,44 €\n"
    )
    r = run(text).tables[0].result
    assert r.detected_currency == "EUR"
    assert [row.amount_minor for row in r.rows] == [-123456, 200000]
    assert r.reconciliation.status == ReconciliationStatus.RECONCILED


def test_unrecognised_columns_ask_for_a_mapping() -> None:
    text = "When,What,Sum,Notes\n2026-10-01,Coffee,3.50,x\n"
    result = run(text)
    if result.tables:
        assert [q.kind for q in blocking_questions(result.tables[0].result)] == ["columns"]
    else:
        assert result.message is not None


def test_pdf_and_spreadsheets_are_honestly_not_supported_yet() -> None:
    pdf = import_file("s.pdf", b"%PDF-1.7 ...", pack=UK, home_currency="GBP")
    assert pdf.importer == "pdf_statement"
    assert pdf.tables == ()
    assert pdf.message is not None
    assert "aren't supported yet" in pdf.message
    xlsx = import_file("s.xlsx", b"PK\x03\x04rest", pack=UK, home_currency="GBP")
    assert xlsx.tables == ()
    assert xlsx.message is not None
