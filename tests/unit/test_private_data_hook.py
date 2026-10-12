"""The privacy hook blocks planted identifiers. Values are assembled at runtime so this file
itself never contains a pattern the hook would block."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tools.check_no_private_data import load_manifests, luhn_valid, scan_file, scan_text


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


def test_statement_files_outside_fixtures_are_blocked(tmp_path: Path) -> None:
    stray = tmp_path / "statement.pdf"
    stray.write_bytes(b"%PDF-1.4")
    assert scan_file(str(stray), []) != []


@pytest.fixture
def fixture_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "evals" / "datasets").mkdir(parents=True)
    return tmp_path


def _register(root: Path, rel: str) -> None:
    path = root / "evals" / "datasets" / rel
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with (root / "evals" / "datasets" / "MANIFEST.sha256").open("a") as manifest:
        manifest.write(f"{digest}  {rel}\n")


def test_unregistered_file_in_fixture_folder_is_blocked(fixture_repo: Path) -> None:
    """Review finding: the fixture folder alone must not exempt a file."""
    planted = fixture_repo / "evals" / "datasets" / "copied.csv"
    planted.write_text("date,desc\n01/10/2026,sort code " + "-".join(["40", "11", "62"]))
    findings = scan_file("evals/datasets/copied.csv", [], load_manifests(fixture_repo))
    assert findings != []


def test_registered_fixture_is_allowed_but_still_checked_against_denylist(
    fixture_repo: Path,
) -> None:
    fixture = fixture_repo / "evals" / "datasets" / "p1.csv"
    fixture.write_text("date,desc\n01/10/2026,DELIVEROO\n")
    _register(fixture_repo, "p1.csv")
    manifest = load_manifests(fixture_repo)
    assert scan_file("evals/datasets/p1.csv", [], manifest) == []
    assert scan_file("evals/datasets/p1.csv", ["deliveroo"], manifest) != []


def test_modified_fixture_is_no_longer_trusted(fixture_repo: Path) -> None:
    fixture = fixture_repo / "evals" / "datasets" / "p1.csv"
    fixture.write_text("date,desc\n01/10/2026,DELIVEROO\n")
    _register(fixture_repo, "p1.csv")
    fixture.write_text("date,desc\n01/10/2026,a real row added later\n")
    assert scan_file("evals/datasets/p1.csv", [], load_manifests(fixture_repo)) != []
