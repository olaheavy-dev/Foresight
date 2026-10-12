from __future__ import annotations

from pathlib import Path

import pytest

from backend.features import Feature, load_features
from tools.check_feature_flags import violations
from tools.render_readme_status import END, START, render, update

ROOT = Path(__file__).resolve().parents[2]


def _feature(enabled: bool, suites: tuple[str, ...] = ("E-CAT",)) -> Feature:
    return Feature(
        key="categorisation", stage=1, title="Categorisation", enabled=enabled, suites=suites
    )


def test_disabled_feature_never_blocks() -> None:
    assert violations([_feature(False)], {}) == []


def test_enabled_feature_needs_passing_suites() -> None:
    assert violations([_feature(True)], {"E-CAT": "pass"}) == []
    assert violations([_feature(True)], {"E-CAT": "fail"}) != []
    assert violations([_feature(True)], {}) != []


def test_enabled_feature_without_suites_blocks() -> None:
    assert violations([_feature(True, suites=())], {}) != []


def test_repository_flags_are_consistent() -> None:
    features = load_features(ROOT / "features.yaml")
    assert features, "features.yaml is empty"
    assert all(f.suites for f in features), "every feature must link to an eval suite"
    assert all(1 <= f.stage <= 4 for f in features)


def test_readme_block_lists_unshipped_features() -> None:
    block = render([_feature(False)])
    assert "Not shipped (planned)" in block
    assert "Stage 1: Categorisation" in block


def test_readme_update_replaces_only_marked_block() -> None:
    readme = f"intro\n{START}\nold\n{END}\noutro"
    out = update(readme, render([_feature(True)]))
    assert out.startswith("intro\n")
    assert out.endswith("\noutro")
    assert "old" not in out


def test_readme_without_markers_is_rejected() -> None:
    with pytest.raises(ValueError, match="STATUS markers"):
        update("no markers", "block")
