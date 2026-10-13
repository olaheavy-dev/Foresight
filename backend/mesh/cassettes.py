"""Record and replay of Mesh exchanges (docs/09 §16, docs/10 AGT-09).

A cassette entry is one JSON file named after the request hash, so evals and CI can run every LLM
suite with no key and no network. The hash covers exactly what was sent (tier, primary model,
redacted messages, output schema, sampling parameters); any drift in prompts, models or inputs is a
`CassetteMiss`, never a silent stale answer.

Entry format (`<request_hash>.json`):

    {
      "format": "foresight-cassette/1",
      "request_hash": "<sha256>",
      "request": {"tier", "model", "messages", "temperature", "max_tokens",
                  "schema_name", "schema", "strategy"},
      "response": {"mesh_response_id", "model", "content", "tool_arguments", "usage": {...}},
      "recorded_at": "<ISO 8601 UTC>",
      "live_run_sha": "<git sha of the recording run>"
    }
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CASSETTE_FORMAT = "foresight-cassette/1"


class CassetteMiss(LookupError):
    """Replay mode met a request that was never recorded (or whose inputs changed)."""


def request_hash(request: dict[str, Any]) -> str:
    canonical = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RecordedResponse:
    mesh_response_id: str
    model: str
    content: str | None
    tool_arguments: str | None
    prompt_tokens: int
    completion_tokens: int

    def as_json(self) -> dict[str, Any]:
        return {
            "mesh_response_id": self.mesh_response_id,
            "model": self.model,
            "content": self.content,
            "tool_arguments": self.tool_arguments,
            "usage": {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
            },
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> RecordedResponse:
        usage = data.get("usage") or {}
        return cls(
            mesh_response_id=str(data["mesh_response_id"]),
            model=str(data["model"]),
            content=data.get("content"),
            tool_arguments=data.get("tool_arguments"),
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
        )


class CassetteStore:
    def __init__(self, directory: str | Path, *, live_run_sha: str = "local") -> None:
        self.directory = Path(directory)
        self.live_run_sha = live_run_sha

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def has(self, request: dict[str, Any]) -> bool:
        return self._path(request_hash(request)).exists()

    def load(self, request: dict[str, Any]) -> RecordedResponse:
        key = request_hash(request)
        path = self._path(key)
        if not path.exists():
            raise CassetteMiss(
                f"no recorded Mesh response for request {key[:12]} "
                f"(tier={request.get('tier')}, model={request.get('model')}); "
                "re-record with MESH_CASSETTE_MODE=record"
            )
        entry = json.loads(path.read_text(encoding="utf-8"))
        if entry.get("format") != CASSETTE_FORMAT or entry.get("request_hash") != key:
            raise CassetteMiss(f"cassette {path.name} does not match its request")
        return RecordedResponse.from_json(entry["response"])

    def save(self, request: dict[str, Any], response: RecordedResponse) -> Path:
        key = request_hash(request)
        self.directory.mkdir(parents=True, exist_ok=True)
        entry = {
            "format": CASSETTE_FORMAT,
            "request_hash": key,
            "request": request,
            "response": response.as_json(),
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "live_run_sha": self.live_run_sha,
        }
        path = self._path(key)
        path.write_text(json.dumps(entry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path
