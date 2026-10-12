"""QA-02: illustrative design figures (docs/00 §10a) must never be hardcoded in product code.

The engine computes every number. If one of these literals appears in backend/ or the frontend
source, it is a hardcoded output. design/ is exempt: it is labelled illustrative.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Generated P1 figures from design/fixture/fixture.json (register rev 6).
DESIGN_FIGURES = (
    "2,184.50",
    "2184.50",
    "4,050",
    "286.40",
    "203.10",
    "136.37",
    "143.20",
    "1,086",
    "8,388",
    "8,345",
    "7,188",
    "£604",
    "£812",
    "£162",
)
SCANNED = (ROOT / "backend", ROOT / "frontend" / "src", ROOT / "frontend" / "app")
SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".yaml", ".yml"}


def test_no_design_figures_in_product_code() -> None:
    hits = []
    for base in SCANNED:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.suffix not in SUFFIXES or "node_modules" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            hits += [f"{path.relative_to(ROOT)}: {f}" for f in DESIGN_FIGURES if f in text]
    assert hits == []
