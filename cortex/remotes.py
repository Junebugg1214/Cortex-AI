"""
Remote push/pull/fork helpers for Git-for-AI-Memory stores.

Remotes are local or mounted filesystem paths that point at another `.cortex`
store, making multi-agent memory sync explicit and auditable.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cortex.upai.versioning import VersionStore


def _normalize_store_path(path: str | Path) -> Path:
    raw = Path(path)
    if raw.name == ".cortex":
        return raw
    if (raw / "history.json").exists() or (raw / "versions").exists():
        return raw
    return raw / ".cortex"


@dataclass
class MemoryRemote:
    name: str
    path: str
    default_branch: str = "main"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "default_branch": self.default_branch,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryRemote":
        return cls(
            name=data["name"],
            path=data["path"],
            default_branch=data.get("default_branch", "main"),
        )

    @property
    def store_path(self) -> Path:
        return _normalize_store_path(self.path)


class RemoteRegistry:
    def __init__(self, store_dir: str | Path) -> None:
        self.store_dir = Path(store_dir)
        self.path = self.store_dir / "remotes.json"

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"remotes": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def list_remotes(self) -> list[MemoryRemote]:
        payload = self._load()
        return [MemoryRemote.from_dict(item) for item in payload.get("remotes", [])]

    def get(self, name: str) -> MemoryRemote | None:
        for remote in self.list_remotes():
            if remote.name == name:
                return remote
        return None

    def add(self, remote: MemoryRemote) -> None:
        payload = self._load()
        remotes = [item for item in payload.get("remotes", []) if item.get("name") != remote.name]
        remotes.append(remote.to_dict())
        payload["remotes"] = sorted(remotes, key=lambda item: item["name"])
        self._save(payload)

    def remove(self, name: str) -> bool:
        payload = self._load()
        before = len(payload.get("remotes", []))
        payload["remotes"] = [item for item in payload.get("remotes", []) if item.get("name") != name]
        if len(payload["remotes"]) == before:
            return False
        self._save(payload)
        return True


def _required_records(store: VersionStore, ref: str) -> tuple[list[dict[str, Any]], str]:
    resolved = store.resolve_ref(ref)
    if resolved is None:
        raise ValueError(f"Unknown ref: {ref}")
    records = store.lineage_records(ref)
    if not records:
        raise ValueError(f"No history found for ref: {ref}")
    return records, resolved


def _import_records(target: VersionStore, source: VersionStore, records: list[dict[str, Any]]) -> int:
    target._ensure_dirs()
    history = target._load_history()
    existing_ids = {item["version_id"] for item in history}
    copied = 0

    for record in records:
        version_id = record["version_id"]
        source_snapshot = source.versions_dir / f"{version_id}.json"
        target_snapshot = target.versions_dir / f"{version_id}.json"
        if source_snapshot.exists() and not target_snapshot.exists():
            target_snapshot.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_snapshot, target_snapshot)
        if version_id not in existing_ids:
            history.append(dict(record))
            existing_ids.add(version_id)
            copied += 1

    if copied:
        target._save_history(history)
    return copied


def push_remote(
    local_store: VersionStore,
    remote: MemoryRemote,
    *,
    branch: str,
    target_branch: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    remote_store = VersionStore(remote.store_path)
    records, local_head = _required_records(local_store, branch)
    copied = _import_records(remote_store, local_store, records)
    remote_branch = target_branch or branch
    remote_head = remote_store.resolve_ref(remote_branch)

    if remote_head and remote_head != local_head and not remote_store.is_ancestor(remote_head, local_head):
        if not force:
            raise ValueError(f"Push would not be a fast-forward on remote branch '{remote_branch}'.")

    remote_store._write_ref(remote_branch, local_head)
    return {
        "status": "ok",
        "remote": remote.name,
        "remote_path": str(remote.store_path),
        "branch": branch,
        "remote_branch": remote_branch,
        "head": local_head,
        "versions_copied": copied,
        "force": force,
    }


def pull_remote(
    local_store: VersionStore,
    remote: MemoryRemote,
    *,
    branch: str,
    into_branch: str | None = None,
    force: bool = False,
    switch: bool = False,
) -> dict[str, Any]:
    remote_store = VersionStore(remote.store_path)
    records, remote_head = _required_records(remote_store, branch)
    copied = _import_records(local_store, remote_store, records)
    local_branch = into_branch or f"remotes/{remote.name}/{branch}"
    current_head = local_store.resolve_ref(local_branch)

    if current_head and current_head != remote_head and not local_store.is_ancestor(current_head, remote_head):
        if not force:
            raise ValueError(f"Pull would not be a fast-forward on local branch '{local_branch}'.")

    local_store._write_ref(local_branch, remote_head)
    if switch:
        local_store.switch_branch(local_branch)

    return {
        "status": "ok",
        "remote": remote.name,
        "remote_path": str(remote.store_path),
        "remote_branch": branch,
        "branch": local_branch,
        "head": remote_head,
        "versions_copied": copied,
        "switched": switch,
        "force": force,
    }


def fork_remote(
    local_store: VersionStore,
    remote: MemoryRemote,
    *,
    remote_branch: str,
    local_branch: str,
    switch: bool = False,
) -> dict[str, Any]:
    payload = pull_remote(
        local_store,
        remote,
        branch=remote_branch,
        into_branch=local_branch,
        force=False,
        switch=switch,
    )
    payload["forked"] = True
    return payload
