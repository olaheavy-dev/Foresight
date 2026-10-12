"""CI gate: an enabled feature must have every linked eval suite passing (docs/01 FR-86).

Reads features.yaml and evals/results/latest.json. The eval runner writes a `gates` block to
latest.json mapping each suite ID (e.g. "E-CAT") to "pass" or "fail" after comparing results
with targets and the regression baseline (docs/09 §16). A missing file, gate or "fail" blocks.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.features import Feature, load_features


def violations(features: list[Feature], gates: dict[str, str]) -> list[str]:
    problems = []
    for feature in features:
        if not feature.enabled:
            continue
        if not feature.suites:
            problems.append(f"{feature.key}: enabled but linked to no eval suite")
        for suite in feature.suites:
            status = gates.get(suite)
            if status != "pass":
                problems.append(f"{feature.key}: suite {suite} is {status or 'missing'}")
    return problems


def load_gates(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in (data.get("gates") or {}).items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", default="features.yaml")
    parser.add_argument("--results", default="evals/results/latest.json")
    args = parser.parse_args(argv)

    problems = violations(load_features(args.features), load_gates(Path(args.results)))
    for problem in problems:
        print(f"feature flag check: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
