"""Input screening: the deterministic front of the Ask pipeline and the import-time text check
(docs/05 §4.2 stages 0–1, §7.4a layers L2–L3).

- `normalise_input` — stage 0 clean-up: NFKC, hidden characters removed, look-alike letters
  folded for matching, length limit.
- `screen_input` — stage 1 for chat: allow | suspicious | block, with the rule ids that fired.
- `detect_suspicious_text` — the same rule pack over imported text (narrations, CSV headers, PDF
  text, filenames). Hook for ingestion: call it per row/header/file at import and store the
  result as `suspicious_text` on the row (wiring is AGT-13's ingest task, not this module).
- `quarantine` — what imported text looks like inside a prompt's JSON `data` field.
- `prepare_for_model` — the single function agents use to put imported text into a prompt: a
  flagged text is replaced by `<TEXT_WITHHELD>` (plus its payment-type code), never sent verbatim.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

from backend.agents.guard.rules import Channel, RulePack, load_rule_pack

Verdict = Literal["allow", "suspicious", "block"]
DataKind = Literal["narration", "header", "filename", "pdf_text"]

WITHHELD = "<TEXT_WITHHELD>"

# Zero-width, bidi-control and other invisible characters that hide text from people but not
# from models (Unicode categories Cf/Cc minus ordinary whitespace).
# ZWJ/ZWNJ stay: they are part of emoji sequences and Indic scripts.
_KEEP_CONTROL = {"\n", "\t", "\u200c", "\u200d"}
# Common Cyrillic/Greek look-alikes folded to Latin before matching (not applied to stored text).
_CONFUSABLES = str.maketrans(
    {
        "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i",
        "ј": "j", "ѕ": "s", "ԁ": "d", "ɡ": "g", "һ": "h", "ӏ": "l", "ո": "n", "ս": "u",
        "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P",
        "С": "C", "Т": "T", "Х": "X", "У": "Y", "І": "I", "Ј": "J", "Ѕ": "S",
        "α": "a", "ο": "o", "ν": "v", "ι": "i", "ρ": "p", "τ": "t", "κ": "k", "ε": "e",
        "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M",
        "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
    }
)  # fmt: skip
_SCRIPT_MIX = re.compile(r"(?=\w*[A-Za-z])(?=\w*[Ͱ-ϿЀ-ӿ])\w+")
_LIMIT_KEYS: dict[DataKind, str] = {
    "narration": "narration_max_chars",
    "header": "header_max_chars",
    "filename": "filename_max_chars",
    "pdf_text": "pdf_line_max_chars",
}


@dataclass(frozen=True)
class NormalisedInput:
    text: str  # what is stored and shown: NFKC, hidden characters removed, length-limited
    match_text: str  # what rules match against: also look-alike letters folded, spacing collapsed
    hidden_removed: int  # count of invisible characters removed (a signal in itself)
    mixed_script: bool  # Latin and Cyrillic/Greek in one word (homoglyph trick)
    truncated: bool


@dataclass(frozen=True)
class ScreenResult:
    verdict: Verdict
    rule_ids: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    rule_pack: str = ""
    normalised: NormalisedInput | None = field(default=None, compare=False)

    @property
    def out_of_scope(self) -> bool:
        return "out_of_scope" in self.reasons


def normalise_input(text: str, max_chars: int | None = None) -> NormalisedInput:
    nfkc = unicodedata.normalize("NFKC", text)
    kept: list[str] = []
    hidden = 0
    for ch in nfkc:
        if ch not in _KEEP_CONTROL and unicodedata.category(ch) in ("Cf", "Cc", "Co", "Cn"):
            hidden += ch != "\r"
            continue
        kept.append(ch)
    clean = "".join(kept)
    truncated = max_chars is not None and len(clean) > max_chars
    if truncated:
        clean = clean[:max_chars]
    mixed = bool(_SCRIPT_MIX.search(clean))
    # Underscores join words in filenames ("ignore_all_rules"); split them for matching.
    match_text = " ".join(clean.translate(_CONFUSABLES).replace("_", " ").split())
    return NormalisedInput(clean, match_text, hidden, mixed, truncated)


def _match(text: NormalisedInput, channel: Channel, pack: RulePack) -> ScreenResult:
    fired = [r for r in pack.for_channel(channel) if r.pattern.search(text.match_text)]
    ids = [r.id for r in fired]
    reasons = sorted({r.reason for r in fired})
    if text.hidden_removed:
        ids.append("G-HID-01")
        reasons.append("hidden_characters")
    if text.mixed_script:
        ids.append("G-HID-02")
        reasons.append("mixed_script")
    if any(r.severity == "block" for r in fired):
        verdict: Verdict = "block"
    elif ids:
        verdict = "suspicious"
    else:
        verdict = "allow"
    return ScreenResult(verdict, tuple(ids), tuple(dict.fromkeys(reasons)), pack.tag, text)


def screen_input(text: str, *, pack: RulePack | None = None) -> ScreenResult:
    """Stage 1 for a chat message: normalise, apply the chat rules, decide."""
    pack = pack or load_rule_pack()
    return _match(normalise_input(text, pack.limits.get("chat_max_chars")), "chat", pack)


def detect_suspicious_text(
    text: str, kind: DataKind = "narration", *, pack: RulePack | None = None
) -> ScreenResult:
    """Import-time check of one piece of imported text. Any rule hit means `suspicious_text`."""
    pack = pack or load_rule_pack()
    # Match the whole text (an attack may sit past the length cap); limits apply to what is sent.
    result = _match(normalise_input(text), "data", pack)
    if result.verdict == "block":
        return ScreenResult(
            "suspicious", result.rule_ids, result.reasons, pack.tag, result.normalised
        )
    return result


def quarantine(text: str, max_len: int) -> str:
    """Imported text as it may appear inside a prompt's JSON `data` field: NFKC, hidden and
    control characters removed, whitespace collapsed, delimiter-like characters neutralised
    (angle brackets, braces, backticks), length-capped."""
    clean = normalise_input(text).text
    clean = re.sub(r"[<>{}`\[\]|\\]", " ", clean)
    clean = " ".join(clean.split())
    return clean[:max_len].rstrip()


def prepare_for_model(
    text: str,
    kind: DataKind = "narration",
    *,
    payment_code: str | None = None,
    pack: RulePack | None = None,
) -> tuple[str, bool]:
    """(text to put in the prompt, suspicious?) for one piece of imported text.

    Suspicious text never reaches a model verbatim: it becomes `<TEXT_WITHHELD>` plus the row's
    payment-type code, if known (docs/05 §7.4a L3). Rows flagged this way are categorised by
    rules and merchant memory only and, if still unresolved, go to the review queue."""
    pack = pack or load_rule_pack()
    result = detect_suspicious_text(text, kind, pack=pack)
    if result.verdict != "allow":
        return (f"{payment_code} {WITHHELD}" if payment_code else WITHHELD), True
    return quarantine(text, pack.limits.get(_LIMIT_KEYS[kind], 64)), False
