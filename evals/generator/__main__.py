"""CLI: python -m evals.generator --persona P1 --seed 1729 | --all | --verify-manifest."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from evals.generator import PRIMARY_SEED
from evals.generator.build import ALL_NAMES, DATASETS_DIR, file_hashes, resolve, write_all


def verify(out_dir: Path, seed: int) -> int:
    manifest = json.loads((out_dir / "MANIFEST.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        fresh = write_all(Path(tmp), list(ALL_NAMES), manifest.get("seed", seed))
    recorded: dict[str, str] = manifest["files"]
    on_disk = file_hashes(out_dir)
    problems = []
    for rel in sorted(set(fresh) | set(recorded) | set(on_disk)):
        a, b, c = fresh.get(rel), recorded.get(rel), on_disk.get(rel)
        if a != b:
            problems.append(f"regenerated != MANIFEST.json: {rel}")
        elif b != c:
            problems.append(f"on disk != MANIFEST.json: {rel}")
    for p in problems:
        print(p, file=sys.stderr)
    if problems:
        print(f"manifest verification FAILED ({len(problems)} files)", file=sys.stderr)
        return 1
    print(f"manifest verified: {len(recorded)} files match")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals.generator", description=__doc__)
    ap.add_argument(
        "--persona",
        action="append",
        default=[],
        help="dataset name or alias (P1 = P1-base + P1-clean); repeatable",
    )
    ap.add_argument("--all", action="store_true", help="generate every dataset")
    ap.add_argument("--seed", type=int, default=PRIMARY_SEED)
    ap.add_argument("--out", type=Path, default=DATASETS_DIR)
    ap.add_argument("--verify-manifest", action="store_true")
    ap.add_argument("--list", action="store_true", help="list dataset names")
    args = ap.parse_args(argv)
    if args.list:
        print("\n".join(ALL_NAMES))
        return 0
    if args.verify_manifest:
        return verify(args.out, args.seed)
    names = list(ALL_NAMES) if args.all else resolve(args.persona)
    if not names:
        ap.error("give --persona NAME, --all or --verify-manifest")
    hashes = write_all(args.out, names, args.seed)
    size = sum((args.out / k).stat().st_size for k in hashes)
    print(f"wrote {', '.join(names)} → {args.out} ({len(hashes)} files, {size / 1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
