from __future__ import annotations

from pathlib import Path
from typing import Any

from cortex.graph.minds import (
    compose_mind,
    ingest_detected_sources_into_mind,
    list_mind_mounts,
    list_minds,
    mind_status,
    mount_mind,
    remember_on_mind,
)


class MemoryRuntimeMindMixin:
    def mind_list(self, *, namespace: str | None = None) -> dict[str, Any]:
        payload = list_minds(self.store_dir, namespace=namespace)
        payload["release"] = self.release()
        return payload

    def mind_status(self, *, name: str, namespace: str | None = None) -> dict[str, Any]:
        payload = mind_status(self.store_dir, name, namespace=namespace)
        payload["release"] = self.release()
        return payload

    def mind_ingest(
        self,
        *,
        name: str,
        targets: list[str],
        project_dir: str = "",
        search_roots: list[str] | None = None,
        include_config_metadata: bool = False,
        include_unmanaged_text: bool = False,
        redact_detected: bool = True,
        redact_patterns: dict[str, Any] | None = None,
        message: str = "",
        namespace: str | None = None,
    ) -> dict[str, Any]:
        from cortex.extraction.extract_memory import PIIRedactor

        redactor = PIIRedactor(redact_patterns) if redact_detected else None
        payload = ingest_detected_sources_into_mind(
            self.store_dir,
            name,
            targets=targets,
            project_dir=Path(project_dir).resolve() if project_dir else Path.cwd(),
            extra_roots=[Path(root).resolve() for root in (search_roots or [])],
            include_config_metadata=include_config_metadata,
            include_unmanaged_text=include_unmanaged_text,
            redactor=redactor,
            message=message,
            namespace=namespace,
        )
        payload["release"] = self.release()
        return payload

    def mind_compose(
        self,
        *,
        name: str,
        target: str,
        task: str = "",
        project_dir: str = "",
        smart: bool = True,
        policy: str = "",
        max_chars: int = 1500,
        activation_target: str = "",
        namespace: str | None = None,
    ) -> dict[str, Any]:
        payload = compose_mind(
            self.store_dir,
            name,
            target=target,
            task=task,
            project_dir=project_dir,
            smart=smart,
            policy_name=policy,
            max_chars=max_chars,
            activation_target=activation_target,
            namespace=namespace,
        )
        payload["release"] = self.release()
        return payload

    def mind_remember(
        self,
        *,
        name: str,
        statement: str,
        message: str = "",
        namespace: str | None = None,
    ) -> dict[str, Any]:
        payload = remember_on_mind(
            self.store_dir,
            name,
            statement=statement,
            message=message,
            namespace=namespace,
        )
        payload["release"] = self.release()
        return payload

    def mind_mounts(self, *, name: str, namespace: str | None = None) -> dict[str, Any]:
        payload = list_mind_mounts(self.store_dir, name, namespace=namespace)
        payload["release"] = self.release()
        return payload

    def mind_mount(
        self,
        *,
        name: str,
        targets: list[str],
        task: str = "",
        project_dir: str = "",
        smart: bool = True,
        policy: str = "",
        max_chars: int = 1500,
        openclaw_store_dir: str = "",
        namespace: str | None = None,
    ) -> dict[str, Any]:
        payload = mount_mind(
            self.store_dir,
            name,
            targets=targets,
            task=task,
            project_dir=project_dir,
            smart=smart,
            policy_name=policy,
            max_chars=max_chars,
            openclaw_store_dir=openclaw_store_dir,
            namespace=namespace,
        )
        payload["release"] = self.release()
        return payload


__all__ = ["MemoryRuntimeMindMixin"]
