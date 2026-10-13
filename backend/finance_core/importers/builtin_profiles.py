"""Built-in FormatProfiles. DATA ONLY.

This is the only place in the importers where a bank is named. Each entry describes a public
export format observed in real files; adding a bank means adding an entry here (or a user
confirming a proposed profile), never adding code.
"""

from __future__ import annotations

from backend.finance_core.importers.profiles import FormatProfile
from backend.finance_core.locale import DateFormat

BUILTIN_PROFILES: tuple[FormatProfile, ...] = (
    FormatProfile(
        profile_id="builtin.monzo_csv.v1",
        label="Monzo CSV export",
        header_signature=(
            "transaction id", "date", "time", "type", "name", "category", "amount", "currency",
        ),
        columns={
            "id": ("transaction id",),
            "date": ("date",),
            "time": ("time",),
            "bank_type": ("type",),
            "description": ("name", "description"),
            "bank_category": ("category",),
            "amount": ("amount",),
            # Monzo also writes each amount into Money Out / Money In: a cross-check only.
            "money_out": ("money out",),
            "money_in": ("money in",),
            "currency": ("currency",),
        },
        date_format=DateFormat(order="DMY"),
        decimal_sep=".",
        group_sep=",",
        sign_convention="signed",
        skip_zero_amount=True,  # £0.00 card-check rows
        notes=("No balance column: the user is asked for today's balance once.",),
    ),
    FormatProfile(
        profile_id="builtin.revolut_consolidated_csv.v1",
        label="Revolut consolidated statement (CSV)",
        header_signature=("date", "description", "category", "money in/out", "balance"),
        columns={
            "date": ("date",),
            "description": ("description",),
            "bank_category": ("category",),
            "amount": ("money in/out",),
            "balance": ("balance",),
        },
        date_format=DateFormat(order="DMY", month_text=True),  # "2 Sept 2026"
        decimal_sep=".",
        group_sep=",",
        sign_convention="signed",
        notes=("One table per currency pocket; empty pockets are skipped.",),
    ),
)  # fmt: skip
