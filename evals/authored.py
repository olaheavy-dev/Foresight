"""Freeze hand-authored eval sets by sha256 (docs/09 §3.5–3.7, §3.10, §10a).

The generator's MANIFEST.json covers only regenerated persona data (`python -m evals.generator
--verify` regenerates and compares), so hand-written sets live in `evals/datasets/authored/` with
their own manifest. Tuning prompts or rules must never edit these files: a changed file fails
`--verify` until it is re-frozen deliberately with `--write` and the change is explained in
`evals/CHANGELOG.md`.

    python -m evals.authored --verify
    python -m evals.authored --write
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

AUTHORED_DIR = Path(__file__).resolve().parent / "datasets" / "authored"
MANIFEST = AUTHORED_DIR / "MANIFEST.json"
VERSION = "authored-1"


def _rows(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def current(directory: Path = AUTHORED_DIR) -> dict[str, dict[str, object]]:
    """Every `*.jsonl` set in the folder with its sha256 and row count."""
    return {
        p.name: {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "rows": _rows(p)}
        for p in sorted(directory.glob("*.jsonl"))
    }


def write(directory: Path = AUTHORED_DIR) -> dict[str, dict[str, object]]:
    files = current(directory)
    body = {"version": VERSION, "note": "synthetic / fictional, hand-authored", "files": files}
    (directory / MANIFEST.name).write_text(
        json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return files


def verify(directory: Path = AUTHORED_DIR) -> list[str]:
    """Problems with the frozen sets; empty when every file matches its registered hash."""
    manifest_path = directory / MANIFEST.name
    if not manifest_path.exists():
        return [f"{manifest_path} is missing; run `python -m evals.authored --write`"]
    recorded: dict[str, dict[str, object]] = json.loads(manifest_path.read_text(encoding="utf-8"))[
        "files"
    ]
    found = current(directory)
    problems = [f"registered but missing: {name}" for name in sorted(set(recorded) - set(found))]
    problems += [
        f"not registered (freeze it with --write): {name}"
        for name in sorted(set(found) - set(recorded))
    ]
    problems += [
        f"changed since it was frozen: {name}"
        for name in sorted(set(found) & set(recorded))
        if found[name]["sha256"] != recorded[name]["sha256"]
    ]
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    if args.write:
        files = write()
        print(f"froze {len(files)} authored sets")
        return 0
    problems = verify()
    for p in problems:
        print(p, file=sys.stderr)
    if problems:
        return 1
    print(f"authored sets verified: {len(current())} files match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
