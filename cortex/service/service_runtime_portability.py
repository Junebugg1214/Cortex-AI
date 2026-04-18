from __future__ import annotations

from pathlib import Path

from cortex.portable_runtime import (
    audit_portability,
    render_portability_context,
    scan_portability,
    status_portability,
)


class MemoryRuntimePortabilityMixin:
    def portability_context(
        self,
        *,
        target: str,
        project_dir: str = "",
        smart: bool | None = None,
        policy: str | None = None,
        max_chars: int = 1500,
    ) -> dict[str, object]:
        project_path = Path(project_dir).resolve() if project_dir else None
        payload = render_portability_context(
            store_dir=self.store_dir,
            target=target,
            project_dir=project_path,
            smart=smart,
            policy_name=policy,
            max_chars=max_chars,
        )
        payload["release"] = self.release()
        return payload

    def portability_scan(
        self,
        *,
        project_dir: str = "",
        search_roots: list[str] | None = None,
        metadata_only: bool = False,
    ) -> dict[str, object]:
        project_path = Path(project_dir).resolve() if project_dir else Path.cwd()
        payload = scan_portability(
            store_dir=self.store_dir,
            project_dir=project_path,
            extra_roots=[Path(root).resolve() for root in (search_roots or [])],
            metadata_only=metadata_only,
        )
        payload["release"] = self.release()
        return payload

    def portability_status(
        self,
        *,
        project_dir: str = "",
    ) -> dict[str, object]:
        project_path = Path(project_dir).resolve() if project_dir else Path.cwd()
        payload = status_portability(
            store_dir=self.store_dir,
            project_dir=project_path,
        )
        payload["release"] = self.release()
        return payload

    def portability_audit(
        self,
        *,
        project_dir: str = "",
    ) -> dict[str, object]:
        project_path = Path(project_dir).resolve() if project_dir else Path.cwd()
        payload = audit_portability(
            store_dir=self.store_dir,
            project_dir=project_path,
        )
        payload["release"] = self.release()
        return payload


__all__ = ["MemoryRuntimePortabilityMixin"]
