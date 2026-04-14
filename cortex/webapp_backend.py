"""
Backend operations for the local Cortex web UI.

Separated from ``cortex.webapp`` so the UI server shell and the backend
service surface can evolve independently.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.request import urlopen

from cortex.cli import _load_graph
from cortex.audience.policy import PolicyEngine
from cortex.audience.templates import BUILTIN_AUDIENCE_TEMPLATES
from cortex.embeddings import get_embedding_provider
from cortex.governance import GOVERNANCE_ACTIONS
from cortex.memory_ops import blame_memory_nodes
from cortex.minds import init_mind, remember_on_mind
from cortex.review import parse_failure_policies, review_graphs
from cortex.schemas.memory_v1 import GovernanceRuleRecord, RemoteRecord
from cortex.service import MemoryService
from cortex.storage import get_storage_backend
from cortex.storage.base import StorageBackend
from cortex.onboarding.wizard import (
    load_wizard_state,
    record_compile,
    record_source,
    reset_wizard,
    skip_wizard,
    start_wizard,
    summarize_wizard_state,
)


class MemoryUIBackend:
    def __init__(
        self,
        store_dir: str | Path,
        context_file: str | Path | None = None,
        backend: StorageBackend | None = None,
    ) -> None:
        self.store_dir = Path(store_dir)
        self.context_file = Path(context_file).resolve() if context_file else None
        self.backend = backend or get_storage_backend(self.store_dir)
        self.service = MemoryService(store_dir=self.store_dir, context_file=self.context_file, backend=self.backend)

    def _backend_name(self) -> str:
        module_name = type(self.backend).__module__
        if module_name.endswith(".sqlite"):
            return "sqlite"
        return "filesystem"

    def _default_context_file(self) -> Path | None:
        if self.context_file:
            return self.context_file
        candidate = Path.cwd() / "context.json"
        return candidate if candidate.exists() else None

    def _resolve_input_file(self, provided: str | None) -> Path:
        if provided:
            path = Path(provided).expanduser().resolve()
        else:
            default = self._default_context_file()
            if default is None:
                raise ValueError("No context file provided and no default context.json found.")
            path = default
        if not path.exists():
            raise ValueError(f"Context file not found: {path}")
        return path

    def _safe_index_status(self, *, ref: str = "HEAD") -> dict[str, Any]:
        resolved_ref = self.backend.versions.resolve_ref(ref)
        if resolved_ref is None:
            provider = get_embedding_provider()
            return {
                "status": "ok",
                "backend": self._backend_name(),
                "persistent": self._backend_name() == "sqlite",
                "supported": self._backend_name() == "sqlite",
                "ref": ref,
                "resolved_ref": None,
                "indexed": False,
                "stale": False,
                "doc_count": 0,
                "updated_at": None,
                "last_indexed_commit": None,
                "last_indexed_at": None,
                "lag_commits": 0,
                "embedding_provider": provider.name,
                "embedding_enabled": provider.enabled,
                "embedding_indexed": False,
                "message": "No commits yet. Create or import memory before indexing.",
            }
        return self.backend.indexing.status(ref=ref)

    def _safe_metrics(self) -> dict[str, Any]:
        metrics = self.service.observability.metrics(
            index_status=self._safe_index_status(ref="HEAD"),
            backend=self._backend_name(),
            current_branch=self.backend.versions.current_branch(),
        )
        metrics["release"] = self.service.release()
        return metrics

    def health(self) -> dict[str, Any]:
        meta = self.meta()
        return {
            "status": "ok",
            "backend": meta["backend"],
            "store_dir": meta["store_dir"],
            "current_branch": meta["current_branch"],
            "head": meta["head"],
            "index": meta["index"],
            "release": meta["release"],
        }

    def meta(self) -> dict[str, Any]:
        versions = self.backend.versions
        current = versions.current_branch()
        default_context = self._default_context_file()
        onboarding = summarize_wizard_state(load_wizard_state(self.store_dir))
        return {
            "status": "ok",
            "store_dir": str(self.store_dir.resolve()),
            "workspace_dir": str(Path.cwd()),
            "context_file": str(default_context) if default_context else "",
            "default_context_available": default_context is not None,
            "backend": self._backend_name(),
            "current_branch": current,
            "head": versions.resolve_ref("HEAD"),
            "branch_count": len(versions.list_branches()),
            "index": self._safe_index_status(ref="HEAD"),
            "log_path": str(self.service.observability.log_path),
            "release": self.service.release(),
            "onboarding": onboarding,
        }

    def onboarding_state(self) -> dict[str, Any]:
        """Return the persisted onboarding state for the current store."""
        state = summarize_wizard_state(load_wizard_state(self.store_dir))
        return {"status": "ok", "onboarding": state}

    def onboarding_start(self, *, mind_id: str, mind_label: str = "") -> dict[str, Any]:
        """Start the onboarding flow for a Mind."""
        state = start_wizard(self.store_dir, mind_id=mind_id, mind_label=mind_label)
        return {"status": "ok", "onboarding": state}

    def onboarding_create_mind(
        self,
        *,
        mind_id: str,
        mind_label: str = "",
        label: str = "",
        owner: str = "",
        kind: str = "person",
        namespace: str | None = None,
    ) -> dict[str, Any]:
        """Create the first Mind during onboarding."""
        payload = init_mind(
            self.store_dir,
            mind_id,
            kind=kind,
            label=label or mind_label,
            owner=owner,
            namespace=namespace,
        )
        state = start_wizard(self.store_dir, mind_id=mind_id, mind_label=label or mind_label or mind_id)
        payload["onboarding"] = state
        return payload

    def onboarding_ingest_source(
        self,
        *,
        mind_id: str,
        source_kind: str,
        source_value: str,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        """Ingest one source for onboarding and advance the wizard."""
        if source_kind == "file":
            path = Path(source_value).expanduser().resolve()
            if not path.exists():
                raise FileNotFoundError(f"Source file not found: {path}")
            statement = path.read_text(encoding="utf-8")
        elif source_kind == "url":
            with urlopen(source_value, timeout=10.0) as response:
                statement = response.read().decode("utf-8", errors="replace")
        elif source_kind == "paste":
            statement = source_value
        else:
            raise ValueError("source_kind must be file, url, or paste")

        remember_payload = remember_on_mind(
            self.store_dir,
            mind_id,
            statement=statement.strip(),
            message="Onboarding source import",
            namespace=namespace,
        )
        state = record_source(self.store_dir, source_kind=source_kind, source_value=source_value)
        return {"status": "ok", "remember": remember_payload, "onboarding": state}

    def onboarding_compile_output(
        self,
        *,
        mind_id: str,
        audience_template: str,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        """Compile the first audience-specific output for onboarding."""
        template = BUILTIN_AUDIENCE_TEMPLATES.get(audience_template)
        if template is None:
            raise ValueError(f"Unknown audience template: {audience_template}")
        engine = PolicyEngine(self.store_dir)
        try:
            engine.add_policy(mind_id, template)
        except Exception:
            pass
        payload = engine.compile(mind_id, audience_template)
        summary = f"Compiled {audience_template} output with {payload['node_count_out']} visible node(s)."
        onboarding = record_compile(
            self.store_dir,
            audience_template=audience_template,
            result_summary=summary,
        )
        payload["onboarding"] = onboarding
        return payload

    def onboarding_skip(self) -> dict[str, Any]:
        """Skip onboarding and persist that choice."""
        return {"status": "ok", "onboarding": skip_wizard(self.store_dir)}

    def onboarding_reset(self) -> dict[str, Any]:
        """Reset onboarding back to its initial state."""
        return {"status": "ok", "onboarding": reset_wizard(self.store_dir)}

    def review(
        self, *, input_file: str | None, against: str, ref: str = "HEAD", fail_on: str = "blocking"
    ) -> dict[str, Any]:
        if not (input_file or "").strip():
            return self.service.review(against=against, ref=ref, fail_on=fail_on)
        versions = self.backend.versions
        against_version = versions.resolve_ref(against)
        if against_version is None:
            raise ValueError(f"Unknown baseline ref: {against}")
        against_graph = versions.checkout(against_version)

        if input_file:
            input_path = self._resolve_input_file(input_file)
            current_graph = _load_graph(input_path)
            current_label = str(input_path)
        else:
            current_version = versions.resolve_ref(ref)
            if current_version is None:
                raise ValueError(f"Unknown current ref: {ref}")
            current_graph = versions.checkout(current_version)
            current_label = current_version

        fail_policies = parse_failure_policies(fail_on)
        review = review_graphs(current_graph, against_graph, current_label=current_label, against_label=against_version)
        result = review.to_dict()
        should_fail, failure_counts = review.should_fail(fail_policies)
        result["status"] = "fail" if should_fail else "pass"
        result["fail_on"] = fail_policies
        result["failure_counts"] = failure_counts
        return result

    def blame(
        self,
        *,
        input_file: str | None,
        label: str = "",
        node_id: str = "",
        ref: str = "HEAD",
        source: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        if not (input_file or "").strip():
            return self.service.blame(label=label, node_id=node_id, ref=ref, source=source, limit=limit)
        input_path = self._resolve_input_file(input_file)
        graph = _load_graph(input_path)
        return blame_memory_nodes(
            graph,
            label=label or None,
            node_id=node_id or None,
            store=self.backend.versions,
            ledger=self.backend.claims,
            ref=ref,
            source=source,
            version_limit=limit,
        )

    def history(
        self,
        *,
        input_file: str | None,
        label: str = "",
        node_id: str = "",
        ref: str = "HEAD",
        source: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        if not (input_file or "").strip():
            return self.service.history(label=label, node_id=node_id, ref=ref, source=source, limit=limit)
        return {
            "status": "ok",
            "ref": ref,
            "source": source,
            "nodes": self.blame(
                input_file=input_file,
                label=label,
                node_id=node_id,
                ref=ref,
                source=source,
                limit=limit,
            )["nodes"],
        }

    def list_governance_rules(self) -> dict[str, Any]:
        return {"rules": [rule.to_dict() for rule in self.backend.governance.list_rules()]}

    def save_governance_rule(self, *, effect: str, payload: dict[str, Any]) -> dict[str, Any]:
        actions = list(payload.get("actions") or payload.get("action") or [])
        namespaces = list(payload.get("namespaces") or payload.get("namespace") or [])
        invalid = [item for item in actions if item != "*" and item not in GOVERNANCE_ACTIONS]
        if invalid:
            raise ValueError(f"Unknown governance action(s): {', '.join(sorted(invalid))}")
        rule = GovernanceRuleRecord(
            tenant_id=self.backend.tenant_id,
            name=payload["name"],
            effect=effect,
            actor_pattern=payload.get("actor_pattern", "*"),
            actions=actions or ["*"],
            namespaces=namespaces or ["*"],
            require_approval=bool(payload.get("require_approval", False)),
            approval_below_confidence=payload.get("approval_below_confidence"),
            approval_tags=list(payload.get("approval_tags", [])),
            approval_change_types=list(payload.get("approval_change_types", [])),
            description=payload.get("description", ""),
        )
        self.backend.governance.upsert_rule(rule)
        return {"status": "ok", "rule": rule.to_dict()}

    def delete_governance_rule(self, name: str) -> dict[str, Any]:
        removed = self.backend.governance.remove_rule(name)
        return {"status": "ok" if removed else "missing", "name": name}

    def check_governance(
        self,
        *,
        actor: str,
        action: str,
        namespace: str,
        input_file: str | None = None,
        against: str | None = None,
    ) -> dict[str, Any]:
        current_graph = _load_graph(self._resolve_input_file(input_file)) if input_file else None
        baseline_graph = None
        if against:
            version_id = self.backend.versions.resolve_ref(against)
            if version_id is None:
                raise ValueError(f"Unknown baseline ref: {against}")
            baseline_graph = self.backend.versions.checkout(version_id)
        return self.backend.governance.authorize(
            actor,
            action,
            namespace,
            current_graph=current_graph,
            baseline_graph=baseline_graph,
        ).to_dict()

    def metrics(self) -> dict[str, Any]:
        return self._safe_metrics()

    def portability_scan(self, *, project_dir: str = "", metadata_only: bool = False) -> dict[str, Any]:
        return self.service.portability_scan(project_dir=project_dir, metadata_only=metadata_only)

    def portability_status(self, *, project_dir: str = "") -> dict[str, Any]:
        return self.service.portability_status(project_dir=project_dir)

    def portability_audit(self, *, project_dir: str = "") -> dict[str, Any]:
        return self.service.portability_audit(project_dir=project_dir)

    def portability_context(
        self,
        *,
        target: str,
        project_dir: str = "",
        smart: bool | None = True,
        max_chars: int = 900,
    ) -> dict[str, Any]:
        return self.service.portability_context(
            target=target,
            project_dir=project_dir,
            smart=smart,
            max_chars=max_chars,
        )

    def portability_sync(
        self,
        *,
        project_dir: str = "",
        targets: list[str] | None = None,
        smart: bool = True,
        policy_name: str = "full",
        max_chars: int = 1500,
    ) -> dict[str, Any]:
        from cortex.minds import resolve_default_mind, sync_mind_compatibility_targets
        from cortex.portable_runtime import (
            ALL_PORTABLE_TARGETS,
            canonical_target_name,
            default_output_dir,
            load_canonical_graph,
            load_portability_state,
            sync_targets,
        )

        project_path = Path(project_dir).resolve() if project_dir else Path.cwd()
        default_mind = resolve_default_mind(self.store_dir)
        if default_mind:
            payload = sync_mind_compatibility_targets(
                self.store_dir,
                default_mind,
                targets=[canonical_target_name(target) for target in (targets or ALL_PORTABLE_TARGETS)],
                project_dir=project_path,
                smart=smart,
                policy_name=policy_name,
                max_chars=max_chars,
            )
            payload["status"] = "ok"
            return payload

        state = load_portability_state(self.store_dir)
        canonical_graph, graph_path = load_canonical_graph(self.store_dir, state)
        if not canonical_graph.nodes:
            return {
                "status": "empty",
                "message": "No canonical context exists yet. Run detected adoption or remember something first.",
                "graph_path": str(graph_path),
                "fact_count": 0,
                "targets": [],
            }
        output_dir = Path(state.output_dir) if state.output_dir else default_output_dir(self.store_dir)
        payload = sync_targets(
            canonical_graph,
            targets=[canonical_target_name(target) for target in (targets or ALL_PORTABLE_TARGETS)],
            store_dir=self.store_dir,
            project_dir=str(project_path),
            output_dir=output_dir,
            graph_path=graph_path,
            policy_name=policy_name,
            smart=smart,
            max_chars=max_chars,
            state=state,
        )
        payload["status"] = "ok"
        payload["graph_path"] = str(graph_path)
        payload["fact_count"] = len(canonical_graph.nodes)
        return payload

    def portability_remember(
        self,
        *,
        statement: str,
        project_dir: str = "",
        targets: list[str] | None = None,
        smart: bool = True,
        policy_name: str = "full",
        max_chars: int = 1500,
    ) -> dict[str, Any]:
        from cortex.minds import remember_and_sync_default_mind, resolve_default_mind
        from cortex.portable_runtime import ALL_PORTABLE_TARGETS, remember_and_sync

        if not statement.strip():
            raise ValueError("statement is required")
        project_path = Path(project_dir).resolve() if project_dir else Path.cwd()
        default_mind = resolve_default_mind(self.store_dir)
        if default_mind:
            payload = remember_and_sync_default_mind(
                self.store_dir,
                default_mind,
                statement=statement.strip(),
                project_dir=project_path,
                targets=list(targets or ALL_PORTABLE_TARGETS),
                smart=smart,
                policy_name=policy_name,
                max_chars=max_chars,
            )
        else:
            payload = remember_and_sync(
                statement.strip(),
                store_dir=self.store_dir,
                project_dir=project_path,
                targets=targets,
                smart=smart,
                policy_name=policy_name,
                max_chars=max_chars,
            )
        payload["status"] = "ok"
        return payload

    def mind_list(self) -> dict[str, Any]:
        return self.service.mind_list()

    def mind_status(self, *, name: str) -> dict[str, Any]:
        return self.service.mind_status(name=name)

    def mind_mounts(self, *, name: str) -> dict[str, Any]:
        return self.service.mind_mounts(name=name)

    def mind_compose(
        self,
        *,
        name: str,
        target: str,
        task: str = "",
        project_dir: str = "",
        smart: bool = True,
        policy_name: str = "",
        max_chars: int = 1200,
        activation_target: str = "",
    ) -> dict[str, Any]:
        return self.service.mind_compose(
            name=name,
            target=target,
            task=task,
            project_dir=project_dir,
            smart=smart,
            policy=policy_name,
            max_chars=max_chars,
            activation_target=activation_target,
        )

    def pack_list(self) -> dict[str, Any]:
        return self.service.pack_list()

    def pack_status(self, *, name: str) -> dict[str, Any]:
        return self.service.pack_status(name=name)

    def pack_sources(self, *, name: str) -> dict[str, Any]:
        return self.service.pack_sources(name=name)

    def pack_concepts(self, *, name: str) -> dict[str, Any]:
        return self.service.pack_concepts(name=name)

    def pack_claims(self, *, name: str) -> dict[str, Any]:
        return self.service.pack_claims(name=name)

    def pack_unknowns(self, *, name: str) -> dict[str, Any]:
        return self.service.pack_unknowns(name=name)

    def pack_artifacts(self, *, name: str) -> dict[str, Any]:
        return self.service.pack_artifacts(name=name)

    def pack_lint_report(self, *, name: str) -> dict[str, Any]:
        return self.service.pack_lint_report(name=name)

    def index_status(self, *, ref: str = "HEAD") -> dict[str, Any]:
        return self._safe_index_status(ref=ref)

    def index_rebuild(self, *, ref: str = "HEAD", all_refs: bool = False) -> dict[str, Any]:
        if all_refs:
            branches = [branch for branch in self.backend.versions.list_branches() if branch.head]
            if not branches:
                status = self._safe_index_status(ref=ref)
                return {
                    "status": "ok",
                    "backend": self._backend_name(),
                    "persistent": status.get("persistent", False),
                    "supported": status.get("supported", False),
                    "ref": ref,
                    "all_refs": True,
                    "rebuilt": 0,
                    "indexed_versions": [],
                    "doc_count": 0,
                    "updated_at": None,
                    "last_indexed_commit": None,
                    "embedding_provider": status.get("embedding_provider", "disabled"),
                    "embedding_enabled": status.get("embedding_enabled", False),
                    "message": "No committed refs are available to rebuild.",
                }
        elif self.backend.versions.resolve_ref(ref) is None:
            status = self._safe_index_status(ref=ref)
            return {
                "status": "ok",
                "backend": self._backend_name(),
                "persistent": status.get("persistent", False),
                "supported": status.get("supported", False),
                "ref": ref,
                "all_refs": False,
                "rebuilt": 0,
                "indexed_versions": [],
                "doc_count": 0,
                "updated_at": None,
                "last_indexed_commit": None,
                "embedding_provider": status.get("embedding_provider", "disabled"),
                "embedding_enabled": status.get("embedding_enabled", False),
                "message": "Unknown ref or empty store. Commit memory before rebuilding indexes.",
            }
        return self.backend.indexing.rebuild(ref=ref, all_refs=all_refs)

    def prune_status(self, *, retention_days: int = 7) -> dict[str, Any]:
        return self.backend.maintenance.status(retention_days=retention_days)

    def prune(self, *, dry_run: bool = True, retention_days: int = 7) -> dict[str, Any]:
        return self.backend.maintenance.prune(dry_run=dry_run, retention_days=retention_days)

    def prune_audit(self, *, limit: int = 20) -> dict[str, Any]:
        return {"status": "ok", "entries": self.backend.maintenance.audit_log(limit=limit)}

    def list_remotes(self) -> dict[str, Any]:
        return {
            "remotes": [
                remote.to_dict() | {"store_path": remote.resolved_store_path}
                for remote in self.backend.remotes.list_remotes()
            ]
        }

    def add_remote(self, *, name: str, path: str, default_branch: str = "main") -> dict[str, Any]:
        remote = RemoteRecord(
            tenant_id=self.backend.tenant_id,
            name=name,
            path=path,
            default_branch=default_branch,
        )
        self.backend.remotes.add_remote(remote)
        stored = next(item for item in self.backend.remotes.list_remotes() if item.name == name)
        return {"status": "ok", "remote": stored.to_dict() | {"store_path": stored.resolved_store_path}}

    def remove_remote(self, name: str) -> dict[str, Any]:
        removed = self.backend.remotes.remove_remote(name)
        return {"status": "ok" if removed else "missing", "name": name}

    def remote_push(
        self, *, name: str, branch: str = "HEAD", to_branch: str | None = None, force: bool = False
    ) -> dict[str, Any]:
        return self.backend.remotes.push_remote(name, branch=branch, target_branch=to_branch, force=force)

    def remote_pull(
        self,
        *,
        name: str,
        branch: str | None = None,
        into_branch: str | None = None,
        switch: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        if branch is None:
            matching = next((item for item in self.backend.remotes.list_remotes() if item.name == name), None)
            if matching is None:
                raise ValueError(f"Unknown remote: {name}")
            branch = matching.default_branch
        return self.backend.remotes.pull_remote(
            name,
            branch=branch,
            into_branch=into_branch,
            switch=switch,
            force=force,
        )

    def remote_fork(
        self, *, name: str, branch_name: str, remote_branch: str | None = None, switch: bool = False
    ) -> dict[str, Any]:
        if remote_branch is None:
            matching = next((item for item in self.backend.remotes.list_remotes() if item.name == name), None)
            if matching is None:
                raise ValueError(f"Unknown remote: {name}")
            remote_branch = matching.default_branch
        return self.backend.remotes.fork_remote(
            name,
            remote_branch=remote_branch,
            local_branch=branch_name,
            switch=switch,
        )


__all__ = ["MemoryUIBackend"]
