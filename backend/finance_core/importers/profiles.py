"""FormatProfile: bank knowledge as data (docs/07 §3.2, §5).

A profile maps a table's columns to roles and fixes its date/number formats and skip rules. The
CSV importer contains no bank-specific code; banks differ only in the profile they match.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from backend.finance_core.locale import DateFormat

ROLES = (
    "date", "time", "description", "amount", "money_in", "money_out", "balance", "id",
    "bank_category", "bank_type", "currency",
)  # fmt: skip


def normalise_header(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace('"', "").strip().lower())


@dataclass(frozen=True)
class FormatProfile:
    profile_id: str
    label: str
    # Normalised header tokens that must all be present for this profile to match.
    header_signature: tuple[str, ...]
    # role -> header names (normalised). Several names mean "first non-empty value wins".
    columns: dict[str, tuple[str, ...]]
    date_format: DateFormat | None = None
    decimal_sep: str | None = None  # None = infer from the file
    group_sep: str | None = None
    # "signed": one amount column, negative = out. "in_out": separate money in / money out
    # columns holding magnitudes (a value in money out is an outflow whatever its sign).
    sign_convention: str = "signed"
    skip_zero_amount: bool = False
    currency: str | None = None  # fixed currency, if the format implies one
    origin: str = "builtin"  # builtin | heuristic | proposed | user_confirmed
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_balance(self) -> bool:
        return bool(self.columns.get("balance"))


def match_profile(
    headers: Sequence[str], profiles: Sequence[FormatProfile]
) -> FormatProfile | None:
    """The first profile whose whole signature is present; saved profiles should come first."""
    present = {normalise_header(h) for h in headers}
    best: FormatProfile | None = None
    best_len = 0
    for profile in profiles:
        if all(tok in present for tok in profile.header_signature):
            if len(profile.header_signature) > best_len:
                best, best_len = profile, len(profile.header_signature)
    return best


def column_index(headers: Sequence[str], names: Sequence[str]) -> list[int]:
    """Indexes of the first occurrence of each named header (duplicate headers: first wins)."""
    norm = [normalise_header(h) for h in headers]
    out: list[int] = []
    for name in names:
        if name in norm:
            out.append(norm.index(name))
    return out
