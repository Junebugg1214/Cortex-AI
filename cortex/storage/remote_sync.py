from __future__ import annotations

import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cortex.federation import (
    FederationBundle,
    FederationManager,
    FederationSignatureError,
    _compute_content_hash,
    _compute_signing_input,
)
from cortex.remote_trust import (
    ensure_store_identity,
    perform_remote_handshake,
    require_remote_namespace,
    write_remote_sync_receipt,
)
from cortex.remotes import _normalize_store_path
from cortex.schemas.memory_v1 import RemoteRecord
from cortex.storage.filesystem import FilesystemStorageBackend
from cortex.storage.sqlite import SQLiteStorageBackend, sqlite_db_path

NETWORK_REMOTE_SCHEMES = {"http", "https"}


def _backend_name(backend: Any) -> str:
    if isinstance(backend, SQLiteStorageBackend):
        return "sqlite"
    return "filesystem"


def _resolve_remote_store_path(remote: RemoteRecord) -> Path:
    return Path(remote.resolved_store_path) if remote.resolved_store_path else _normalize_store_path(remote.path)


def _remote_scheme(remote: RemoteRecord) -> str:
    return urllib.parse.urlparse(str(remote.path)).scheme.lower() or "file"


def _is_network_remote(remote: RemoteRecord) -> bool:
    return _remote_scheme(remote) in NETWORK_REMOTE_SCHEMES


def _remote_base_url(remote: RemoteRecord) -> str:
    parsed = urllib.parse.urlparse(str(remote.path))
    scheme = parsed.scheme.lower()
    if scheme not in NETWORK_REMOTE_SCHEMES:
        raise ValueError(f"Remote '{remote.name}' is not an HTTP remote.")
    return str(remote.path).rstrip("/")


def _open_remote_backend(remote: RemoteRecord, *, fallback_backend_type: str) -> Any:
    from cortex.storage import get_storage_backend

    store_path = _resolve_remote_store_path(remote)
    has_filesystem_store = (store_path / "history.json").exists() or (store_path / "versions").exists()
    has_sqlite_store = sqlite_db_path(store_path).exists()
    backend_type = None if (has_filesystem_store or has_sqlite_store) else fallback_backend_type
    return get_storage_backend(store_path, backend_type=backend_type)


def _backend_store_dir(backend: Any) -> Path:
    if isinstance(backend, SQLiteStorageBackend):
        return backend.store_dir
    if isinstance(backend, FilesystemStorageBackend):
        return backend.store_dir
    raise TypeError(f"Unsupported storage backend for sync: {type(backend)!r}")


def _remote_api_key(remote: RemoteRecord) -> str:
    normalized_name = "".join(ch if ch.isalnum() else "_" for ch in remote.name.upper())
    return (
        os.getenv(f"CORTEX_REMOTE_API_KEY_{normalized_name}", "").strip()
        or os.getenv("CORTEX_REMOTE_API_KEY", "").strip()
    )


def _http_headers(remote: RemoteRecord) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    token = _remote_api_key(remote)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _decode_http_error(exc: urllib.error.HTTPError) -> Exception:
    body = exc.read().decode("utf-8", errors="replace")
    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        payload = {}
    message = str(payload.get("error") or payload.get("message") or body or exc.reason)
    code = str(payload.get("code") or "")
    if code in {"malformed_bundle", "untrusted_key", "signature_invalid"}:
        return FederationSignatureError(message, code=code)
    return ValueError(f"Remote HTTP {exc.code}: {message}")


def _http_json(remote: RemoteRecord, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    url = _remote_base_url(remote) + path
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, headers=_http_headers(remote), method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310 - remote URL scheme is restricted to http(s).
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise _decode_http_error(exc) from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"Remote HTTP request failed: {exc.reason}") from exc
    try:
        decoded = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise ValueError("Remote HTTP response was not valid JSON.") from exc
    if not isinstance(decoded, dict):
        raise ValueError("Remote HTTP response must be a JSON object.")
    return decoded


def _export_bundle(backend: Any, ref: str) -> dict[str, Any]:
    if isinstance(backend, SQLiteStorageBackend):
        return backend.versions._export_bundle(ref)

    if isinstance(backend, FilesystemStorageBackend):
        store = backend.versions.store
        resolved = store.resolve_ref(ref)
        if resolved is None:
            raise ValueError(f"Unknown ref: {ref}")
        records = store.lineage_records(ref)
        if not records:
            raise ValueError(f"No history found for ref: {ref}")
        version_ids = {item["version_id"] for item in records}
        snapshots: dict[str, str] = {}
        for version_id in sorted(version_ids):
            snapshot_path = store.versions_dir / f"{version_id}.json"
            if snapshot_path.exists():
                snapshots[version_id] = snapshot_path.read_text(encoding="utf-8")
        return {"head": resolved, "records": records, "snapshots": snapshots}

    raise TypeError(f"Unsupported storage backend for export: {type(backend)!r}")


def _snapshot_counts(sync_payload: dict[str, Any]) -> tuple[int, int]:
    head = str(sync_payload.get("head") or "")
    graph_json = dict(sync_payload.get("snapshots") or {}).get(head, "")
    if not graph_json:
        return 0, 0
    try:
        payload = json.loads(graph_json)
    except json.JSONDecodeError:
        return 0, 0
    meta = payload.get("meta", {})
    return int(meta.get("node_count", 0)), int(meta.get("edge_count", 0))


def _signed_sync_bundle(backend: Any, ref: str, *, branch: str) -> FederationBundle:
    store_dir = _backend_store_dir(backend)
    identity = ensure_store_identity(store_dir, name_hint=f"Cortex {store_dir.name}")
    if identity._key_type != "ed25519":
        raise FederationSignatureError(
            "malformed bundle: HTTP remotes require an Ed25519 identity.",
            code="malformed_bundle",
        )

    sync_payload = _export_bundle(backend, ref)
    graph_data = {
        "remote_sync": {
            "version": 1,
            "branch": branch,
            "head": sync_payload["head"],
            "records": list(sync_payload.get("records", [])),
            "snapshots": dict(sync_payload.get("snapshots", {})),
        }
    }
    node_count, edge_count = _snapshot_counts(sync_payload)
    now = datetime.now(timezone.utc)
    bundle = FederationBundle(
        version="1.0",
        exporter_did=identity.did,
        exporter_public_key_b64=identity.public_key_b64,
        nonce=secrets.token_hex(16),
        created_at=now.isoformat(),
        expires_at=datetime.fromtimestamp(now.timestamp() + 3600, tz=timezone.utc).isoformat(),
        policy="remote-sync",
        graph_data=graph_data,
        node_count=node_count,
        edge_count=edge_count,
        content_hash=_compute_content_hash(graph_data),
        signature="",
        metadata={"transport": "http-remote", "branch": branch},
    )
    bundle.signature = identity.sign(_compute_signing_input(bundle.to_dict()))
    return bundle


def _bundle_from_payload(payload: dict[str, Any]) -> FederationBundle:
    try:
        return FederationBundle.from_dict(payload)
    except (KeyError, TypeError) as exc:
        raise FederationSignatureError(
            "malformed bundle: " + str(exc),
            code="malformed_bundle",
        ) from exc


def _sync_payload_from_bundle(bundle: FederationBundle) -> dict[str, Any]:
    sync_payload = bundle.graph_data.get("remote_sync")
    if not isinstance(sync_payload, dict):
        raise FederationSignatureError(
            "malformed bundle: missing remote_sync payload",
            code="malformed_bundle",
        )
    for key in ("branch", "head", "records", "snapshots"):
        if key not in sync_payload:
            raise FederationSignatureError(
                f"malformed bundle: missing remote_sync.{key}",
                code="malformed_bundle",
            )
    return sync_payload


def _verify_signed_sync_bundle(
    backend: Any,
    bundle_payload: dict[str, Any],
    *,
    pinned_did: str,
    pinned_public_key_b64: str = "",
) -> tuple[FederationBundle, dict[str, Any]]:
    bundle = _bundle_from_payload(bundle_payload)
    if not pinned_did or bundle.exporter_did != pinned_did:
        raise FederationSignatureError("untrusted key", code="untrusted_key")
    if pinned_public_key_b64 and bundle.exporter_public_key_b64 != pinned_public_key_b64:
        raise FederationSignatureError("untrusted key", code="untrusted_key")

    manager = FederationManager(
        identity=ensure_store_identity(_backend_store_dir(backend), name_hint="Cortex remote verifier"),
        trusted_dids=[pinned_did],
        store_dir=_backend_store_dir(backend),
    )
    manager._verify_signature(bundle, check_trust=True)
    return bundle, _sync_payload_from_bundle(bundle)


def _trusted_remote_for_bundle(backend: Any, bundle: FederationBundle, branch: str) -> RemoteRecord:
    for remote in backend.remotes.list_remotes():
        if remote.trusted_did != bundle.exporter_did:
            continue
        if remote.trusted_public_key_b64 and remote.trusted_public_key_b64 != bundle.exporter_public_key_b64:
            raise FederationSignatureError("untrusted key", code="untrusted_key")
        try:
            require_remote_namespace(remote, branch)
        except ValueError:
            continue
        return remote
    raise FederationSignatureError("untrusted key", code="untrusted_key")


def export_signed_remote_bundle(backend: Any, *, branch: str) -> dict[str, Any]:
    bundle = _signed_sync_bundle(backend, branch, branch=branch)
    sync_payload = _sync_payload_from_bundle(bundle)
    return {
        "status": "ok",
        "branch": branch,
        "head": sync_payload["head"],
        "bundle": bundle.to_dict(),
    }


def import_signed_remote_bundle(
    backend: Any,
    *,
    bundle_payload: dict[str, Any],
    force: bool = False,
) -> dict[str, Any]:
    bundle = _bundle_from_payload(bundle_payload)
    sync_payload = _sync_payload_from_bundle(bundle)
    branch = str(sync_payload.get("branch") or "")
    head = str(sync_payload.get("head") or "")
    if not branch or not head:
        raise FederationSignatureError("malformed bundle: missing branch head", code="malformed_bundle")

    trusted_remote = _trusted_remote_for_bundle(backend, bundle, branch)
    _, sync_payload = _verify_signed_sync_bundle(
        backend,
        bundle_payload,
        pinned_did=trusted_remote.trusted_did,
        pinned_public_key_b64=trusted_remote.trusted_public_key_b64,
    )
    copied = _import_bundle(backend, sync_payload)
    current_head = backend.versions.resolve_ref(branch)
    if current_head and current_head != head and not backend.versions.is_ancestor(current_head, head):
        if not force:
            raise ValueError(f"Push would not be a fast-forward on remote branch '{branch}'.")
    _set_branch_head(backend, branch, head)
    return {
        "status": "ok",
        "branch": branch,
        "head": head,
        "versions_copied": copied,
        "force": force,
        "trusted_remote_did": trusted_remote.trusted_did,
        "exporter_did": bundle.exporter_did,
        "node_count": bundle.node_count,
        "edge_count": bundle.edge_count,
    }


def _import_bundle(backend: Any, bundle: dict[str, Any]) -> int:
    if isinstance(backend, SQLiteStorageBackend):
        return backend.versions._import_bundle(bundle)

    if isinstance(backend, FilesystemStorageBackend):
        store = backend.versions.store
        store._ensure_dirs()
        history = store._load_history()
        existing_ids = {item["version_id"] for item in history}
        copied = 0

        for version_id, graph_json in bundle.get("snapshots", {}).items():
            snapshot_path = store.versions_dir / f"{version_id}.json"
            if snapshot_path.exists():
                continue
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_path.write_text(graph_json, encoding="utf-8")

        for record in bundle.get("records", []):
            version_id = record["version_id"]
            if version_id in existing_ids:
                continue
            history.append(dict(record))
            existing_ids.add(version_id)
            copied += 1

        if copied:
            store._save_history(history)
        return copied

    raise TypeError(f"Unsupported storage backend for import: {type(backend)!r}")


def _set_branch_head(backend: Any, branch: str, version_id: str | None) -> None:
    if isinstance(backend, SQLiteStorageBackend):
        backend.versions._write_ref(branch, version_id)
        return
    if isinstance(backend, FilesystemStorageBackend):
        backend.versions.store._write_ref(branch, version_id)
        return
    raise TypeError(f"Unsupported storage backend for ref update: {type(backend)!r}")


def push_remote_backend(
    local_backend: Any,
    remote: RemoteRecord,
    branch: str,
    target_branch: str | None,
    force: bool,
) -> dict[str, Any]:
    if _is_network_remote(remote):
        return _push_http_remote(local_backend, remote, branch, target_branch, force)

    local_store_dir = _backend_store_dir(local_backend)
    local_branch = branch if branch != "HEAD" else local_backend.versions.current_branch()
    remote_branch = target_branch or local_branch
    require_remote_namespace(remote, remote_branch)
    handshake = perform_remote_handshake(
        local_store_dir,
        remote,
        direction="push",
        branch=local_branch,
        remote_branch=remote_branch,
    )
    remote_backend = _open_remote_backend(remote, fallback_backend_type=_backend_name(local_backend))
    local_head = local_backend.versions.resolve_ref(branch)
    if local_head is None:
        raise ValueError(f"Unknown ref: {branch}")
    bundle = _export_bundle(local_backend, branch)
    copied = _import_bundle(remote_backend, bundle)
    remote_head = remote_backend.versions.resolve_ref(remote_branch)

    if remote_head and remote_head != local_head and not remote_backend.versions.is_ancestor(remote_head, local_head):
        if not force:
            raise ValueError(f"Push would not be a fast-forward on remote branch '{remote_branch}'.")

    _set_branch_head(remote_backend, remote_branch, local_head)
    receipt_path = write_remote_sync_receipt(
        local_store_dir,
        {
            "direction": "push",
            "remote": remote.name,
            "branch": local_branch,
            "remote_branch": remote_branch,
            "head": local_head,
            "versions_copied": copied,
            "force": force,
            **handshake,
        },
    )
    return {
        "status": "ok",
        "remote": remote.name,
        "remote_path": str(_resolve_remote_store_path(remote)),
        "branch": local_branch,
        "remote_branch": remote_branch,
        "head": local_head,
        "versions_copied": copied,
        "force": force,
        "trusted_remote_did": handshake["remote_did"],
        "local_did": handshake["local_did"],
        "allowed_namespaces": list(handshake["allowed_namespaces"]),
        "receipt_path": receipt_path,
    }


def pull_remote_backend(
    local_backend: Any,
    remote: RemoteRecord,
    branch: str,
    into_branch: str | None,
    force: bool,
    switch: bool,
) -> dict[str, Any]:
    if _is_network_remote(remote):
        return _pull_http_remote(local_backend, remote, branch, into_branch, force, switch)

    local_store_dir = _backend_store_dir(local_backend)
    require_remote_namespace(remote, branch)
    handshake = perform_remote_handshake(
        local_store_dir,
        remote,
        direction="pull",
        branch=branch,
        remote_branch=branch,
    )
    remote_backend = _open_remote_backend(remote, fallback_backend_type=_backend_name(local_backend))
    remote_head = remote_backend.versions.resolve_ref(branch)
    if remote_head is None:
        raise ValueError(f"Unknown ref: {branch}")
    bundle = _export_bundle(remote_backend, branch)
    copied = _import_bundle(local_backend, bundle)
    local_branch = into_branch or f"remotes/{remote.name}/{branch}"
    current_head = local_backend.versions.resolve_ref(local_branch)

    if (
        current_head
        and current_head != remote_head
        and not local_backend.versions.is_ancestor(current_head, remote_head)
    ):
        if not force:
            raise ValueError(f"Pull would not be a fast-forward on local branch '{local_branch}'.")

    _set_branch_head(local_backend, local_branch, remote_head)
    if switch:
        local_backend.versions.switch_branch(local_branch)
    receipt_path = write_remote_sync_receipt(
        local_store_dir,
        {
            "direction": "pull",
            "remote": remote.name,
            "branch": local_branch,
            "remote_branch": branch,
            "head": remote_head,
            "versions_copied": copied,
            "switched": switch,
            "force": force,
            **handshake,
        },
    )

    return {
        "status": "ok",
        "remote": remote.name,
        "remote_path": str(_resolve_remote_store_path(remote)),
        "remote_branch": branch,
        "branch": local_branch,
        "head": remote_head,
        "versions_copied": copied,
        "switched": switch,
        "force": force,
        "trusted_remote_did": handshake["remote_did"],
        "local_did": handshake["local_did"],
        "allowed_namespaces": list(handshake["allowed_namespaces"]),
        "receipt_path": receipt_path,
    }


def _push_http_remote(
    local_backend: Any,
    remote: RemoteRecord,
    branch: str,
    target_branch: str | None,
    force: bool,
) -> dict[str, Any]:
    local_store_dir = _backend_store_dir(local_backend)
    local_branch = branch if branch != "HEAD" else local_backend.versions.current_branch()
    remote_branch = target_branch or local_branch
    require_remote_namespace(remote, remote_branch)
    local_head = local_backend.versions.resolve_ref(branch)
    if local_head is None:
        raise ValueError(f"Unknown ref: {branch}")

    bundle = _signed_sync_bundle(local_backend, branch, branch=remote_branch)
    response = _http_json(
        remote,
        "POST",
        "/v1/remotes/push",
        {"bundle": bundle.to_dict(), "force": force},
    )
    if str(response.get("head") or "") != local_head:
        raise ValueError("Remote push response head did not match the pushed head.")

    receipt_path = write_remote_sync_receipt(
        local_store_dir,
        {
            "direction": "push",
            "remote": remote.name,
            "branch": local_branch,
            "remote_branch": remote_branch,
            "head": local_head,
            "versions_copied": int(response.get("versions_copied", 0)),
            "force": force,
            "local_did": bundle.exporter_did,
            "remote_did": remote.trusted_did,
            "allowed_namespaces": list(remote.allowed_namespaces),
            "transport": "http",
        },
    )
    return {
        "status": "ok",
        "remote": remote.name,
        "remote_path": remote.path,
        "branch": local_branch,
        "remote_branch": remote_branch,
        "head": local_head,
        "versions_copied": int(response.get("versions_copied", 0)),
        "force": force,
        "trusted_remote_did": remote.trusted_did,
        "local_did": bundle.exporter_did,
        "allowed_namespaces": list(remote.allowed_namespaces),
        "receipt_path": receipt_path,
        "transport": "http",
    }


def _pull_http_remote(
    local_backend: Any,
    remote: RemoteRecord,
    branch: str,
    into_branch: str | None,
    force: bool,
    switch: bool,
) -> dict[str, Any]:
    local_store_dir = _backend_store_dir(local_backend)
    require_remote_namespace(remote, branch)
    query = urllib.parse.urlencode({"branch": branch})
    response = _http_json(remote, "GET", f"/v1/remotes/pull?{query}")
    bundle_payload = response.get("bundle")
    if not isinstance(bundle_payload, dict):
        raise FederationSignatureError("malformed bundle: missing bundle", code="malformed_bundle")
    bundle, sync_payload = _verify_signed_sync_bundle(
        local_backend,
        bundle_payload,
        pinned_did=remote.trusted_did,
        pinned_public_key_b64=remote.trusted_public_key_b64,
    )
    remote_head = str(sync_payload.get("head") or "")
    copied = _import_bundle(local_backend, sync_payload)
    local_branch = into_branch or f"remotes/{remote.name}/{branch}"
    current_head = local_backend.versions.resolve_ref(local_branch)
    if (
        current_head
        and current_head != remote_head
        and not local_backend.versions.is_ancestor(current_head, remote_head)
    ):
        if not force:
            raise ValueError(f"Pull would not be a fast-forward on local branch '{local_branch}'.")

    _set_branch_head(local_backend, local_branch, remote_head)
    if switch:
        local_backend.versions.switch_branch(local_branch)
    receipt_path = write_remote_sync_receipt(
        local_store_dir,
        {
            "direction": "pull",
            "remote": remote.name,
            "branch": local_branch,
            "remote_branch": branch,
            "head": remote_head,
            "versions_copied": copied,
            "switched": switch,
            "force": force,
            "local_did": ensure_store_identity(local_store_dir, name_hint=f"Cortex {local_store_dir.name}").did,
            "remote_did": bundle.exporter_did,
            "allowed_namespaces": list(remote.allowed_namespaces),
            "transport": "http",
        },
    )

    return {
        "status": "ok",
        "remote": remote.name,
        "remote_path": remote.path,
        "remote_branch": branch,
        "branch": local_branch,
        "head": remote_head,
        "versions_copied": copied,
        "switched": switch,
        "force": force,
        "trusted_remote_did": remote.trusted_did,
        "local_did": ensure_store_identity(local_store_dir, name_hint=f"Cortex {local_store_dir.name}").did,
        "allowed_namespaces": list(remote.allowed_namespaces),
        "receipt_path": receipt_path,
        "transport": "http",
    }


def fork_remote_backend(
    local_backend: Any,
    remote: RemoteRecord,
    remote_branch: str,
    local_branch: str,
    switch: bool,
) -> dict[str, Any]:
    payload = pull_remote_backend(
        local_backend,
        remote,
        branch=remote_branch,
        into_branch=local_branch,
        force=False,
        switch=switch,
    )
    payload["forked"] = True
    return payload
