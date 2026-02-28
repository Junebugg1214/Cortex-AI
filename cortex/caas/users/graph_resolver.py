"""
Per-user graph resolution and storage.

Manages isolated knowledge graphs for each user, with support for:
- Loading/saving user-specific graphs
- Graph versioning
- Storage quota enforcement
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from cortex.graph import CortexGraph
    from cortex.caas.users.models import User


class UserGraphResolver:
    """
    Resolves and manages per-user knowledge graphs.

    Storage structure:
        .cortex/
        ├── identity.json       # Server admin identity
        ├── graph.json          # Admin's graph (legacy single-user)
        └── users/
            ├── <user_id_1>/
            │   ├── graph.json
            │   └── versions/
            │       ├── v001.json
            │       └── v002.json
            └── <user_id_2>/
                └── ...
    """

    def __init__(
        self,
        base_path: str | Path,
        max_versions: int = 10,
    ) -> None:
        self._base_path = Path(base_path)
        self._users_path = self._base_path / "users"
        self._max_versions = max_versions
        self._lock = threading.Lock()

        # Ensure users directory exists
        self._users_path.mkdir(parents=True, exist_ok=True)

    def _user_path(self, user_id: str) -> Path:
        """Get the base path for a user's data."""
        # Sanitize user_id to prevent path traversal
        safe_id = "".join(c for c in user_id if c.isalnum() or c in "-_")
        if not safe_id:
            raise ValueError("Invalid user_id")
        return self._users_path / safe_id

    def _graph_path(self, user_id: str) -> Path:
        """Get the path to a user's graph file."""
        return self._user_path(user_id) / "graph.json"

    def _versions_path(self, user_id: str) -> Path:
        """Get the path to a user's versions directory."""
        return self._user_path(user_id) / "versions"

    # ── Graph operations ──────────────────────────────────────────

    def get_user_graph(self, user_id: str) -> Optional[dict]:
        """
        Load a user's graph data from storage.

        Returns:
            Graph data dict (v5 format) or None if not found
        """
        graph_file = self._graph_path(user_id)
        if not graph_file.exists():
            return None

        try:
            with open(graph_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

    def save_user_graph(
        self,
        user_id: str,
        graph_data: dict,
        create_version: bool = True,
    ) -> int:
        """
        Save a user's graph data to storage.

        Args:
            user_id: The user's ID
            graph_data: Graph data in v5 format
            create_version: Whether to create a version backup

        Returns:
            Size of saved graph in bytes
        """
        user_path = self._user_path(user_id)
        graph_file = self._graph_path(user_id)

        with self._lock:
            # Ensure user directory exists
            user_path.mkdir(parents=True, exist_ok=True)

            # Create version backup if requested and graph exists
            if create_version and graph_file.exists():
                self._create_version(user_id)

            # Write graph data
            graph_json = json.dumps(graph_data, indent=2, ensure_ascii=False)
            with open(graph_file, "w", encoding="utf-8") as f:
                f.write(graph_json)

            return len(graph_json.encode("utf-8"))

    def delete_user_graph(self, user_id: str) -> bool:
        """
        Delete a user's graph and all versions.

        Returns:
            True if deleted, False if not found
        """
        user_path = self._user_path(user_id)
        if not user_path.exists():
            return False

        with self._lock:
            shutil.rmtree(user_path)
            return True

    def graph_exists(self, user_id: str) -> bool:
        """Check if a user has a graph."""
        return self._graph_path(user_id).exists()

    def get_graph_size(self, user_id: str) -> int:
        """Get the size of a user's graph in bytes."""
        graph_file = self._graph_path(user_id)
        if not graph_file.exists():
            return 0
        return graph_file.stat().st_size

    def get_total_storage(self, user_id: str) -> int:
        """Get total storage used by a user (graph + versions)."""
        user_path = self._user_path(user_id)
        if not user_path.exists():
            return 0

        total = 0
        for root, dirs, files in os.walk(user_path):
            for f in files:
                total += Path(root, f).stat().st_size
        return total

    # ── Version operations ────────────────────────────────────────

    def _create_version(self, user_id: str) -> Optional[str]:
        """
        Create a version backup of the current graph.

        Returns:
            Version name or None if no graph to backup
        """
        graph_file = self._graph_path(user_id)
        if not graph_file.exists():
            return None

        versions_dir = self._versions_path(user_id)
        versions_dir.mkdir(parents=True, exist_ok=True)

        # Generate version name
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        version_name = f"v_{timestamp}.json"
        version_file = versions_dir / version_name

        # Copy current graph to version
        shutil.copy2(graph_file, version_file)

        # Cleanup old versions
        self._cleanup_versions(user_id)

        return version_name

    def _cleanup_versions(self, user_id: str) -> None:
        """Remove old versions beyond max_versions limit."""
        versions_dir = self._versions_path(user_id)
        if not versions_dir.exists():
            return

        versions = sorted(versions_dir.glob("v_*.json"), reverse=True)
        for old_version in versions[self._max_versions:]:
            old_version.unlink()

    def list_versions(self, user_id: str) -> list[dict]:
        """
        List all versions for a user's graph.

        Returns:
            List of version info dicts with name, timestamp, size
        """
        versions_dir = self._versions_path(user_id)
        if not versions_dir.exists():
            return []

        versions = []
        for version_file in sorted(versions_dir.glob("v_*.json"), reverse=True):
            stat = version_file.stat()
            versions.append({
                "name": version_file.name,
                "size": stat.st_size,
                "created_at": datetime.fromtimestamp(
                    stat.st_mtime, timezone.utc
                ).isoformat(),
            })
        return versions

    def get_version(self, user_id: str, version_name: str) -> Optional[dict]:
        """
        Load a specific version of a user's graph.

        Returns:
            Graph data dict or None if not found
        """
        # Sanitize version name
        safe_name = "".join(c for c in version_name if c.isalnum() or c in "-_.")
        if not safe_name.startswith("v_") or not safe_name.endswith(".json"):
            return None

        version_file = self._versions_path(user_id) / safe_name
        if not version_file.exists():
            return None

        try:
            with open(version_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

    def restore_version(self, user_id: str, version_name: str) -> bool:
        """
        Restore a user's graph from a specific version.

        Creates a backup of the current graph before restoring.

        Returns:
            True if restored, False if version not found
        """
        version_data = self.get_version(user_id, version_name)
        if version_data is None:
            return False

        with self._lock:
            # Save current as a new version before restoring
            self._create_version(user_id)

            # Restore the old version as current
            graph_file = self._graph_path(user_id)
            with open(graph_file, "w", encoding="utf-8") as f:
                json.dump(version_data, f, indent=2, ensure_ascii=False)

            return True

    # ── Admin graph (legacy) ──────────────────────────────────────

    def get_admin_graph(self) -> Optional[dict]:
        """Load the admin's graph (legacy single-user mode)."""
        admin_graph = self._base_path / "graph.json"
        if not admin_graph.exists():
            return None

        try:
            with open(admin_graph, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

    def save_admin_graph(self, graph_data: dict) -> int:
        """Save the admin's graph (legacy single-user mode)."""
        admin_graph = self._base_path / "graph.json"

        with self._lock:
            graph_json = json.dumps(graph_data, indent=2, ensure_ascii=False)
            with open(admin_graph, "w", encoding="utf-8") as f:
                f.write(graph_json)
            return len(graph_json.encode("utf-8"))

    # ── Statistics ────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Get storage statistics across all users."""
        total_users = 0
        total_graphs = 0
        total_size = 0
        total_versions = 0

        if self._users_path.exists():
            for user_dir in self._users_path.iterdir():
                if not user_dir.is_dir():
                    continue
                total_users += 1

                graph_file = user_dir / "graph.json"
                if graph_file.exists():
                    total_graphs += 1
                    total_size += graph_file.stat().st_size

                versions_dir = user_dir / "versions"
                if versions_dir.exists():
                    for v in versions_dir.glob("v_*.json"):
                        total_versions += 1
                        total_size += v.stat().st_size

        # Include admin graph
        admin_graph = self._base_path / "graph.json"
        if admin_graph.exists():
            total_size += admin_graph.stat().st_size

        return {
            "total_users_with_data": total_users,
            "total_graphs": total_graphs,
            "total_versions": total_versions,
            "total_storage_bytes": total_size,
        }
