"""Connector service for external LLM/chatbot account links."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from cortex.caas.storage import AbstractConnectorStore

SUPPORTED_PROVIDERS = frozenset({
    "anthropic",
    "github",
    "google",
    "meta",
    "mistral",
    "openai",
    "perplexity",
    "xai",
})

VALID_STATUSES = frozenset({"active", "paused", "error"})
VALID_JOBS = frozenset({"memory_pull_prompt", "github_repo_sync", "custom_json_sync"})

DEFAULT_JOB_BY_PROVIDER = {
    "github": "github_repo_sync",
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConnectorService:
    """Validation + lifecycle operations for connectors."""

    def __init__(self, store: AbstractConnectorStore) -> None:
        self._store = store

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider = str(payload.get("provider", "")).strip().lower()
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(
                "Invalid provider. Must be one of: "
                + ", ".join(sorted(SUPPORTED_PROVIDERS))
            )
        scopes = payload.get("scopes", [])
        if scopes is None:
            scopes = []
        if not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes):
            raise ValueError("scopes must be a list of strings")

        metadata = payload.get("metadata", {})
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        metadata = dict(metadata)

        default_job = DEFAULT_JOB_BY_PROVIDER.get(provider, "memory_pull_prompt")
        job = str(payload.get("job", metadata.get("_job", default_job))).strip().lower()
        if job not in VALID_JOBS:
            raise ValueError(
                "Invalid job. Must be one of: "
                + ", ".join(sorted(VALID_JOBS))
            )
        job_config = payload.get("job_config", metadata.get("_job_config", {}))
        if job_config is None:
            job_config = {}
        if not isinstance(job_config, dict):
            raise ValueError("job_config must be an object")
        metadata["_job"] = job
        metadata["_job_config"] = dict(job_config)
        metadata.setdefault("_auto_sync_enabled", True)
        metadata.setdefault("_auto_sync_interval_seconds", 24 * 60 * 60)
        metadata.setdefault("_last_sync_status", "idle")
        metadata.setdefault("_last_sync_error", "")
        metadata.setdefault("_last_sync_message", "")

        status = str(payload.get("status", "active")).strip().lower()
        if status not in VALID_STATUSES:
            raise ValueError(
                "Invalid status. Must be one of: "
                + ", ".join(sorted(VALID_STATUSES))
            )

        now = _utcnow()
        connector_id = f"cn_{secrets.token_hex(8)}"
        connector = {
            "connector_id": connector_id,
            "provider": provider,
            "account_label": str(payload.get("account_label", "")).strip(),
            "external_user_id": str(payload.get("external_user_id", "")).strip(),
            "scopes": list(scopes),
            "status": status,
            "metadata": metadata,
            "created_at": now,
            "updated_at": now,
            "last_sync_at": "",
        }
        self._store.add(connector)
        return connector

    def get(self, connector_id: str) -> dict[str, Any] | None:
        return self._store.get(connector_id)

    def list_all(self) -> list[dict[str, Any]]:
        connectors = self._store.list_all()
        connectors.sort(key=lambda x: x.get("created_at", ""))
        return connectors

    def update(self, connector_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        current = self._store.get(connector_id)
        if current is None:
            return None

        updates: dict[str, Any] = {}
        current_metadata = current.get("metadata", {})
        if not isinstance(current_metadata, dict):
            current_metadata = {}
        resolved_metadata: dict[str, Any] = dict(current_metadata)

        if "provider" in payload:
            provider = str(payload.get("provider", "")).strip().lower()
            if provider != current.get("provider", ""):
                raise ValueError("provider is immutable")
        if "account_label" in payload:
            updates["account_label"] = str(payload.get("account_label", "")).strip()
        if "external_user_id" in payload:
            updates["external_user_id"] = str(payload.get("external_user_id", "")).strip()
        if "scopes" in payload:
            scopes = payload.get("scopes", [])
            if not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes):
                raise ValueError("scopes must be a list of strings")
            updates["scopes"] = list(scopes)
        if "metadata" in payload:
            metadata = payload.get("metadata", {})
            if not isinstance(metadata, dict):
                raise ValueError("metadata must be an object")
            resolved_metadata = dict(metadata)
        if "job" in payload or "job_config" in payload:
            provider = str(current.get("provider", "")).strip().lower()
            default_job = DEFAULT_JOB_BY_PROVIDER.get(provider, "memory_pull_prompt")
            next_job = str(payload.get("job", resolved_metadata.get("_job", default_job))).strip().lower()
            if next_job not in VALID_JOBS:
                raise ValueError(
                    "Invalid job. Must be one of: "
                    + ", ".join(sorted(VALID_JOBS))
                )
            next_job_config = payload.get("job_config", resolved_metadata.get("_job_config", {}))
            if next_job_config is None:
                next_job_config = {}
            if not isinstance(next_job_config, dict):
                raise ValueError("job_config must be an object")
            resolved_metadata["_job"] = next_job
            resolved_metadata["_job_config"] = dict(next_job_config)
            resolved_metadata.setdefault("_auto_sync_enabled", True)
            resolved_metadata.setdefault("_auto_sync_interval_seconds", 24 * 60 * 60)
            resolved_metadata.setdefault("_last_sync_status", "idle")
            resolved_metadata.setdefault("_last_sync_error", "")
            resolved_metadata.setdefault("_last_sync_message", "")
        if "status" in payload:
            status = str(payload.get("status", "")).strip().lower()
            if status not in VALID_STATUSES:
                raise ValueError(
                    "Invalid status. Must be one of: "
                    + ", ".join(sorted(VALID_STATUSES))
                )
            updates["status"] = status
        if "last_sync_at" in payload:
            updates["last_sync_at"] = str(payload.get("last_sync_at", "")).strip()

        metadata_changed = (
            "metadata" in payload
            or "job" in payload
            or "job_config" in payload
        )
        if metadata_changed:
            updates["metadata"] = resolved_metadata

        if not updates:
            return current
        updates["updated_at"] = _utcnow()
        return self._store.update(connector_id, updates)

    def delete(self, connector_id: str) -> bool:
        return self._store.delete(connector_id)
