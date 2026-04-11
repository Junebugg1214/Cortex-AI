from __future__ import annotations

from pathlib import Path
from typing import Any

from cortex.embeddings import get_embedding_provider
from cortex.minds import (
    compose_mind,
    ingest_detected_sources_into_mind,
    list_mind_mounts,
    list_minds,
    mind_status,
    mount_mind,
    remember_on_mind,
)
from cortex.openapi import build_openapi_spec
from cortex.packs import (
    ask_pack,
    compile_pack,
    export_pack_bundle,
    import_pack_bundle,
    lint_pack,
    list_packs,
    mount_pack,
    pack_artifacts,
    pack_claims,
    pack_concepts,
    pack_lint_report,
    pack_mounts,
    pack_sources,
    pack_status,
    pack_unknowns,
    query_pack,
    render_pack_context,
)
from cortex.portable_runtime import (
    audit_portability,
    render_portability_context,
    scan_portability,
    status_portability,
)
from cortex.release import build_release_metadata
from cortex.storage.base import StorageBackend


def _backend_name(backend: StorageBackend) -> str:
    module_name = type(backend).__module__
    if module_name.endswith(".sqlite"):
        return "sqlite"
    return "filesystem"


def _safe_head_ref(service: Any) -> str:
    try:
        return service.backend.versions.resolve_ref("HEAD")
    except (FileNotFoundError, ValueError):
        return ""


def _safe_index_status(service: Any) -> dict[str, Any]:
    try:
        return service.backend.indexing.status(ref="HEAD")
    except (FileNotFoundError, ValueError):
        provider = get_embedding_provider()
        return {
            "status": "missing",
            "backend": _backend_name(service.backend),
            "persistent": _backend_name(service.backend) == "sqlite",
            "supported": provider.enabled,
            "ref": "HEAD",
            "resolved_ref": "",
            "last_indexed_commit": None,
            "doc_count": 0,
            "stale": False,
            "updated_at": None,
            "lag_commits": 0,
            "embedding_provider": provider.name,
            "embedding_enabled": provider.enabled,
        }


class MemoryRuntimeServiceMixin:
    def health(self) -> dict[str, Any]:
        index_status = _safe_index_status(self)
        return {
            "status": "ok",
            "backend": _backend_name(self.backend),
            "store_dir": str(self.store_dir.resolve()),
            "current_branch": self.backend.versions.current_branch(),
            "head": _safe_head_ref(self),
            "index": index_status,
            "release": self.release(),
        }

    def openapi(self, *, server_url: str | None = None) -> dict[str, Any]:
        return build_openapi_spec(server_url=server_url)

    def release(self) -> dict[str, Any]:
        return build_release_metadata(self.openapi())

    def meta(self) -> dict[str, Any]:
        provider = get_embedding_provider()
        return {
            "status": "ok",
            "store_dir": str(self.store_dir.resolve()),
            "context_file": str(self.context_file) if self.context_file else "",
            "backend": _backend_name(self.backend),
            "current_branch": self.backend.versions.current_branch(),
            "head": _safe_head_ref(self),
            "embedding_provider": provider.name,
            "embedding_enabled": provider.enabled,
            "log_path": str(self.observability.log_path),
            "index": _safe_index_status(self),
            "release": self.release(),
        }

    def portability_context(
        self,
        *,
        target: str,
        project_dir: str = "",
        smart: bool | None = None,
        policy: str | None = None,
        max_chars: int = 1500,
    ) -> dict[str, Any]:
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
    ) -> dict[str, Any]:
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
    ) -> dict[str, Any]:
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
    ) -> dict[str, Any]:
        project_path = Path(project_dir).resolve() if project_dir else Path.cwd()
        payload = audit_portability(
            store_dir=self.store_dir,
            project_dir=project_path,
        )
        payload["release"] = self.release()
        return payload

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
        from cortex.extract_memory import PIIRedactor

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

    def pack_list(self, *, namespace: str | None = None) -> dict[str, Any]:
        payload = list_packs(self.store_dir, namespace=namespace)
        payload["release"] = self.release()
        return payload

    def pack_status(self, *, name: str, namespace: str | None = None) -> dict[str, Any]:
        payload = pack_status(self.store_dir, name, namespace=namespace)
        payload["release"] = self.release()
        return payload

    def pack_sources(self, *, name: str, namespace: str | None = None) -> dict[str, Any]:
        payload = pack_sources(self.store_dir, name, namespace=namespace)
        payload["release"] = self.release()
        return payload

    def pack_concepts(self, *, name: str, namespace: str | None = None) -> dict[str, Any]:
        payload = pack_concepts(self.store_dir, name, namespace=namespace)
        payload["release"] = self.release()
        return payload

    def pack_claims(self, *, name: str, namespace: str | None = None) -> dict[str, Any]:
        payload = pack_claims(self.store_dir, name, namespace=namespace)
        payload["release"] = self.release()
        return payload

    def pack_unknowns(self, *, name: str, namespace: str | None = None) -> dict[str, Any]:
        payload = pack_unknowns(self.store_dir, name, namespace=namespace)
        payload["release"] = self.release()
        return payload

    def pack_artifacts(self, *, name: str, namespace: str | None = None) -> dict[str, Any]:
        payload = pack_artifacts(self.store_dir, name, namespace=namespace)
        payload["release"] = self.release()
        return payload

    def pack_lint_report(self, *, name: str, namespace: str | None = None) -> dict[str, Any]:
        payload = pack_lint_report(self.store_dir, name, namespace=namespace)
        payload["release"] = self.release()
        return payload

    def pack_mounts(self, *, name: str, namespace: str | None = None) -> dict[str, Any]:
        payload = pack_mounts(self.store_dir, name, namespace=namespace)
        payload["release"] = self.release()
        return payload

    def pack_compile(
        self,
        *,
        name: str,
        incremental: bool = True,
        suggest_questions: bool = True,
        max_summary_chars: int = 1200,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        payload = compile_pack(
            self.store_dir,
            name,
            incremental=incremental,
            suggest_questions=suggest_questions,
            max_summary_chars=max_summary_chars,
            namespace=namespace,
        )
        payload["release"] = self.release()
        return payload

    def pack_query(
        self,
        *,
        name: str,
        query: str,
        limit: int = 8,
        mode: str = "hybrid",
        namespace: str | None = None,
    ) -> dict[str, Any]:
        payload = query_pack(
            self.store_dir,
            name,
            query,
            limit=limit,
            mode=mode,
            namespace=namespace,
        )
        payload["release"] = self.release()
        return payload

    def pack_ask(
        self,
        *,
        name: str,
        question: str,
        output: str = "note",
        limit: int = 8,
        write_back: bool = True,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        payload = ask_pack(
            self.store_dir,
            name,
            question,
            output=output,
            limit=limit,
            write_back=write_back,
            namespace=namespace,
        )
        payload["release"] = self.release()
        return payload

    def pack_lint(
        self,
        *,
        name: str,
        stale_days: int = 30,
        duplicate_threshold: float = 0.88,
        weak_claim_confidence: float = 0.65,
        thin_article_chars: int = 220,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        payload = lint_pack(
            self.store_dir,
            name,
            stale_days=stale_days,
            duplicate_threshold=duplicate_threshold,
            weak_claim_confidence=weak_claim_confidence,
            thin_article_chars=thin_article_chars,
            namespace=namespace,
        )
        payload["release"] = self.release()
        return payload

    def pack_export(
        self,
        *,
        name: str,
        output: str,
        verify: bool = True,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        payload = export_pack_bundle(
            self.store_dir,
            name,
            output,
            verify=verify,
            namespace=namespace,
        )
        payload["release"] = self.release()
        return payload

    def pack_import(
        self,
        *,
        archive: str,
        as_name: str = "",
        namespace: str | None = None,
    ) -> dict[str, Any]:
        payload = import_pack_bundle(
            archive,
            self.store_dir,
            as_name=as_name,
            namespace=namespace,
        )
        payload["release"] = self.release()
        return payload

    def pack_mount(
        self,
        *,
        name: str,
        targets: list[str],
        project_dir: str = "",
        smart: bool = True,
        policy: str = "technical",
        max_chars: int = 1500,
        openclaw_store_dir: str = "",
        namespace: str | None = None,
    ) -> dict[str, Any]:
        payload = mount_pack(
            self.store_dir,
            name,
            targets=targets,
            project_dir=project_dir,
            smart=smart,
            policy_name=policy,
            max_chars=max_chars,
            openclaw_store_dir=openclaw_store_dir,
            namespace=namespace,
        )
        payload["release"] = self.release()
        return payload

    def pack_context(
        self,
        *,
        name: str,
        target: str,
        project_dir: str = "",
        smart: bool = True,
        policy: str = "technical",
        max_chars: int = 1500,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        payload = render_pack_context(
            self.store_dir,
            name,
            target=target,
            project_dir=project_dir,
            smart=smart,
            policy_name=policy,
            max_chars=max_chars,
            namespace=namespace,
        )
        payload["release"] = self.release()
        return payload

    def channel_prepare_turn(
        self,
        *,
        message: dict[str, Any],
        target: str | None = None,
        smart: bool = True,
        max_chars: int = 1500,
        project_dir: str = "",
    ) -> dict[str, Any]:
        from cortex.channel_runtime import (
            ChannelContextBridge,
            channel_message_from_dict,
            channel_turn_to_dict,
        )

        channel_message = channel_message_from_dict(message)
        if project_dir and not channel_message.project_dir:
            channel_message.project_dir = str(Path(project_dir).resolve())
        bridge = ChannelContextBridge(self, default_project_dir=Path(project_dir).resolve() if project_dir else None)
        turn = bridge.prepare_turn(
            channel_message,
            target=target,
            smart=smart,
            max_chars=max_chars,
        )
        payload = {"status": "ok", "turn": channel_turn_to_dict(turn)}
        payload["release"] = self.release()
        return payload

    def channel_seed_turn_memory(
        self,
        *,
        turn: dict[str, Any],
        ref: str = "HEAD",
        source: str = "channel.runtime",
        approve: bool = False,
    ) -> dict[str, Any]:
        from cortex.channel_runtime import ChannelContextBridge, channel_turn_from_dict

        bridge = ChannelContextBridge(self)
        payload = bridge.seed_turn_memory(
            channel_turn_from_dict(turn),
            ref=ref,
            source=source,
            approve=approve,
        )
        payload["release"] = self.release()
        return payload

    def metrics(self, *, namespace: str | None = None) -> dict[str, Any]:
        self._enforce_namespace(namespace, ref="HEAD")
        metrics = self.observability.metrics(
            index_status=_safe_index_status(self),
            backend=_backend_name(self.backend),
            current_branch=self.backend.versions.current_branch(),
        )
        metrics["release"] = self.release()
        return metrics

    def prune_status(self, *, retention_days: int = 7) -> dict[str, Any]:
        return self.backend.maintenance.status(retention_days=retention_days)

    def prune(self, *, dry_run: bool = True, retention_days: int = 7) -> dict[str, Any]:
        return self.backend.maintenance.prune(dry_run=dry_run, retention_days=retention_days)

    def prune_audit(self, *, limit: int = 50) -> dict[str, Any]:
        return {"status": "ok", "entries": self.backend.maintenance.audit_log(limit=limit)}


__all__ = ["MemoryRuntimeServiceMixin", "_backend_name", "_safe_head_ref", "_safe_index_status"]
