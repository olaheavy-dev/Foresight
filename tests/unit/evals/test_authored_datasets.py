"""Hand-authored eval sets are frozen by evals/datasets/MANIFEST.authored.sha256 (docs/09 §3.9)."""

from __future__ import annotations

import hashlib
import json

from evals.common import DATASETS


def _manifest() -> dict[str, str]:
    lines = (DATASETS / "MANIFEST.authored.sha256").read_text(encoding="utf-8").splitlines()
    return {
        rel: h
        for h, _, rel in (ln.partition("  ") for ln in lines if ln and not ln.startswith("#"))
    }


def test_authored_files_match_their_manifest() -> None:
    for rel, digest in _manifest().items():
        assert hashlib.sha256((DATASETS / rel).read_bytes()).hexdigest() == digest, rel


def test_injection_sets_have_the_documented_shape() -> None:
    rows = [
        json.loads(x) for x in (DATASETS / "injection_cases.jsonl").read_text("utf-8").splitlines()
    ]
    assert sum(r["channel"] == "chat" for r in rows) == 40
    assert sum(r["channel"] == "data" for r in rows) == 40
    assert len({r["id"] for r in rows}) == 80
    for r in rows:
        assert r["text"]
        assert r["attacker_goal"]
        assert r["expected"]
    dev = (DATASETS / "injection_cases_dev.jsonl").read_text("utf-8").splitlines()
    assert len(dev) >= 20
    assert (
        len((DATASETS / "injection_benign_questions.jsonl").read_text("utf-8").splitlines()) == 60
    )
