"""
Remote push/pull/fork helpers for Git-for-AI-Memory stores.

Remotes are local or mounted filesystem paths that point at another `.cortex`
store, making multi-agent memory sync explicit and auditable.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cortex.atomic_io import atomic_write_text, locked_path
from cortex.remote_trust import NETWORK_REMOTE_SCHEMES, _normalize_store_path, prepare_remote_fields
from cortex.upai.versioning import VersionStore


@dataclass
class MemoryRemote:
    name: str
    path: str
    default_branch: str = "main"
    trusted_did: str = ""
    trusted_public_key_b64: str = ""
    allowed_namespaces: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "default_branch": self.default_branch,
            "trusted_did": self.trusted_did,
            "trusted_public_key_b64": self.trusted_public_key_b64,
            "allowed_namespaces": list(self.allowed_namespaces),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryRemote":
        return cls(
            name=data["name"],
            path=data["path"],
            default_branch=data.get("default_branch", "main"),
            trusted_did=data.get("trusted_did", ""),
            trusted_public_key_b64=data.get("trusted_public_key_b64", ""),
            allowed_namespaces=list(data.get("allowed_namespaces", [data.get("default_branch", "main")])),
        )

    @property
    def store_path(self) -> Path:
        if self.is_network:
            raise AttributeError("Network remotes do not have a local store_path.")
        return _normalize_store_path(self.path)

    @property
    def scheme(self) -> str:
        return urlparse(self.path).scheme.lower() or "file"

    @property
    def is_network(self) -> bool:
        return self.scheme in NETWORK_REMOTE_SCHEMES


class RemoteRegistry:
    def __init__(self, store_dir: str | Path) -> None:
        self.store_dir = Path(store_dir)
        self.path = self.store_dir / "remotes.json"

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"remotes": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, payload: dict[str, Any]) -> None:
        atomic_write_text(self.path, json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def list_remotes(self) -> list[MemoryRemote]:
        payload = self._load()
        return [MemoryRemote.from_dict(item) for item in payload.get("remotes", [])]

    def get(self, name: str) -> MemoryRemote | None:
        for remote in self.list_remotes():
            if remote.name == name:
                return remote
        return None

    def add(self, remote: MemoryRemote) -> None:
        with locked_path(self.store_dir):
            prepared = prepare_remote_fields(remote)
            stored = MemoryRemote(
                name=remote.name,
                path=remote.path,
                default_branch=remote.default_branch,
                trusted_did=prepared["trusted_did"],
                trusted_public_key_b64=prepared["trusted_public_key_b64"],
                allowed_namespaces=list(prepared["allowed_namespaces"]),
            )
            payload = self._load()
            remotes = [item for item in payload.get("remotes", []) if item.get("name") != stored.name]
            remotes.append(stored.to_dict())
            payload["remotes"] = sorted(remotes, key=lambda item: item["name"])
            self._save(payload)

    def remove(self, name: str) -> bool:
        with locked_path(self.store_dir):
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
    if remote.is_network:
        from cortex.schemas.memory_v1 import RemoteRecord
        from cortex.storage.filesystem import FilesystemStorageBackend
        from cortex.storage.remote_sync import push_remote_backend

        return push_remote_backend(
            FilesystemStorageBackend(local_store.store_dir),
            RemoteRecord.from_memory_remote(remote),
            branch,
            target_branch,
            force,
        )

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
    if remote.is_network:
        from cortex.schemas.memory_v1 import RemoteRecord
        from cortex.storage.filesystem import FilesystemStorageBackend
        from cortex.storage.remote_sync import pull_remote_backend

        return pull_remote_backend(
            FilesystemStorageBackend(local_store.store_dir),
            RemoteRecord.from_memory_remote(remote),
            branch,
            into_branch,
            force,
            switch,
        )

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
