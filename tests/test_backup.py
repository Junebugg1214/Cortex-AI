import json
import shutil
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

import cortex.backup as backup_mod
from cortex.backup import export_store_backup, restore_store_backup, verify_store_backup
from cortex.cli import main
from cortex.graph import CortexGraph, Node
from cortex.storage import get_storage_backend
from cortex.storage.sqlite import build_sqlite_backend


def _graph_with_node(node: Node) -> CortexGraph:
    graph = CortexGraph()
    graph.add_node(node)
    return graph


def test_backup_export_verify_and_restore_preserves_sqlite_store(tmp_path):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    graph = _graph_with_node(
        Node(
            id="atlas",
            label="Project Atlas",
            aliases=["atlas"],
            tags=["active_priorities"],
            confidence=0.94,
        )
    )
    commit = backend.versions.commit(graph, "baseline")
    backend.indexing.rebuild(ref="HEAD")
    (store_dir / "config.toml").write_text("[mcp]\nnamespace = 'team'\n", encoding="utf-8")

    archive = tmp_path / "atlas-backup.zip"
    exported = export_store_backup(store_dir, archive)
    verified = verify_store_backup(archive)
    restored_dir = tmp_path / "restored-store"
    restored = restore_store_backup(archive, restored_dir)
    restored_backend = get_storage_backend(restored_dir)
    search = restored_backend.indexing.search(query="atlas", ref="HEAD", limit=5)

    assert exported["archive"] == str(archive)
    assert verified["valid"] is True
    assert restored["head"] == commit.version_id
    assert restored_backend.versions.resolve_ref("HEAD") == commit.version_id
    assert search[0]["node"]["label"] == "Project Atlas"
    assert (restored_dir / "config.toml").exists()


def test_backup_cli_export_verify_and_restore_round_trip(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    backend.versions.commit(_graph_with_node(Node(id="sdk", label="Python SDK")), "baseline")

    archive = tmp_path / "cli-backup.zip"
    export_rc = main(["backup", "export", "--store-dir", str(store_dir), "--output", str(archive)])
    verify_rc = main(["backup", "verify", str(archive)])
    restored_dir = tmp_path / "cli-restored"
    restore_rc = main(["backup", "restore", str(archive), "--store-dir", str(restored_dir)])
    output = capsys.readouterr().out

    assert export_rc == 0
    assert verify_rc == 0
    assert restore_rc == 0
    assert archive.exists()
    assert "cli-restored" in output


def test_restore_detects_corrupted_copy_during_restore(tmp_path, monkeypatch):
    store_dir = tmp_path / ".cortex"
    backend = build_sqlite_backend(store_dir)
    backend.versions.commit(_graph_with_node(Node(id="atlas", label="Project Atlas")), "baseline")
    archive = tmp_path / "atlas-backup.zip"
    export_store_backup(store_dir, archive)

    original_copy2 = shutil.copy2

    def corrupt_copy(source, target, *args, **kwargs):
        result = original_copy2(source, target, *args, **kwargs)
        target_path = Path(target)
        if target_path.name == "cortex.db":
            target_path.write_bytes(b"corrupted")
        return result

    monkeypatch.setattr(backup_mod.shutil, "copy2", corrupt_copy)

    with pytest.raises(ValueError, match="Restored store verification failed"):
        restore_store_backup(archive, tmp_path / "restored")


def test_restore_rejects_path_traversal_archive_entries(tmp_path):
    archive = tmp_path / "unsafe-backup.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as handle:
        handle.writestr("manifest.json", json.dumps({"format_version": "1", "files": []}))
        handle.writestr("store/../../outside.txt", "nope")

    with pytest.raises(ValueError, match="unsafe path traversal"):
        restore_store_backup(archive, tmp_path / "restored")
