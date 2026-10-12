from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from backend.finance_core.money import (
    MoneyError,
    add,
    detect_currency,
    exponent,
    format_money,
    parse_amount,
)
from backend.finance_core.types import Money


@pytest.mark.parametrize(
    ("code", "exp"), [("GBP", 2), ("INR", 2), ("EUR", 2), ("JPY", 0), ("KWD", 3)]
)
def test_iso_exponents(code: str, exp: int) -> None:
    assert exponent(code) == exp


def test_unknown_currency_is_rejected() -> None:
    with pytest.raises(MoneyError):
        exponent("XYZ")


@pytest.mark.parametrize(
    ("text", "currency", "dec", "grp", "minor"),
    [
        ("£2,184.50", "GBP", ".", ",", 218450),
        ("-£20.00", "GBP", ".", ",", -2000),
        ("−12.99", "GBP", ".", ",", -1299),
        ("(45.10)", "GBP", ".", ",", -4510),
        ("23.70 DR", "GBP", ".", ",", -2370),
        ("4,050.00 CR", "GBP", ".", ",", 405000),
        ("€1.234,56", "EUR", ",", ".", 123456),
        ("₹1,15,000.00", "INR", ".", ",", 11500000),
        ("¥12,800", "JPY", ".", ",", 12800),
        ("1.250 KWD", "KWD", ".", ",", 1250),
        ("0.00", "GBP", ".", ",", 0),
    ],
)
def test_parse_amount_exactly(text: str, currency: str, dec: str, grp: str, minor: int) -> None:
    assert parse_amount(text, currency, dec, grp) == minor


@pytest.mark.parametrize("text", ["12.345", "abc", ""])
def test_unrepresentable_amounts_are_errors(text: str) -> None:
    with pytest.raises(MoneyError):
        parse_amount(text, "GBP")


def test_zero_decimal_currency_rejects_fractions() -> None:
    with pytest.raises(MoneyError):
        parse_amount("12.5", "JPY")


@given(st.integers(min_value=-(10**12), max_value=10**12), st.sampled_from(["JPY", "GBP", "KWD"]))
def test_round_trip_dot_decimal(minor: int, currency: str) -> None:
    exp = exponent(currency)
    sign = "-" if minor < 0 else ""
    units, frac = divmod(abs(minor), 10**exp)
    text = f"{sign}{units:,}" + (f".{frac:0{exp}d}" if exp else "")
    assert parse_amount(text, currency, ".", ",") == minor


@given(st.integers(min_value=-(10**12), max_value=10**12), st.sampled_from(["JPY", "EUR", "KWD"]))
def test_round_trip_comma_decimal(minor: int, currency: str) -> None:
    exp = exponent(currency)
    sign = "-" if minor < 0 else ""
    units, frac = divmod(abs(minor), 10**exp)
    grouped = f"{units:,}".replace(",", ".")
    text = f"{sign}{grouped}" + (f",{frac:0{exp}d}" if exp else "")
    assert parse_amount(text, currency, ",", ".") == minor


def test_format_money() -> None:
    assert format_money(218450, "GBP") == "£2,184.50"
    assert format_money(-14800, "GBP") == "−£148.00"
    assert format_money(11500000, "INR", grouping="lakh") == "₹1,15,000.00"
    assert format_money(12800, "JPY") == "12,800 JPY"


def test_mixed_currency_addition_raises() -> None:
    assert add(Money(100, "GBP"), Money(50, "GBP")) == Money(150, "GBP")
    with pytest.raises(MoneyError):
        add(Money(100, "GBP"), Money(50, "EUR"))


def test_currency_ladder() -> None:
    assert detect_currency(currency_column_values=["GBP", "GBP"], home_currency="INR")[:2] == (
        "GBP",
        "column",
    )
    assert detect_currency(amount_samples=["€12,50"], home_currency="GBP")[:2] == ("EUR", "symbol")
    assert detect_currency(profile_currency="GBP", home_currency="INR")[:2] == ("GBP", "profile")
    assert detect_currency(home_currency="GBP")[:2] == ("GBP", "home_default")


def test_ambiguous_dollar_asks_instead_of_guessing() -> None:
    currency, provenance, question = detect_currency(amount_samples=["$12.00"], home_currency="GBP")
    assert currency is None
    assert provenance == "ambiguous"
    assert question is not None
    assert question.kind == "currency"
    assert "USD" in question.options
    assert question.preselected is None
