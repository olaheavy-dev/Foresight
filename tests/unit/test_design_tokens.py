"""The design tokens have one source (design/tokens/tokens.css); every copy must match it."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "design" / "tokens" / "tokens.css"
COPIES = [
    ROOT / "frontend" / "app" / "tokens.css",
    ROOT / "design" / "hifi" / "assets" / "tokens.css",
]


@pytest.mark.parametrize("copy", COPIES, ids=lambda p: str(p.relative_to(ROOT)))
def test_token_copies_match_the_source(copy: Path) -> None:
    assert copy.read_text(encoding="utf-8") == SOURCE.read_text(
        encoding="utf-8"
    ), f"{copy} is out of date; copy design/tokens/tokens.css over it"


def test_light_and_dark_define_the_same_colour_tokens() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    light = text.split('[data-theme="dark"]')[0]
    dark = text.split('[data-theme="dark"]')[1].split("@media")[0]

    def names(block: str) -> set[str]:
        return {
            line.split(":")[0].strip()
            for line in block.splitlines()
            if line.strip().startswith("--color-")
        }

    assert names(light) == names(dark)
