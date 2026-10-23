"""Payload redaction before anything is sent to the model provider (docs/05 §7.3, §7.4a layer L2).

`redact(payload, locale_pack=...)` walks a JSON-like payload and masks identifiers in every string
value. Keys, numbers and booleans are left alone (amounts travel as bands, never as identifiers).
A string that is itself a JSON document (an agent's `data` message) is parsed and walked the same
way, so its numbers (amounts in minor units, counts) are never mistaken for references; only its
string values are masked.
It is deterministic: the same payload always gives the same output, and within one call the same
person is always the same `PERSON_n` placeholder, so a model can still see that two rows are the
same counterparty without learning who it is.

What is masked (all packs unless stated):
- explicitly named household members → `HOUSEHOLD_MEMBER`, people → `PERSON_n`, employers →
  `EMPLOYER` (callers pass what the ledger already knows: Counterparty rows, income streams);
- e-mail addresses → `EMAIL`; UPI IDs / VPAs (`name@bank`) → `VPA_n`;
- IBANs → `IBAN`; card numbers (13–19 digits, spaced or not) and masked cards (`****1234`) →
  `CARD`; UK sort codes → `SORT_CODE`; 8-digit account numbers → `ACCOUNT`;
- payment references (after a reference marker, or long digit-bearing tokens) → `REF`;
- UK and Indian phone numbers → `PHONE`;
- `in` pack only: IFSC codes → `IFSC`; 12-digit UPI/IMPS/NEFT retrieval references → `REF`;
  Aadhaar-shaped (12 digits, optionally 4-4-4) and PAN-shaped (`AAAAA9999A`) strings → `ID`;
- person names in transfer narrations (Faster Payments, standing orders, Bacs, UPI payees): the
  counterparty part of the narration becomes `PERSON_n` unless it is a known merchant or looks
  like a business (LTD, COUNCIL, ENERGY, …).

The module is pure: no network, no AI SDK, no storage (import-linter contracts, docs/05 §3.1).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.finance_core.categorise.pack import load_pack

LOCALE_PACKS = ("uk", "in")
_PACK_DIR = Path(__file__).resolve().parents[1] / "finance_core" / "locale_packs"

# Merchants the `in` pack keeps by name (there is no `in` pack file yet; this is the redaction-side
# lexicon only, docs/05 §7.3: "kept only when it matches the pack's merchant lexicon").
_IN_MERCHANTS = frozenset(
    {
        "SWIGGY", "ZOMATO", "FLIPKART", "AMAZON", "BIGBASKET", "BLINKIT", "ZEPTO", "MYNTRA",
        "UBER", "OLA", "RAPIDO", "IRCTC", "AIRTEL", "JIO", "VI", "BSNL", "TATA PLAY", "NETFLIX",
        "HOTSTAR", "SPOTIFY", "DMART", "RELIANCE", "PAYTM", "PHONEPE", "GPAY", "BESCOM",
        "MAHADISCOM", "TNEB", "LIC", "HDFC LIFE", "DOMINOS", "MCDONALDS", "STARBUCKS",
    }
)  # fmt: skip

# Words that make a counterparty a business, not a person.
_BUSINESS_WORDS = frozenset(
    {
        "LTD", "LIMITED", "PLC", "LLP", "LLC", "INC", "CO", "COMPANY", "GROUP", "UK", "BANK",
        "COUNCIL", "CC", "MBC", "DC", "HMRC", "DVLA", "ENERGY", "WATER", "WATERS", "GAS", "POWER",
        "INSURANCE", "LETTINGS", "PROPERTY", "PROPERTIES", "ESTATES", "HOMES", "SERVICES",
        "SOLUTIONS", "STUDIO", "STUDIOS", "CLINIC", "SCHOOL", "COLLEGE", "UNIVERSITY", "TRUST",
        "CHARITY", "FOUNDATION", "NHS", "POST", "OFFICE", "PVT", "PRIVATE", "STORES", "STORE",
        "SHOP", "MARKET", "PHARMACY", "GYM", "FITNESS", "TELECOM", "MOBILE", "BROADBAND",
        "LOANS", "FINANCE", "CREDIT", "CARD", "SAVINGS", "POT", "ISA", "PENSION", "TAX",
        "CENTRE", "CENTER", "HOTEL", "RESTAURANT", "CAFE", "MOTORS", "GARAGE", "TRAVEL",
        "AIRWAYS", "RAIL", "TRAINS", "TFL", "PARKING", "SALARY", "PAYROLL", "WAGES", "REFUND",
        "INTEREST", "TRANSFER", "PAYMENT", "PAYMENTS", "BILL", "DIRECT", "DEBIT",
    }
)  # fmt: skip

# Narration prefixes after which the counterparty is a person or business, never a card merchant.
_TRANSFER_CODES = frozenset(
    {"FPO", "FPI", "FP", "SO", "STO", "BGC", "BACS", "TFR", "BP", "NEFT", "IMPS", "RTGS"}
)
_TRANSFER_PHRASES = re.compile(
    r"^(?:(?:FASTER\s+PAYMENT|PAYMENT|TRANSFER|STANDING\s+ORDER|BANK\s+TRANSFER|SENT|RECEIVED)"
    r"\s+(?:TO|FROM)\s+|(?:TO|FROM)\s+)",
    re.IGNORECASE,
)
_REFERENCE_MARKERS = (
    "REF", "REFERENCE", "INV", "INVOICE", "ORDER", "BOOKING", "ACCT", "ACC", "NO", "PO",
)  # fmt: skip

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_VPA = re.compile(r"\b[\w.-]{2,}@[a-z][a-z0-9]{1,}\b", re.IGNORECASE)
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b")
_CARD = re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])")
_MASKED_CARD = re.compile(r"(?:\*{2,}|X{2,}|x{2,}|•{2,})\s?\d{2,4}\b")
_SORT_CODE = re.compile(r"(?<![\d-])(\d{2})-(\d{2})-(\d{2})(?![\d-])")
_SORT_CODE_CUE = re.compile(r"(?i)\b(?:sort\s*code|s/c|sc)\b\W{0,3}$")
_ACCOUNT = re.compile(r"(?<![\d.,£$€₹])\b\d{4} ?\d{4}\b(?![\d.,])")
_UK_PHONE = re.compile(
    r"(?<![\w+])(?:\+44\s?(?:\(0\)\s?)?|0)\d{2,4}[\s-]?\d{3,4}[\s-]?\d{3,4}(?!\d)"
)
_IN_PHONE = re.compile(r"(?<![\w+])(?:\+91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")
_IFSC = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
_AADHAAR_SPACED = re.compile(r"(?<!\d)\d{4}[ -]\d{4}[ -]\d{4}(?!\d)")
_TWELVE_DIGITS = re.compile(r"(?<!\d)\d{12}(?!\d)")
_RRN_CONTEXT = re.compile(r"(?i)\b(?:UPI|IMPS|NEFT|RRN|UTR|RTGS|NACH)\b")
_REF_AFTER_MARKER = re.compile(
    r"(?i)\b(" + "|".join(_REFERENCE_MARKERS) + r")\b[\s:.#-]*"
    r"(?!(?:ACCOUNT|SORT_CODE|CARD|PHONE|IBAN|EMAIL|IFSC|ID|REF)\b)([A-Z0-9][A-Z0-9/-]{2,})"
)
# a reference-shaped token: ≥6 characters with at least 3 digits (auth codes, long refs, INV0042)
_TOKEN = re.compile(r"(?<![\w.,£$€₹-])[A-Za-z0-9][A-Za-z0-9-]{5,}(?![\w.,-])")
_DATE_LIKE = re.compile(r"^\d{4}-\d{2}-\d{2}$|^\d{1,2}-\d{1,2}-\d{2,4}$")
_PLACEHOLDER = re.compile(
    r"^(?:PERSON_\d+|VPA_\d+|HOUSEHOLD_MEMBER|EMPLOYER|EMAIL|IBAN|CARD|SORT_CODE|ACCOUNT|REF|"
    r"PHONE|IFSC|ID)$"
)


@dataclass
class _State:
    """Per-call placeholder numbering, so the same person maps to the same token."""

    people: dict[str, str] = field(default_factory=dict)
    vpas: dict[str, str] = field(default_factory=dict)

    def person(self, name: str) -> str:
        key = " ".join(name.upper().split())
        if key not in self.people:
            self.people[key] = f"PERSON_{len(self.people) + 1}"
        return self.people[key]

    def vpa(self, value: str) -> str:
        key = value.lower()
        if key not in self.vpas:
            self.vpas[key] = f"VPA_{len(self.vpas) + 1}"
        return self.vpas[key]


@lru_cache(maxsize=4)
def default_merchants(locale_pack: str) -> frozenset[str]:
    """The merchant lexicon whose names are kept: every merchant, bill and savings marker in the
    pack's rules (`uk.yaml`), or the redaction lexicon above for `in`."""
    if locale_pack == "in":
        return _IN_MERCHANTS
    pack = load_pack((_PACK_DIR / f"{locale_pack}.yaml").read_text(encoding="utf-8"))
    names: set[str] = set()
    for rule in pack.rules:
        names.update(rule.merchants)
    names.update(pack.card_bill_markers)
    names.update(pack.savings_markers)
    for family in pack.subscription_families.values():
        names.update(family)
    return frozenset(n.upper() for n in names if n)


def _replace_names(text: str, names: Iterable[str], token: str | None, state: _State) -> str:
    for name in sorted({n for n in names if n and n.strip()}, key=len, reverse=True):
        pattern = re.compile(
            r"(?<!\w)" + r"\s+".join(map(re.escape, name.split())) + r"(?!\w)", re.I
        )
        text = pattern.sub(token or state.person(name), text)
    return text


def _is_plausible_date(a: str, b: str) -> bool:
    return 1 <= int(a) <= 31 and 1 <= int(b) <= 12


def _mask_sort_codes(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        cued = bool(_SORT_CODE_CUE.search(text[max(0, m.start() - 14) : m.start()]))
        if cued or not _is_plausible_date(m.group(1), m.group(2)):
            return "SORT_CODE"
        return m.group(0)  # a dd-mm-yy date with no sort-code cue stays (docs/09 redaction cases)

    return _SORT_CODE.sub(repl, text)


def _mask_twelve_digits(text: str) -> str:
    """`in` pack: a 12-digit run is a UPI/IMPS retrieval reference when the narration says so,
    otherwise treated as Aadhaar-shaped."""
    token = "REF" if _RRN_CONTEXT.search(text) else "ID"
    return _TWELVE_DIGITS.sub(token, text)


def _looks_like_person(words: Sequence[str], merchants: frozenset[str]) -> bool:
    if not 1 <= len(words) <= 4 or any(_PLACEHOLDER.match(w) for w in words):
        return False
    joined = " ".join(words)
    if any(m in joined for m in merchants if len(m) > 2) or joined in merchants:
        return False
    if any(w in _BUSINESS_WORDS for w in words):
        return False
    return all(re.fullmatch(r"[A-Z][A-Z'.-]*", w) for w in words) and any(len(w) > 1 for w in words)


def _mask_transfer_counterparty(text: str, merchants: frozenset[str], state: _State) -> str:
    """Mask the counterparty of a transfer narration (FPO K MENSAH RENT → FPO PERSON_1 RENT)."""
    upper = text.upper()
    # Indian rails: UPI/DR/<rrn>/<payee>/<bank>/<vpa>, NEFT-<ifsc>-<payee>, IMPS/P2A/<rrn>/<payee>.
    # The payee is the first name-like segment after the reference; bank codes (≤4 letters) stay.
    if re.match(r"^\s*(UPI|IMPS|NEFT|NACH|RTGS)\b", upper) and re.search(r"[/-]", text):
        parts = re.split(r"([/-])", text)
        for i in range(2, len(parts), 2):
            seg = parts[i].strip()
            words = seg.upper().split()
            if not words or (len(words) == 1 and len(words[0]) <= 4):
                continue
            if _looks_like_person(words, merchants):
                parts[i] = parts[i].replace(seg, state.person(seg))
            break
        return "".join(parts)
    tokens = text.split()
    if not tokens:
        return text
    start = None
    if tokens[0].upper().strip(":") in _TRANSFER_CODES:
        start = 1
    else:
        m = _TRANSFER_PHRASES.match(text)
        if m:
            start = len(text[: m.end()].split())
    if start is None:
        return text
    end = start
    while end < len(tokens) and end - start < 4:
        tok = tokens[end].upper().strip(",.;:")
        if (
            not tok
            or tok in _REFERENCE_MARKERS
            or any(ch.isdigit() for ch in tok)
            or _PLACEHOLDER.match(tok)
        ):
            break
        end += 1
    words = [t.upper().strip(",.;:") for t in tokens[start:end]]
    # Keep a trailing purpose word ("RENT", "DINNER") out of the name when there are ≥3 words.
    if len(words) >= 3 and words[-1] in _PURPOSE_WORDS:
        end -= 1
        words = words[:-1]
    if words and _looks_like_person(words, merchants):
        name = " ".join(tokens[start:end])
        tokens[start:end] = [state.person(name)]
        return " ".join(tokens)
    return text


def _transfer_counterparties(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, Mapping):
        if str(value.get("channel", "")).lower() in _TRANSFER_CHANNELS:
            out += [v for k, v in value.items() if k in _COUNTERPARTY_KEYS and isinstance(v, str)]
        for v in value.values():
            out += _transfer_counterparties(v)
    elif isinstance(value, list | tuple):
        for v in value:
            out += _transfer_counterparties(v)
    elif isinstance(value, str):
        document = _json_document(value)
        if document is not None:
            out += _transfer_counterparties(document)
    return out


# A dict whose `channel` is a person-to-person rail: its counterparty field is masked when it
# looks like a person's name (Monzo/Revolut exports put "K Mensah" in a Name column, no code).
_TRANSFER_CHANNELS = frozenset(
    {"faster_payment_in", "faster_payment_out", "standing_order", "bacs_credit", "transfer", "upi"}
)
_COUNTERPARTY_KEYS = frozenset({"counterparty", "name", "payee", "payer"})

_PURPOSE_WORDS = frozenset(
    {"RENT", "DINNER", "LUNCH", "BILLS", "BILL", "GIFT", "LOAN", "FOOD", "TRIP", "HOLIDAY",
     "SHARE", "SPLIT", "PETROL", "FUEL", "MONEY", "THANKS", "BIRTHDAY", "XMAS", "CHRISTMAS"}
)  # fmt: skip


def redact_text(
    text: str,
    *,
    locale_pack: str = "uk",
    people: Iterable[str] = (),
    household_members: Iterable[str] = (),
    employers: Iterable[str] = (),
    merchants: frozenset[str] | None = None,
    _state: _State | None = None,
) -> str:
    """Mask one string. Use `redact` for whole payloads (it keeps PERSON_n stable across fields)."""
    if locale_pack not in LOCALE_PACKS:
        raise ValueError(f"unknown locale pack {locale_pack!r}; expected one of {LOCALE_PACKS}")
    state = _state or _State()
    lexicon = default_merchants(locale_pack) if merchants is None else merchants
    out = _replace_names(text, household_members, "HOUSEHOLD_MEMBER", state)
    out = _replace_names(out, employers, "EMPLOYER", state)
    out = _replace_names(out, people, None, state)
    out = _EMAIL.sub("EMAIL", out)
    out = _VPA.sub(lambda m: state.vpa(m.group(0)), out)
    out = _IBAN.sub("IBAN", out)
    out = _MASKED_CARD.sub("CARD", out)
    if locale_pack == "in":
        out = _AADHAAR_SPACED.sub("ID", out)
        out = _mask_twelve_digits(out)
        out = _IFSC.sub("IFSC", out)
        out = _PAN.sub("ID", out)
        out = _IN_PHONE.sub("PHONE", out)
    out = _CARD.sub("CARD", out)
    out = _mask_sort_codes(out)
    out = _UK_PHONE.sub("PHONE", out)
    out = _IN_PHONE.sub("PHONE", out)
    out = _ACCOUNT.sub("ACCOUNT", out)
    out = _REF_AFTER_MARKER.sub(lambda m: f"{m.group(1)} REF", out)
    out = _TOKEN.sub(_long_ref, out)
    return _mask_transfer_counterparty(out, lexicon, state)


def _long_ref(m: re.Match[str]) -> str:
    tok = m.group(0)
    if _PLACEHOLDER.match(tok) or _DATE_LIKE.match(tok) or sum(c.isdigit() for c in tok) < 3:
        return tok
    return "REF"


def _json_document(text: str) -> Any:
    """The parsed value when `text` is a JSON object or array, else None."""
    stripped = text.strip()
    if not stripped or stripped[0] not in "{[":
        return None
    try:
        value = json.loads(stripped)
    except ValueError:
        return None
    return value if isinstance(value, dict | list) else None


def redact(
    payload: Mapping[str, Any],
    *,
    locale_pack: str,
    people: Iterable[str] = (),
    household_members: Iterable[str] = (),
    employers: Iterable[str] = (),
    merchants: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Return a redacted copy of a JSON-like payload (dicts, lists, strings, numbers)."""
    state = _State()
    lexicon = default_merchants(locale_pack) if merchants is None else merchants
    # First pass: person names that sit in the counterparty field of a transfer row are masked
    # wherever else they appear in the payload too (free text, other rows).
    found = [
        n
        for n in _transfer_counterparties(payload)
        if _looks_like_person(n.upper().split(), lexicon)
    ]
    names = (tuple(people) + tuple(found), tuple(household_members), tuple(employers))

    def walk(value: Any, key: str | None = None, transfer: bool = False) -> Any:
        if isinstance(value, str):
            document = _json_document(value)
            if document is not None:
                return json.dumps(walk(document), ensure_ascii=False)
        if isinstance(value, str) and transfer and key in _COUNTERPARTY_KEYS:
            words = value.upper().split()
            if _looks_like_person(words, lexicon):
                return state.person(value)
        if isinstance(value, str):
            return redact_text(
                value,
                locale_pack=locale_pack,
                people=names[0],
                household_members=names[1],
                employers=names[2],
                merchants=merchants,
                _state=state,
            )
        if isinstance(value, Mapping):
            is_transfer = str(value.get("channel", "")).lower() in _TRANSFER_CHANNELS
            return {k: walk(v, k, is_transfer) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [walk(v) for v in value]
        return value

    return dict(walk(payload))
