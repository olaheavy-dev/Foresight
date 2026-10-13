"""backend/mesh/redact.py (docs/05 §7.3). Identifiers are assembled at runtime so this file does
not itself contain identifier-shaped strings (the privacy pre-commit scan reads tests too)."""

from __future__ import annotations

import json

import pytest

from backend.mesh.redact import default_merchants, redact, redact_text


def _j(*parts: str, sep: str = "") -> str:
    return sep.join(parts)


CARD = _j("4000", "1234", "5678", "9010", sep=" ")  # not Luhn-valid
SORT = _j("30", "94", "57", sep="-")  # not a plausible date (month 94)
ACCOUNT = _j("4123", "4567")
IBAN = _j("GB29", "NWBK", "6016", "1331", "9268", "19")
UK_MOBILE = _j("07700", " 900123")
IN_MOBILE = _j("+91 ", "98765", " 43210")
AADHAAR = _j("2345", "6789", "0123", sep=" ")
PAN = _j("ABCDE", "1234", "F")
IFSC = _j("HDFC", "0001234")
RRN = _j("4123", "4567", "8901")


@pytest.mark.parametrize(
    ("narration", "kept", "masked"),
    [
        (f"DEB TESCO STORES 2041 CARD {CARD}", ["DEB", "TESCO STORES"], [CARD]),
        ("DEB DELIVEROO ****1234", ["DEB", "DELIVEROO"], ["1234"]),
        ("DD OCTOPUS ENERGY", ["DD OCTOPUS ENERGY"], []),
        ("SO JOHN SMITH RENT", ["SO", "RENT"], ["JOHN SMITH"]),
        (f"FPO K MENSAH REF {ACCOUNT}", ["FPO"], ["K MENSAH", ACCOUNT]),
        ("FPI AMARA NWOSU", ["FPI"], ["AMARA NWOSU"]),
        ("FPO SEVERN TRENT", ["FPO SEVERN TRENT"], []),
        ("BGC ACME PAYROLL LTD", ["BGC ACME PAYROLL LTD"], []),
        (
            f"FASTER PAYMENT TO KOFI MENSAH SORT CODE {SORT} {ACCOUNT}",
            ["FASTER PAYMENT TO"],
            ["KOFI MENSAH", SORT, ACCOUNT],
        ),
        ("Transfer from Ama Owusu", ["Transfer from"], ["Ama Owusu"]),
        (f"call {UK_MOBILE} about the payment", ["call", "about the payment"], [UK_MOBILE]),
        (f"IBAN {IBAN}", [], [IBAN]),
    ],
)
def test_uk_narrations(narration: str, kept: list[str], masked: list[str]) -> None:
    out = redact_text(narration, locale_pack="uk")
    for k in kept:
        assert k in out, out
    for m in masked:
        assert m not in out, out


@pytest.mark.parametrize(
    ("narration", "kept", "masked"),
    [
        (
            f"UPI/DR/{RRN}/Ravi Kumar/HDFC/ravi@okhdfc",
            ["UPI/DR/", "HDFC"],
            [RRN, "Ravi Kumar", "ravi@okhdfc"],
        ),
        (f"UPI/DR/{RRN}/SWIGGY/ICIC/swiggy@icici", ["SWIGGY"], [RRN, "swiggy@icici"]),
        (f"NEFT-{IFSC}-PRIYA SHARMA", ["NEFT-"], [IFSC, "PRIYA SHARMA"]),
        (f"IMPS/P2A/{RRN}/Neha Gupta/SBIN", ["IMPS/P2A/"], [RRN, "Neha Gupta"]),
        ("NACH/DR/BAJAJ FINANCE", ["NACH/DR/BAJAJ FINANCE"], []),
        (
            f"aadhaar {AADHAAR} pan {PAN} phone {IN_MOBILE}",
            ["aadhaar", "pan", "phone"],
            [AADHAAR, PAN, IN_MOBILE],
        ),
    ],
)
def test_india_narrations(narration: str, kept: list[str], masked: list[str]) -> None:
    out = redact_text(narration, locale_pack="in")
    for k in kept:
        assert k in out, out
    for m in masked:
        assert m not in out, out


def test_planted_identifiers_never_leak() -> None:
    planted = [CARD, SORT, ACCOUNT, IBAN, UK_MOBILE, "a.person@example.com"]
    rows = [
        {"narration": f"FPO PAYMENT {p} ROW {i}", "amount_band": "£20–50", "direction": "out"}
        for i, p in enumerate(planted)
    ]
    out = json.dumps(redact({"rows": rows}, locale_pack="uk"))
    for p in planted:
        assert p not in out
    in_planted = [AADHAAR, PAN, IFSC, IN_MOBILE, RRN, "name@okaxis"]
    rows = [{"narration": f"UPI/DR/{p}/SWIGGY"} for p in in_planted]
    out = json.dumps(redact({"rows": rows}, locale_pack="in"))
    for p in in_planted:
        assert p not in out


def test_people_are_numbered_consistently_and_found_across_fields() -> None:
    payload = {
        "rows": [
            {"counterparty": "Kofi Mensah", "channel": "faster_payment_in"},
            {"narration": "FPI KOFI MENSAH"},
            {"narration": "FPO AMA OWUSU"},
        ],
        "note": "Kofi Mensah paid back",
    }
    out = redact(payload, locale_pack="uk")
    assert out["rows"][0]["counterparty"] == "PERSON_1"
    assert out["rows"][1]["narration"] == "FPI PERSON_1"
    assert out["rows"][2]["narration"] == "FPO PERSON_2"
    assert out["note"] == "PERSON_1 paid back"


def test_named_household_members_and_employers() -> None:
    out = redact(
        {"n": "FPI AMA MENSAH HOUSEKEEPING", "s": "BGC NORTHWIND ROBOTICS SALARY"},
        locale_pack="uk",
        household_members=["Ama Mensah"],
        employers=["Northwind Robotics"],
    )
    assert out == {"n": "FPI HOUSEHOLD_MEMBER HOUSEKEEPING", "s": "BGC EMPLOYER SALARY"}


@pytest.mark.parametrize(
    "safe", ["£1,284.50", "2026-10-13", "12-10-26", "6 Nov", "£20–50", "DELIVEROO", "O2"]
)
def test_amounts_dates_and_merchants_survive(safe: str) -> None:
    assert safe in redact_text(f"row {safe} end", locale_pack="uk")


def test_numbers_keys_and_structure_are_untouched_and_output_is_deterministic() -> None:
    row = {"n": f"FPO JO BLOGGS {ACCOUNT}"}
    payload: dict[str, object] = {"amount_minor": 41234567, "flag": True, "rows": [row]}
    a = redact(payload, locale_pack="uk")
    assert a == redact(payload, locale_pack="uk")
    assert a["amount_minor"] == 41234567
    assert a["flag"] is True
    assert row["n"].endswith(ACCOUNT)  # input not mutated


def test_uk_lexicon_comes_from_the_pack_and_unknown_pack_is_rejected() -> None:
    assert {"DELIVEROO", "OCTOPUS ENERGY", "NETFLIX"} <= default_merchants("uk")
    with pytest.raises(ValueError, match="unknown locale pack"):
        redact_text("x", locale_pack="fr")
