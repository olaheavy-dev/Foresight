"""The privacy hook blocks planted identifiers. Values are assembled at runtime so this file
itself never contains a pattern the hook would block."""

from __future__ import annotations

from pathlib import Path

from tools.check_no_private_data import luhn_valid, scan_file, scan_text


def test_sort_code_with_cue_is_blocked() -> None:
    planted = "sort code " + "-".join(["40", "11", "62"])
    assert scan_text(planted, []) != []


def test_dates_are_not_sort_codes() -> None:
    assert scan_text("posted 12-10-26 and 01-11-26", []) == []


def test_card_numbers_need_luhn() -> None:
    valid = "4111" + "1111" * 3
    assert luhn_valid(valid)
    assert scan_text(f"card {valid}", []) != []
    assert scan_text("ref 1234567890123456", []) == []


def test_ni_number_is_blocked() -> None:
    assert scan_text("NI " + "AB" + "123456" + "C", []) != []


def test_denylist_terms_are_blocked() -> None:
    assert scan_text("payment to someone private", ["someone private"]) != []


def test_statement_files_only_allowed_in_fixture_folders(tmp_path: Path) -> None:
    stray = tmp_path / "statement.pdf"
    stray.write_bytes(b"%PDF-1.4")
    assert scan_file(str(stray), []) != []
    assert scan_file("evals/datasets/p1/monzo.csv", []) == []
