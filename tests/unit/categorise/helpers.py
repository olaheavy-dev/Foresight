from __future__ import annotations

from datetime import date
from functools import lru_cache
from itertools import count
from pathlib import Path

from backend.finance_core.categorise.normalise import parse_narration
from backend.finance_core.categorise.pack import CategorisationPack, load_pack
from backend.finance_core.types import Transaction

ROOT = Path(__file__).resolve().parents[3]
UK_PACK_PATH = ROOT / "backend" / "finance_core" / "locale_packs" / "uk.yaml"
_ids = count(1)


@lru_cache
def uk_pack() -> CategorisationPack:
    return load_pack(UK_PACK_PATH.read_text(encoding="utf-8"))


def txn(
    description: str,
    amount_minor: int,
    on: date = date(2026, 10, 1),
    bank_type: str | None = None,
    bank_category: str | None = None,
) -> Transaction:
    parsed = parse_narration(description, bank_type, uk_pack())
    return Transaction(
        id=f"txn_{next(_ids)}",
        account_id="acct_test",
        posted_on=on,
        amount_minor=amount_minor,
        currency="GBP",
        description=description,
        normalised=parsed.normalised,
        channel=parsed.channel,
        counterparty=parsed.counterparty,
        bank_category=bank_category,
    )
