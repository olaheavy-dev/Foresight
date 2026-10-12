"""Feature flags loaded from features.yaml (docs/01 FR-86)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Feature:
    key: str
    stage: int
    title: str
    enabled: bool
    suites: tuple[str, ...]


def load_features(path: str | Path) -> list[Feature]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    features = []
    for key, spec in (data.get("features") or {}).items():
        features.append(
            Feature(
                key=key,
                stage=int(spec["stage"]),
                title=str(spec["title"]),
                enabled=bool(spec.get("enabled", False)),
                suites=tuple(spec.get("suites") or ()),
            )
        )
    return features
