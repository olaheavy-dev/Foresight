"""csv_statement on small inline fixtures shaped like real exports (all data fictional)."""

from __future__ import annotations

import json
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


ODD_BANK = (
    "Posted On,Payee Text,Value (GBP),Running Total,Ref\n"
    "01/10/2026,SALARY ACME LTD,2100.00,2600.00,A1\n"
    "02/10/2026,TESCO STORES,-42.10,2557.90,A2\n"
    "03/10/2026,RENT OCTOBER,-950.00,1607.90,A3\n"
    "15/10/2026,DELIVEROO,-18.40,1589.50,A4\n"
)
ODD_MAPPING = json.dumps(
    {
        "date": "posted on",
        "description": "payee text",
        "amount": "value (gbp)",
        "balance": "running total",
    }
)


def test_unrecognised_columns_come_with_examples_and_what_was_recognised() -> None:
    """R5: the question can be answered: each column shows an example, and anything recognised
    is pre-filled."""
    (table,) = run(ODD_BANK).tables
    (q,) = blocking_questions(table.result)
    assert q.kind == "columns"
    assert q.options == ("c0", "c1", "c2", "c3", "c4")  # opaque positions
    assert q.labels == ("posted on", "payee text", "value (gbp)", "running total", "ref")
    assert q.table_id
    assert q.examples[0] == "01/10/2026"
    assert q.examples[1] == "SALARY ACME LTD"
    assert ("amount", "c2") in q.proposed


def test_a_column_mapping_answer_imports_and_reconciles() -> None:
    (table,) = run(ODD_BANK, answers={"columns": ODD_MAPPING}).tables
    assert not blocking_questions(table.result)
    assert len(table.result.rows) == 4
    assert table.result.reconciliation.status == ReconciliationStatus.RECONCILED
    assert table.profile is not None
    assert table.profile.origin == "user_confirmed"
    assert table.profile.profile_id.startswith("user.")
    # Saved, the profile makes the next export from this bank silent.
    (again,) = run(ODD_BANK, saved_profiles=[table.profile]).tables
    assert not blocking_questions(again.result)
    assert len(again.result.rows) == 4


@pytest.mark.parametrize(
    ("mapping", "why"),
    [
        ('{"date": "posted on", "amount": "value (gbp)"}', "need a date, a description"),
        # A mapping naming a column this table lacks doesn't apply to it: the question returns.
        (
            '{"date": "posted on", "description": "payee text", "amount": "nope"}',
            "didn’t recognise",
        ),
        (
            '{"date": "posted on", "description": "posted on", "amount": "value (gbp)"}',
            "only be used once",
        ),
    ],
)
def test_an_unusable_mapping_asks_again_and_says_why(mapping: str, why: str) -> None:
    (table,) = run(ODD_BANK, answers={"columns": mapping}).tables
    (q,) = blocking_questions(table.result)
    assert q.kind == "columns"
    assert why in q.prompt
    assert not table.result.rows


def test_examples_never_show_account_identifiers() -> None:
    """#42 (Codex review): examples come from the owner's file, but identifiers stay inside."""
    text = (
        "Posted On,Account Number,Payee Text,Value (GBP)\n"
        "01/10/2026,12345678,TRANSFER TO 40-11-62 87654321,-25.00\n"
        "15/10/2026,12345678,CARD SHOP,-4.20\n"
    )
    (table,) = run(text).tables
    (q,) = blocking_questions(table.result)
    assert q.examples[1] == ""  # an identifier column shows no example at all
    assert "87654321" not in q.examples[2]
    assert "••••" in q.examples[2]
    assert q.examples[3] == "-25.00"  # amounts are kept
    assert q.examples[0] == "01/10/2026"  # dates are kept


def test_a_bare_account_number_under_an_unfamiliar_heading_is_masked() -> None:
    """#42 (Codex re-review): "12345678" looks like an amount but has no decimal, sign or symbol."""
    text = (
        "Posted On,Beneficiary,Payee Text,Value (GBP)\n"
        "01/10/2026,12345678,RENT,-950.00\n"
        "15/10/2026,12345678,SHOP,-4.20\n"
    )
    (table,) = run(text).tables
    (q,) = blocking_questions(table.result)
    assert q.examples[1] == "••••"
    assert q.examples[3] == "-950.00"


def test_a_mapped_amount_heading_sets_the_currency() -> None:
    """#42 (Codex review): "Value (USD)" in a GBP profile imports as USD, not GBP."""
    text = "Posted On,Payee Text,Value (USD)\n01/10/2026,SHOP,-12.50\n02/10/2026,PAY,100.00\n"
    mapping = json.dumps(
        {"date": "posted on", "description": "payee text", "amount": "value (usd)"}
    )
    (table,) = run(text, answers={"columns": mapping, "date_order": "DMY"}).tables
    assert not blocking_questions(table.result)
    assert {r.currency for r in table.result.rows} == {"USD"}


def test_each_unrecognised_table_takes_its_own_mapping() -> None:
    """#42 (Codex review): a file with two unknown tables is importable, one mapping each."""
    text = (
        '"Main account",,,\n"Transaction statement",,,\n'
        "Posted On,Payee Text,Value (GBP),Running Total\n"
        "01/10/2026,SALARY,100.00,100.00\n02/10/2026,SHOP,-10.00,90.00\n"
        "---------,,,\n"
        '"Savings pot",,,\n"Transaction statement",,,\n'
        "When Booked,Narrative,Sum (GBP),Pot Total\n"
        "03/10/2026,ROUND UP,0.50,0.50\n04/10/2026,ROUND UP,0.40,0.90\n"
    )
    first = {"date": "posted on", "description": "payee text", "amount": "value (gbp)"}
    second = {"date": "when booked", "description": "narrative", "amount": "sum (gbp)"}
    one = run(text, answers={"columns": json.dumps([first]), "date_order": "DMY"}).tables
    assert len(one) == 2
    assert [bool(blocking_questions(t.result)) for t in one] == [False, True]
    both = run(text, answers={"columns": json.dumps([first, second]), "date_order": "DMY"}).tables
    assert not any(blocking_questions(t.result) for t in both)
    assert [len(t.result.rows) for t in both] == [2, 2]


def test_headings_with_account_numbers_are_masked_and_options_are_opaque() -> None:
    """#42 (Codex): a heading like "Account 12345678" never reaches the browser verbatim."""
    text = (
        "Posted On,Account 12345678,Payee Text,Value (GBP)\n"
        "01/10/2026,x,RENT,-950.00\n15/10/2026,x,SHOP,-4.20\n"
    )
    (table,) = run(text).tables
    (q,) = blocking_questions(table.result)
    assert "12345678" not in " ".join(q.options + q.labels)
    assert q.labels[1] == "account ••••"


def test_a_recognised_currency_column_survives_a_manual_mapping() -> None:
    """#42 (Codex): `Currency` is recognised even when the other headings aren't."""
    text = (
        "Booked,Counterparty,Net,Currency\n01/10/2026,SHOP,-12.50,USD\n15/10/2026,PAY,100.00,USD\n"
    )
    mapping = json.dumps({"date": "c0", "description": "c1", "amount": "c2"})
    (table,) = run(text, answers={"columns": mapping}).tables
    assert not blocking_questions(table.result)
    assert {r.currency for r in table.result.rows} == {"USD"}


def test_a_mapping_bound_to_one_table_does_not_answer_a_wider_one() -> None:
    """#42 (Codex): table 2 has table 1's columns plus a balance; table 1's mapping mustn't
    silently import it without that balance."""
    text = (
        '"Main account",,,\n"Transaction statement",,,\n'
        "When Booked,Narrative,Sum (GBP)\n"
        "01/10/2026,SALARY,100.00\n15/10/2026,SHOP,-10.00\n"
        "---------,,,\n"
        '"Savings pot",,,\n"Transaction statement",,,\n'
        "When Booked,Narrative,Sum (GBP),Pot Total\n"
        "03/10/2026,ROUND UP,0.50,0.50\n16/10/2026,ROUND UP,0.40,0.90\n"
    )
    first_q, second_q = (blocking_questions(t.result)[0] for t in run(text).tables)
    assert first_q.table_id != second_q.table_id
    first = {"table": first_q.table_id, "date": "c0", "description": "c1", "amount": "c2"}
    tables = run(text, answers={"columns": json.dumps([first])}).tables
    assert [bool(blocking_questions(t.result)) for t in tables] == [False, True]


def test_duplicate_headings_are_refused_with_a_clear_reason() -> None:
    """#42 (Codex, P2): two columns called "Net" can't be told apart by name. The table finder
    already refuses such a heading row; a mapping that reaches one is refused with the reason."""
    text = "Booked,Counterparty,Net,Net\n01/10/2026,SHOP,12.50,0.00\n15/10/2026,PAY,0.00,100.00\n"
    assert run(text).tables == ()
    from backend.finance_core.importers.csv_statement import manual_profile

    headers = ["Booked", "Counterparty", "Net", "Net"]
    chosen = {"date": "c0", "description": "c1", "money_out": "c2", "money_in": "c3"}
    profile, why = manual_profile(headers, chosen)
    assert profile is None
    assert why is not None
    assert "two columns called “net”" in why
