from __future__ import annotations

from typing import Any

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


class MemoryRuntimePackMixin:
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


__all__ = ["MemoryRuntimePackMixin"]
