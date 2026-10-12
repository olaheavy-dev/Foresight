"""Pre-commit and CI guard: block real personal financial data from entering the repo.

Blocks (docs/09 §17.1): UK sort codes next to a sort-code/account cue, 16-digit card numbers
that pass the Luhn check, NI numbers, statement files outside fixture folders, and any term on
a private deny-list kept OUTSIDE the repo (default ~/.foresight-private/denylist.txt, one term
per line). Dates such as 12-10-26 do not match the sort-code rule unless a cue is present.

Fixture folders are NOT a blanket exemption. A file there is treated as a fixture only if it is
registered in that folder's MANIFEST.sha256 ("<sha256>  <relative path>" per line) with a
matching hash; the generator writes the manifest and CI checks it against regenerated output
(docs/09 §16). Unregistered or modified files are scanned like any other file, and statement
files among them are blocked. Registered fixtures skip the identifier patterns (fictional data
may contain fake sort codes) but are still checked against the private deny-list.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

STATEMENT_SUFFIXES = {".pdf", ".csv", ".xls", ".xlsx"}
FIXTURE_DIRS = ("evals/datasets/", "evals/external/datasets/")
SKIP_DIRS = ("node_modules/", ".next/", ".git/")
DEFAULT_DENYLIST = Path.home() / ".foresight-private" / "denylist.txt"

SORT_CODE = re.compile(r"(?i)(sort\s*code|s/c|account)\D{0,20}(?<![\d-])\d{2}-\d{2}-\d{2}(?![\d-])")
NI_NUMBER = re.compile(r"\b(?!BG|GB|NK|KN|TN|NT|ZZ)[A-CEGHJ-PR-TW-Z]{2}\d{6}[A-D]\b")
CARD_CANDIDATE = re.compile(r"\b(?:\d[ -]?){15}\d\b")


def luhn_valid(number: str) -> bool:
    digits = [int(d) for d in number if d.isdigit()]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return len(digits) >= 13 and total % 10 == 0


def load_denylist(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [t.strip().lower() for t in lines if t.strip() and not t.startswith("#")]


def scan_text(text: str, denylist: list[str], patterns: bool = True) -> list[str]:
    findings = []
    if patterns and SORT_CODE.search(text):
        findings.append("UK sort code next to an account cue")
    if patterns and NI_NUMBER.search(text):
        findings.append("National Insurance number pattern")
    for match in CARD_CANDIDATE.finditer(text) if patterns else ():
        if luhn_valid(match.group()):
            findings.append("card number (passes Luhn)")
            break
    lowered = text.lower()
    findings += [f"private deny-list term #{i + 1}" for i, t in enumerate(denylist) if t in lowered]
    return findings


MANIFEST_NAME = "MANIFEST.sha256"


def load_manifests(root: Path) -> dict[str, str]:
    """Map repo-relative fixture paths to their registered sha256."""
    registered: dict[str, str] = {}
    for fixture_dir in FIXTURE_DIRS:
        manifest = root / fixture_dir / MANIFEST_NAME
        if not manifest.exists():
            continue
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            digest, _, rel = line.strip().partition("  ")
            registered[fixture_dir + rel.strip()] = digest.lower()
    return registered


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_registered_fixture(normalised: str, path: Path, manifest: dict[str, str]) -> bool:
    expected = manifest.get(normalised)
    return expected is not None and path.is_file() and _sha256(path) == expected


def scan_file(path: str, denylist: list[str], manifest: dict[str, str] | None = None) -> list[str]:
    normalised = path.replace(os.sep, "/")
    if any(part in normalised for part in SKIP_DIRS):
        return []
    file_path = Path(path)
    fixture = is_registered_fixture(normalised, file_path, manifest or {})
    if file_path.suffix.lower() in STATEMENT_SUFFIXES and not fixture:
        return ["statement file that is not a registered fixture (see MANIFEST.sha256)"]
    try:
        text = file_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
        return []
    return scan_text(text, denylist, patterns=not fixture)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*")
    parser.add_argument("--denylist", type=Path, default=DEFAULT_DENYLIST)
    args = parser.parse_args(argv)

    denylist = load_denylist(args.denylist)
    manifest = load_manifests(Path.cwd())
    failed = False
    for path in args.files:
        for finding in scan_file(path, denylist, manifest):
            print(f"{path}: {finding}", file=sys.stderr)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
