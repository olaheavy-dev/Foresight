"""File importers (docs/07 §5). Exactly two generic importers; bank knowledge lives in profiles.

`import_file` routes by content: PDF → `pdf_statement` (Tier 2, not shipped yet: an honest result,
not a crash), XLS/XLSX → not shipped yet (Tier 2), anything else → `csv_statement`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from backend.finance_core.importers.csv_statement import (
    BLOCKING_KINDS,
    TableImport,
    blocking_questions,
    import_csv,
)
from backend.finance_core.importers.profiles import FormatProfile, match_profile
from backend.finance_core.importers.table_locator import decode, locate_tables
from backend.finance_core.locale import LocalePack

__all__ = [
    "BLOCKING_KINDS",
    "CsvStatementSource",
    "Detection",
    "FileImport",
    "ImportSource",
    "TableImport",
    "blocking_questions",
    "import_file",
    "sniff",
]


@dataclass(frozen=True)
class Detection:
    importer: str  # "csv_statement" | "pdf_statement" | "spreadsheet"
    profile_id: str | None
    signals: tuple[str, ...]


@dataclass(frozen=True)
class FileImport:
    file_name: str
    importer: str
    file_sha256: str
    tables: tuple[TableImport, ...]
    message: str | None  # user-facing status when the file can't be imported (yet)
    warnings: tuple[str, ...] = ()


class ImportSource(Protocol):
    key: str

    def sniff(self, data: bytes, file_name: str) -> Detection: ...

    def parse(
        self,
        data: bytes,
        file_name: str,
        *,
        pack: LocalePack,
        home_currency: str,
        saved_profiles: Sequence[FormatProfile] = (),
        answers: Mapping[str, str] | None = None,
    ) -> FileImport: ...


def sniff(data: bytes, file_name: str) -> Detection:
    if data[:5] == b"%PDF-":
        return Detection("pdf_statement", None, ("pdf magic bytes",))
    if data[:4] == b"PK\x03\x04" or data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return Detection("spreadsheet", None, ("spreadsheet magic bytes",))
    from backend.finance_core.importers.builtin_profiles import BUILTIN_PROFILES

    tables = locate_tables(decode(data))
    profile = match_profile(tables[0].headers, BUILTIN_PROFILES) if tables else None
    signals = tuple(f"table: {t.title or 'untitled'} ({len(t.rows)} rows)" for t in tables)
    return Detection("csv_statement", profile.profile_id if profile else None, signals)


class CsvStatementSource:
    key = "csv_statement"

    def sniff(self, data: bytes, file_name: str) -> Detection:
        return sniff(data, file_name)

    def parse(
        self,
        data: bytes,
        file_name: str,
        *,
        pack: LocalePack,
        home_currency: str,
        saved_profiles: Sequence[FormatProfile] = (),
        answers: Mapping[str, str] | None = None,
    ) -> FileImport:
        tables, warnings = import_csv(
            data,
            pack=pack,
            home_currency=home_currency,
            saved_profiles=saved_profiles,
            answers=answers,
        )
        return FileImport(
            file_name,
            self.key,
            hashlib.sha256(data).hexdigest(),
            tables,
            None if tables else "We couldn't find a transaction table in this file.",
            warnings,
        )


def import_file(
    file_name: str,
    data: bytes,
    *,
    pack: LocalePack,
    home_currency: str,
    saved_profiles: Sequence[FormatProfile] = (),
    answers: Mapping[str, str] | None = None,
) -> FileImport:
    """Route a dropped file to its importer. Pure: the caller supplies the bytes."""
    detection = sniff(data, file_name)
    sha = hashlib.sha256(data).hexdigest()
    if detection.importer == "pdf_statement":
        return FileImport(
            file_name, "pdf_statement", sha, (),
            "PDF statements aren't supported yet. Please export a CSV from your bank.",
        )  # fmt: skip
    if detection.importer == "spreadsheet":
        return FileImport(
            file_name, "spreadsheet", sha, (),
            "Excel files aren't supported yet. Please export a CSV from your bank.",
        )  # fmt: skip
    return CsvStatementSource().parse(
        data,
        file_name,
        pack=pack,
        home_currency=home_currency,
        saved_profiles=saved_profiles,
        answers=answers,
    )
