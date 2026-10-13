"""Locale and categorisation packs for a workspace, loaded once per process from pack data."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from functools import lru_cache
from pathlib import Path

from backend.finance_core.categorise.pack import CategorisationPack, load_pack
from backend.finance_core.locale import LocalePack, holiday_dates, load_locale_pack

PACK_DIR = Path(__file__).resolve().parents[1] / "finance_core" / "locale_packs"
PACK_FILES = {"GB": "uk.yaml"}


class UnsupportedCountry(ValueError):
    pass


@lru_cache
def _pack_text(country: str) -> str:
    file = PACK_FILES.get(country.upper())
    if file is None:
        raise UnsupportedCountry(f"no locale pack for {country}")
    return (PACK_DIR / file).read_text(encoding="utf-8")


@lru_cache
def categorisation_pack(country: str) -> CategorisationPack:
    return load_pack(_pack_text(country))


@lru_cache
def locale_pack(country: str) -> LocalePack:
    return load_locale_pack(_pack_text(country))


def holidays(country: str, days: Iterable[date]) -> frozenset[date]:
    years = {d.year for d in days}
    if not years:
        return frozenset()
    span = range(min(years) - 1, max(years) + 2)
    return holiday_dates(locale_pack(country), span)
