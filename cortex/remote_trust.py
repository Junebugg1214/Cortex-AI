from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from cortex.atomic_io import atomic_write_json
from cortex.namespaces import acl_allows_namespace, normalize_acl_namespaces
from cortex.upai.identity import UPAIIdentity

NETWORK_REMOTE_SCHEMES = {"http", "https"}


def _remote_scheme(path: str | Path) -> str:
    return urlparse(str(path)).scheme.lower()


def _is_network_remote_path(path: str | Path) -> bool:
    return _remote_scheme(path) in NETWORK_REMOTE_SCHEMES


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _normalize_store_path(path: str | Path) -> Path:
    parsed = urlparse(str(path))
    if parsed.scheme == "file":
        path = unquote(parsed.path)
    raw = Path(path)
    if raw.name == ".cortex":
        return raw
    if (raw / "history.json").exists() or (raw / "versions").exists():
        return raw
    return raw / ".cortex"


def _remote_store_path(remote: Any) -> Path:
    resolved = str(getattr(remote, "resolved_store_path", "") or "").strip()
    return Path(resolved) if resolved else _normalize_store_path(getattr(remote, "path"))


def ensure_store_identity(store_dir: Path, *, name_hint: str) -> UPAIIdentity:
    root = Path(store_dir)
    identity_path = root / "identity.json"
    if identity_path.exists():
        return UPAIIdentity.load(root)
    identity = UPAIIdentity.generate(name_hint)
    identity.save(root)
    return identity


def prepare_remote_fields(remote: Any) -> dict[str, Any]:
    raw_path = str(getattr(remote, "path", "") or "").strip()
    scheme = _remote_scheme(raw_path)
    allowed_namespaces = list(
        normalize_acl_namespaces(
            list(getattr(remote, "allowed_namespaces", []) or []) or [str(getattr(remote, "default_branch", "main"))]
        )
    )
    if scheme in NETWORK_REMOTE_SCHEMES:
        pinned_did = str(getattr(remote, "trusted_did", "") or "").strip()
        pinned_public_key = str(getattr(remote, "trusted_public_key_b64", "") or "").strip()
        if not pinned_did:
            raise ValueError(f"Network remote '{getattr(remote, 'name', 'origin')}' requires a pinned trusted_did.")
        if pinned_did.startswith("did:upai:") and not pinned_public_key:
            raise ValueError(
                f"Network remote '{getattr(remote, 'name', 'origin')}' requires a pinned public key for {pinned_did}."
            )
        return {
            "resolved_store_path": "",
            "trusted_did": pinned_did,
            "trusted_public_key_b64": pinned_public_key,
            "allowed_namespaces": allowed_namespaces,
        }
    if scheme and scheme != "file":
        raise ValueError(f"Unsupported remote scheme '{scheme}'. Supported schemes: file, http, https.")

    store_path = _remote_store_path(remote)
    identity = ensure_store_identity(store_path, name_hint=f"Remote {getattr(remote, 'name', 'origin')}")
    pinned_did = str(getattr(remote, "trusted_did", "") or "").strip()
    pinned_public_key = str(getattr(remote, "trusted_public_key_b64", "") or "").strip()
    if pinned_did and pinned_did != identity.did:
        raise ValueError(
            f"Remote '{getattr(remote, 'name', 'origin')}' identity mismatch: expected DID {pinned_did}, found {identity.did}."
        )
    if pinned_public_key and pinned_public_key != identity.public_key_b64:
        raise ValueError(
            f"Remote '{getattr(remote, 'name', 'origin')}' public key mismatch with the pinned trust record."
        )
    return {
        "resolved_store_path": str(store_path),
        "trusted_did": identity.did,
        "trusted_public_key_b64": identity.public_key_b64,
        "allowed_namespaces": allowed_namespaces,
    }


def require_remote_namespace(remote: Any, namespace: str) -> None:
    prepared = prepare_remote_fields(remote)
    allowed_namespaces = tuple(str(item) for item in prepared["allowed_namespaces"])
    if acl_allows_namespace(allowed_namespaces, namespace):
        return
    joined = ", ".join(allowed_namespaces)
    raise ValueError(
        f"Remote '{getattr(remote, 'name', 'origin')}' does not allow namespace '{namespace}'. Allowed: {joined}."
    )


def perform_remote_handshake(
    local_store_dir: Path,
    remote: Any,
    *,
    direction: str,
    branch: str,
    remote_branch: str,
) -> dict[str, Any]:
    local_identity = ensure_store_identity(Path(local_store_dir), name_hint=f"Cortex {Path(local_store_dir).name}")
    prepared = prepare_remote_fields(remote)
    remote_store_path = Path(prepared["resolved_store_path"])
    remote_identity = ensure_store_identity(remote_store_path, name_hint=f"Remote {getattr(remote, 'name', 'origin')}")
    payload = {
        "version": "1",
        "direction": direction,
        "remote": str(getattr(remote, "name", "origin")),
        "branch": branch,
        "remote_branch": remote_branch,
        "local_did": local_identity.did,
        "remote_did": remote_identity.did,
        "nonce": secrets.token_hex(16),
        "created_at": _iso_now(),
    }
    message = _canonical_json_bytes(payload)
    remote_signature = remote_identity.sign(message)
    local_signature = local_identity.sign(message)
    if remote_identity._key_type == "ed25519":
        if not UPAIIdentity.verify(message, remote_signature, remote_identity.public_key_b64, key_type="ed25519"):
            raise ValueError(f"Remote '{getattr(remote, 'name', 'origin')}' failed handshake signature verification.")
    elif not remote_identity.verify_own(message, remote_signature):
        raise ValueError(f"Remote '{getattr(remote, 'name', 'origin')}' failed local handshake verification.")
    if local_identity._key_type == "ed25519":
        if not UPAIIdentity.verify(message, local_signature, local_identity.public_key_b64, key_type="ed25519"):
            raise ValueError("Local sync handshake verification failed.")
    elif not local_identity.verify_own(message, local_signature):
        raise ValueError("Local sync handshake verification failed.")
    return {
        **payload,
        "local_public_key_b64": local_identity.public_key_b64,
        "remote_public_key_b64": remote_identity.public_key_b64,
        "local_signature": local_signature,
        "remote_signature": remote_signature,
        "allowed_namespaces": list(prepared["allowed_namespaces"]),
        "remote_store_path": str(remote_store_path),
    }


def write_remote_sync_receipt(local_store_dir: Path, payload: dict[str, Any]) -> str:
    receipt_id = f"remote-sync-{secrets.token_hex(8)}"
    receipt = {
        "receipt_id": receipt_id,
        "recorded_at": _iso_now(),
        **payload,
    }
    receipt_path = Path(local_store_dir) / "remote-sync-receipts" / f"{receipt_id}.json"
    atomic_write_json(receipt_path, receipt)
    return str(receipt_path)


__all__ = [
    "NETWORK_REMOTE_SCHEMES",
    "_is_network_remote_path",
    "_normalize_store_path",
    "ensure_store_identity",
    "perform_remote_handshake",
    "prepare_remote_fields",
    "require_remote_namespace",
    "write_remote_sync_receipt",
]
