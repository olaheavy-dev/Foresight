"""Export the UI contracts (docs/08 §2): Pydantic → JSON Schema → TypeScript types and guards.

    python tools/export_schemas.py          # regenerate frontend/src/ui-contracts/*
    python tools/export_schemas.py --check  # exit 1 if any generated file is out of date

Writes `schema.json` here, then runs `frontend/src/ui-contracts/codegen.mjs` (Node, with the
frontend's `npm ci` done) to produce `types.ts` (json-schema-to-typescript) and `guards.ts`.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess  # noqa: S404 - runs the repo's own codegen script with fixed arguments
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.ui_contracts.schema import contracts_schema  # noqa: E402

FRONTEND = ROOT / "frontend"
OUT_DIR = FRONTEND / "src" / "ui-contracts"
SCHEMA_FILE = OUT_DIR / "schema.json"
CODEGEN = OUT_DIR / "codegen.mjs"
STALE_EXIT = 10  # codegen.mjs: generated TypeScript differs from the files on disk


def render_schema() -> str:
    return json.dumps(contracts_schema(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="verify instead of writing")
    args = parser.parse_args(argv)

    schema = render_schema()
    stale: list[str] = []
    if args.check:
        current = SCHEMA_FILE.read_text(encoding="utf-8") if SCHEMA_FILE.exists() else ""
        if current != schema:
            stale.append(str(SCHEMA_FILE.relative_to(ROOT)))
    else:
        SCHEMA_FILE.write_text(schema, encoding="utf-8")

    node = shutil.which("node")
    if node is None:
        print("node not found: install Node and run `npm ci` in frontend/", file=sys.stderr)
        return 2
    # In --check mode the codegen reads the schema from stdin, so a stale schema.json on disk
    # cannot hide stale TypeScript.
    result = subprocess.run(  # noqa: S603 - fixed argv
        [node, str(CODEGEN), *(["--check"] if args.check else [])],
        cwd=FRONTEND,
        input=schema,
        text=True,
        capture_output=True,
        check=False,
    )
    sys.stderr.write(result.stderr)
    if result.returncode not in (0, STALE_EXIT):
        print(f"codegen failed (exit {result.returncode})", file=sys.stderr)
        return 2
    stale += [line for line in result.stdout.splitlines() if line.strip()]

    if args.check:
        if stale:
            print("Out of date; run `python tools/export_schemas.py`:", *stale, sep="\n  ")
            return 1
        print("UI contracts are up to date.")
    else:
        print(f"Wrote {SCHEMA_FILE.relative_to(ROOT)}", *result.stdout.splitlines(), sep="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
