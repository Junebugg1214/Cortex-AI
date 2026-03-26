from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from cortex.storage import get_storage_backend

BACKUP_FORMAT_VERSION = "1"
STORE_PREFIX = "store/"
MANIFEST_NAME = "manifest.json"
SKIP_NAMES = {".DS_Store"}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _iter_store_files(store_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for path in sorted(store_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name in SKIP_NAMES or path.name.endswith(".lock"):
            continue
        paths.append(path)
    return paths


def _manifest_for_store(store_dir: Path) -> dict:
    backend = get_storage_backend(store_dir)
    files = _iter_store_files(store_dir)
    return {
        "format_version": BACKUP_FORMAT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "store_dir_name": store_dir.name,
        "backend": type(backend).__module__.split(".")[-1],
        "current_branch": backend.versions.current_branch(),
        "head": backend.versions.resolve_ref("HEAD"),
        "files": [
            {
                "path": str(path.relative_to(store_dir)),
                "size": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
            for path in files
        ],
    }


def export_store_backup(
    store_dir: str | Path,
    output_path: str | Path,
    *,
    verify: bool = True,
) -> dict:
    source = Path(store_dir)
    if not source.exists():
        raise FileNotFoundError(f"Store directory not found: {source}")
    manifest = _manifest_for_store(source)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2, ensure_ascii=False))
        for item in manifest["files"]:
            archive.write(source / item["path"], arcname=f"{STORE_PREFIX}{item['path']}")
    if verify:
        verification = verify_store_backup(destination)
        if not verification["valid"]:
            raise ValueError(f"Backup verification failed for {destination}")
        manifest["verification"] = verification
    return {
        "status": "ok",
        "archive": str(destination),
        "manifest": manifest,
    }


def verify_store_backup(archive_path: str | Path) -> dict:
    path = Path(archive_path)
    if not path.exists():
        raise FileNotFoundError(f"Backup archive not found: {path}")
    with ZipFile(path, "r") as archive:
        try:
            manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
        except KeyError as exc:
            raise ValueError(f"Backup archive is missing {MANIFEST_NAME}: {path}") from exc
        mismatches: list[dict] = []
        for item in manifest.get("files", []):
            archive_name = f"{STORE_PREFIX}{item['path']}"
            try:
                payload = archive.read(archive_name)
            except KeyError:
                mismatches.append({"path": item["path"], "reason": "missing"})
                continue
            actual_hash = _sha256_bytes(payload)
            if actual_hash != item["sha256"]:
                mismatches.append(
                    {
                        "path": item["path"],
                        "reason": "sha256_mismatch",
                        "expected": item["sha256"],
                        "actual": actual_hash,
                    }
                )
            if len(payload) != int(item["size"]):
                mismatches.append(
                    {
                        "path": item["path"],
                        "reason": "size_mismatch",
                        "expected": int(item["size"]),
                        "actual": len(payload),
                    }
                )
    return {
        "status": "ok",
        "archive": str(path),
        "valid": not mismatches,
        "file_count": len(manifest.get("files", [])),
        "backend": manifest.get("backend"),
        "current_branch": manifest.get("current_branch"),
        "head": manifest.get("head"),
        "mismatches": mismatches,
    }


def _clear_directory(path: Path) -> None:
    if not path.exists():
        return
    for child in path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def restore_store_backup(
    archive_path: str | Path,
    store_dir: str | Path,
    *,
    verify: bool = True,
    force: bool = False,
) -> dict:
    archive = Path(archive_path)
    destination = Path(store_dir)
    verification = verify_store_backup(archive) if verify else None
    if verification is not None and not verification["valid"]:
        raise ValueError(f"Backup verification failed for {archive}")
    if destination.exists() and any(destination.iterdir()) and not force:
        raise ValueError(f"Target store directory is not empty: {destination}. Pass --force to overwrite it.")
    destination.mkdir(parents=True, exist_ok=True)
    if force:
        _clear_directory(destination)

    with tempfile.TemporaryDirectory(prefix="cortex_restore_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        with ZipFile(archive, "r") as zip_archive:
            zip_archive.extractall(tmp_path)
        restored_root = tmp_path / "store"
        if not restored_root.exists():
            raise ValueError(f"Backup archive is missing '{STORE_PREFIX}' content: {archive}")
        for source in sorted(restored_root.rglob("*")):
            relative = source.relative_to(restored_root)
            target = destination / relative
            if source.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    post_verify = verify_store_backup(archive)
    backend = get_storage_backend(destination)
    return {
        "status": "ok",
        "archive": str(archive),
        "store_dir": str(destination),
        "verified": post_verify["valid"],
        "backend": type(backend).__module__.split(".")[-1],
        "current_branch": backend.versions.current_branch(),
        "head": backend.versions.resolve_ref("HEAD"),
    }


__all__ = [
    "BACKUP_FORMAT_VERSION",
    "export_store_backup",
    "restore_store_backup",
    "verify_store_backup",
]
