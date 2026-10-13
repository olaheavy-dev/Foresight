from __future__ import annotations

from backend.agents.guard import (
    canary_instruction,
    contains_canary,
    make_canary,
    numerals_outside_placeholders,
    output_screen,
)

CANARY = make_canary("unit-test-secret")


def kinds(text: str, **kw: object) -> set[str]:
    return {v.kind for v in output_screen(text, canary=CANARY, **kw)}  # type: ignore[arg-type]


def test_clean_output_passes() -> None:
    text = "Moving the transfer to {{date}} keeps you above {{buffer}}. See moneyhelper.org.uk."
    assert output_screen(text, canary=CANARY) == []


def test_canary_url_numeral_and_product_advice_are_caught() -> None:
    assert kinds(f"My marker is {CANARY}") == {"canary"}
    assert kinds(f"marker {CANARY.upper().replace('-', ' - ')}") == {"canary"}
    assert kinds("See https://evil.example.xyz/plan") == {"url"}
    assert kinds("Your low is £162, 32% below") == {"numeral"}
    assert kinds("You should open an ISA") == {"product_advice"}
    assert kinds("Take a personal loan", locale_pack="in") == {"product_advice"}


def test_plans_are_walked_with_paths() -> None:
    plan = {"blocks": [{"title": "ok"}, {"text": "buy shares now"}]}
    (v,) = output_screen(plan, canary=CANARY)
    assert v.kind == "product_advice"
    assert v.path == "blocks[1].text"


def test_numerals_helper_ignores_placeholders_and_single_digits() -> None:
    assert numerals_outside_placeholders("{{amount}} in 3 steps on {{date}}") == []
    assert numerals_outside_placeholders("£40 and 1,200 and 12.5") == ["£40", "1,200", "12.5"]


def test_canary_is_deterministic_per_secret_and_never_in_plain_instruction_twice() -> None:
    assert make_canary("a") == make_canary("a") != make_canary("b")
    line = canary_instruction(CANARY)
    assert CANARY in line
    assert contains_canary(line, CANARY)
    assert not contains_canary("nothing here", CANARY)
