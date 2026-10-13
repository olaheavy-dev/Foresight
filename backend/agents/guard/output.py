"""Output checks before anything a model wrote reaches the UI (docs/05 §4.2 stage 5, §7.4a L4).

`output_screen` takes model text, or a plan (any JSON-like structure whose strings are model
text), and returns every violation. A non-empty list means the output is dropped and the block
falls back to a deterministic template; a canary hit also writes `AuditEvent prompt_leak_blocked`
(the caller does that — this module only detects).

Checks:
- `canary`: the per-deployment prompt canary appears (the prompt leaked).
- `url`: a link to a host outside the rule pack's allow-list (MoneyHelper and the like).
- `numeral`: a financial numeral outside a `{{placeholder}}` (V-07: models never author numbers).
- `product_advice`: a regulated-product phrase from the pack's list (V-14).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

from backend.agents.guard.canary import contains_canary
from backend.agents.guard.rules import RulePack, load_rule_pack

ViolationKind = Literal["canary", "url", "numeral", "product_advice"]

_PLACEHOLDER = re.compile(r"\{\{\s*[^{}]+?\s*\}\}")
_URL = re.compile(
    r"(?i)\b(?:https?://|www\.)[^\s<>\"')\]]+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|"
    r"xyz|ru|cn|top|app|dev|co|uk|in|info|biz|link|site|online|ly|me)(?:/[^\s<>\"')\]]*)?\b"
)
# Financial numerals: currency amounts, percentages and bare numbers of two or more digits or with
# separators. Single digits ("1 of 3", "step 2") and ordinal words are allowed.
_NUMERAL = re.compile(
    r"[£$€₹¥]\s?\d[\d,]*(?:\.\d+)?|\b\d+(?:[.,]\d+)*(?:\s?%|\s?percent\b|\s?pc\b)|\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b"
    r"|\b\d+\.\d+\b|\b\d{2,}\b"
)


@dataclass(frozen=True)
class Violation:
    kind: ViolationKind
    detail: str
    path: str = ""


def _strings(value: Any, path: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, Mapping):
        for k, v in value.items():
            yield from _strings(v, f"{path}.{k}" if path else str(k))
    elif isinstance(value, list | tuple):
        for i, v in enumerate(value):
            yield from _strings(v, f"{path}[{i}]")


def _host_allowed(url: str, allow: frozenset[str]) -> bool:
    candidate = url if "://" in url else f"https://{url}"
    host = (urlparse(candidate).hostname or "").lower()
    return host in allow or any(host.endswith("." + a) for a in allow)


def numerals_outside_placeholders(text: str) -> list[str]:
    """V-07 helper: numerals a model wrote outside `{{…}}` value placeholders."""
    return _NUMERAL.findall(_PLACEHOLDER.sub(" ", text))


def output_screen(
    output: str | Mapping[str, Any] | list[Any],
    *,
    locale_pack: str = "uk",
    canary: str | None = None,
    check_numerals: bool = True,
    pack: RulePack | None = None,
) -> list[Violation]:
    pack = pack or load_rule_pack()
    phrases = pack.product_advice.get(locale_pack, ())
    found: list[Violation] = []
    for path, text in _strings(output):
        if contains_canary(text, canary):
            found.append(Violation("canary", "prompt canary in output", path))
        for url in (u.rstrip(".,;:!?") for u in _URL.findall(text)):
            if not _host_allowed(url, pack.url_allow_list):
                found.append(Violation("url", url, path))
        if check_numerals:
            for num in numerals_outside_placeholders(_URL.sub(" ", text)):
                found.append(Violation("numeral", num, path))
        lowered = " ".join(text.lower().split())
        for phrase in phrases:
            if re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", lowered):
                found.append(Violation("product_advice", phrase, path))
    return found
