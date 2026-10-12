"""Narration normalisation and parsing (channel, counterparty, reference).

`normalise_narration` is redact-safe: card digits, long references, account-like numbers, dates and
times are stripped, so the output can be shown or (later) sent to a model. Locale tokens (payment
codes, noise words) come from the pack.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.finance_core.categorise.pack import CategorisationPack
from backend.finance_core.types import Channel

_MASKED_CARD = re.compile(r"(\*{2,}|X{2,})\s?\d{2,4}\b|\bCARD\s?\d{4}\b|\bCD\s?\d{4}\b")
_DATE = re.compile(
    r"\b\d{1,2}[/.-]\d{1,2}([/.-]\d{2,4})?\b"
    r"|\b\d{1,2}\s?(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC)[A-Z]*(\s?\d{2,4})?\b"
    r"|\b\d{4}-\d{2}-\d{2}\b"
)
_TIME = re.compile(r"\b\d{1,2}:\d{2}(:\d{2})?\b")
_LONG_NUMBER = re.compile(r"\b[A-Z]{0,4}\d[\dA-Z]{5,}\b")  # refs, account numbers, auth codes
_AMOUNT = re.compile(r"[£$€₹]?\s?\d+[.,]\d{2}\b")
_REFERENCE = re.compile(r"\b(REF|REFERENCE|FROM|TO)\b[:\s]+([A-Z0-9][A-Z0-9 \-/]{2,})$")
_SPACE = re.compile(r"\s+")
_PUNCT = re.compile(r"[^A-Z0-9&'+.\s]")


def normalise_narration(text: str) -> str:
    t = text.upper()
    t = _MASKED_CARD.sub(" ", t)
    t = _DATE.sub(" ", t)
    t = _TIME.sub(" ", t)
    t = _AMOUNT.sub(" ", t)
    t = _LONG_NUMBER.sub(" ", t)
    t = _PUNCT.sub(" ", t)
    t = t.replace(" . ", " ")
    return _SPACE.sub(" ", t).strip(" .")


@dataclass(frozen=True)
class ParsedNarration:
    normalised: str
    channel: Channel
    counterparty: str | None
    reference: str | None


def parse_channel(normalised: str, bank_type: str | None, pack: CategorisationPack) -> Channel:
    if bank_type:
        bt = bank_type.strip().upper()
        for matcher in pack.channels:
            if bt in matcher.bank_types or bt in matcher.codes:
                return matcher.channel
    tokens = normalised.split()
    for matcher in pack.channels:
        if any(tok in matcher.codes for tok in tokens[:2] + tokens[-2:]):
            return matcher.channel
    return Channel.OTHER


def parse_narration(
    description: str, bank_type: str | None, pack: CategorisationPack
) -> ParsedNarration:
    normalised = normalise_narration(description)
    channel = parse_channel(normalised, bank_type, pack)
    reference = None
    ref_match = _REFERENCE.search(normalised)
    if ref_match:
        reference = ref_match.group(2).strip()
    codes = {code for m in pack.channels for code in m.codes}
    tokens = [
        tok
        for tok in normalised.split()
        if tok not in codes and tok not in pack.noise_tokens and not tok.isdigit()
    ]
    counterparty = " ".join(tokens[:4]) or None
    return ParsedNarration(normalised, channel, counterparty, reference)
