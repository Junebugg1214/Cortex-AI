from __future__ import annotations

from typing import Any

from cortex.service.service_common import _load_identity, _merge_payload
from cortex.versioning.merge import (
    clear_merge_state,
    load_merge_state,
    load_merge_worktree,
    merge_refs,
    resolve_merge_conflict,
    save_merge_state,
)


class MemoryGraphMergeServiceMixin:
    def _pending_merge_payload(self) -> dict[str, Any]:
        state = load_merge_state(self.store_dir)
        if state is None:
            return {
                "status": "ok",
                "pending": False,
                "conflicts": [],
            }
        payload = {
            "status": "ok",
            "pending": True,
            "current_branch": state["current_branch"],
            "other_ref": state["other_ref"],
            "base_version": state.get("base_version"),
            "current_version": state.get("current_version"),
            "other_version": state.get("other_version"),
            "summary": state.get("summary", {}),
            "conflicts": state.get("conflicts", []),
            "updated_at": state.get("updated_at", ""),
        }
        try:
            payload["graph"] = load_merge_worktree(self.store_dir).export_v5()
        except FileNotFoundError:
            pass
        return payload

    def merge_preview(
        self,
        *,
        other_ref: str,
        current_ref: str = "HEAD",
        persist: bool = False,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        self._enforce_namespace(namespace, ref=current_ref)
        self._enforce_namespace(namespace, ref=other_ref)
        result = merge_refs(self.backend.versions, current_ref, other_ref)
        current_branch = self.backend.versions.current_branch() if current_ref == "HEAD" else current_ref
        payload = _merge_payload(
            current_ref=current_ref,
            current_branch=current_branch,
            other_ref=other_ref,
            result=result,
        )
        if persist:
            if current_ref != "HEAD":
                raise ValueError("Persistent merge preview only supports current_ref='HEAD'")
            if result.conflicts:
                state = save_merge_state(
                    self.store_dir,
                    current_branch=current_branch,
                    other_ref=other_ref,
                    result=result,
                )
                payload["pending_merge"] = True
                payload["pending_conflicts"] = len(state["conflicts"])
            else:
                clear_merge_state(self.store_dir)
                payload["pending_merge"] = False
                payload["pending_conflicts"] = 0
        return payload

    def merge_conflicts(self, *, namespace: str | None = None) -> dict[str, Any]:
        self._enforce_namespace(namespace, ref="HEAD")
        return self._pending_merge_payload()

    def merge_resolve(
        self,
        *,
        conflict_id: str,
        choose: str,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        self._enforce_namespace(namespace, ref="HEAD")
        result = resolve_merge_conflict(self.backend.versions, self.store_dir, conflict_id, choose)
        payload = self._pending_merge_payload()
        payload.update(result)
        payload["status"] = "ok"
        return payload

    def merge_commit_resolved(
        self,
        *,
        message: str | None = None,
        actor: str = "manual",
        approve: bool = False,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        state = load_merge_state(self.store_dir)
        if state is None:
            raise ValueError("No pending merge state found")
        self._enforce_namespace(namespace, branch=state["current_branch"])
        conflicts = state.get("conflicts", [])
        if conflicts:
            raise ValueError(f"Cannot commit merge; {len(conflicts)} conflict(s) remain.")

        graph = load_merge_worktree(self.store_dir)
        baseline_version = self.backend.versions.resolve_ref("HEAD")
        baseline_graph = self.backend.versions.checkout(baseline_version) if baseline_version else None
        self._authorize(
            actor=actor,
            action="merge",
            namespace=state["current_branch"],
            approve=approve,
            current_graph=graph,
            baseline_graph=baseline_graph,
        )

        merge_message = message or f"Merge branch '{state['other_ref']}' into {state['current_branch']}"
        merge_parent_ids = (
            [state["other_version"]]
            if state.get("other_version") and state.get("other_version") != state.get("current_version")
            else []
        )
        record = self.backend.versions.commit(
            graph,
            merge_message,
            source="merge",
            identity=_load_identity(self.store_dir),
            parent_id=state.get("current_version"),
            branch=state["current_branch"],
            merge_parent_ids=merge_parent_ids,
        )
        clear_merge_state(self.store_dir)
        return {
            "status": "ok",
            "commit_id": record.version_id,
            "message": merge_message,
            "commit": record.to_dict(),
        }

    def merge_abort(self, *, namespace: str | None = None) -> dict[str, Any]:
        state = load_merge_state(self.store_dir)
        if state is None:
            return {
                "status": "ok",
                "aborted": False,
                "pending": False,
            }
        self._enforce_namespace(namespace, branch=state["current_branch"])
        clear_merge_state(self.store_dir)
        return {
            "status": "ok",
            "aborted": True,
            "pending": False,
            "current_branch": state["current_branch"],
            "other_ref": state["other_ref"],
        }
