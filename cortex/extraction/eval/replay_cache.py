from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

ReplayMode = Literal["read", "write", "off"]

DEFAULT_REPLAY_CACHE_ROOT = Path(".cortex-cache") / "extraction-replay"


def replay_mode_from_env(env: dict[str, str] | None = None) -> ReplayMode:
    """Resolve replay mode from the environment.

    Dev defaults to off so model calls behave normally. CI defaults to read so
    harnesses can consume committed or pre-seeded replay artifacts without
    writing local state.
    """

    env = os.environ if env is None else env
    explicit = env.get("CORTEX_EXTRACTION_REPLAY", "").strip().lower()
    if explicit in {"read", "write", "off"}:
        return explicit  # type: ignore[return-value]
    if explicit:
        return "off"
    ci = env.get("CI", "").strip().lower()
    return "read" if ci in {"1", "true", "yes", "on"} else "off"


@dataclass(frozen=True)
class ReplayCache:
    """Filesystem-backed cache for deterministic extraction replay responses."""

    root: Path = DEFAULT_REPLAY_CACHE_ROOT
    mode: ReplayMode = "off"

    @classmethod
    def from_env(cls, *, env: dict[str, str] | None = None) -> ReplayCache:
        env = os.environ if env is None else env
        root = Path(env.get("CORTEX_EXTRACTION_REPLAY_DIR", "").strip() or DEFAULT_REPLAY_CACHE_ROOT)
        return cls(root=root, mode=replay_mode_from_env(env))

    @staticmethod
    def key(*, prompt_version: str, input_content: str, model_id: str) -> str:
        return hashlib.sha256(f"{prompt_version}{input_content}{model_id}".encode("utf-8")).hexdigest()

    @property
    def can_read(self) -> bool:
        return self.mode in {"read", "write"}

    @property
    def can_write(self) -> bool:
        return self.mode == "write"

    def path_for_key(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def read(self, *, prompt_version: str, input_content: str, model_id: str) -> dict[str, Any] | None:
        if not self.can_read:
            return None
        key = self.key(prompt_version=prompt_version, input_content=input_content, model_id=model_id)
        path = self.path_for_key(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    def write(
        self,
        *,
        prompt_version: str,
        input_content: str,
        model_id: str,
        payload: dict[str, Any],
    ) -> Path | None:
        if not self.can_write:
            return None
        key = self.key(prompt_version=prompt_version, input_content=input_content, model_id=model_id)
        record = {
            "key": key,
            "prompt_version": prompt_version,
            "model_id": model_id,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "payload": payload,
        }
        path = self.path_for_key(key)
        temp_path = path.with_suffix(".json.tmp")
        self.root.mkdir(parents=True, exist_ok=True)
        temp_path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(path)
        return path
