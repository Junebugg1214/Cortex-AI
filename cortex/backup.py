from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
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


def _read_backup_manifest(archive_path: str | Path) -> dict:
    path = Path(archive_path)
    if not path.exists():
        raise FileNotFoundError(f"Backup archive not found: {path}")
    with ZipFile(path, "r") as archive:
        try:
            return json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
        except KeyError as exc:
            raise ValueError(f"Backup archive is missing {MANIFEST_NAME}: {path}") from exc


def _safe_archive_members(archive: ZipFile) -> list[tuple[str, PurePosixPath]]:
    members: list[tuple[str, PurePosixPath]] = []
    for info in archive.infolist():
        name = info.filename
        if name == MANIFEST_NAME:
            continue
        if not name.startswith(STORE_PREFIX):
            raise ValueError(f"Backup archive contains unexpected entry outside '{STORE_PREFIX}': {name}")
        if info.is_dir():
            continue
        relative = PurePosixPath(name[len(STORE_PREFIX) :])
        parts = [part for part in relative.parts if part not in ("", ".")]
        if not parts:
            continue
        if any(part == ".." for part in parts):
            raise ValueError(f"Backup archive contains unsafe path traversal entry: {name}")
        members.append((name, PurePosixPath(*parts)))
    return members


def _verify_restored_store(store_dir: Path, manifest: dict) -> dict:
    expected = {
        str(item["path"]): {
            "sha256": str(item["sha256"]),
            "size": int(item["size"]),
        }
        for item in manifest.get("files", [])
    }
    actual = {str(path.relative_to(store_dir)): path for path in _iter_store_files(store_dir)}
    mismatches: list[dict] = []

    for missing in sorted(set(expected) - set(actual)):
        mismatches.append({"path": missing, "reason": "missing_after_restore"})
    for extra in sorted(set(actual) - set(expected)):
        mismatches.append({"path": extra, "reason": "unexpected_after_restore"})
    for relative in sorted(set(expected) & set(actual)):
        path = actual[relative]
        expected_entry = expected[relative]
        actual_hash = _sha256_file(path)
        actual_size = path.stat().st_size
        if actual_hash != expected_entry["sha256"]:
            mismatches.append(
                {
                    "path": relative,
                    "reason": "sha256_mismatch_after_restore",
                    "expected": expected_entry["sha256"],
                    "actual": actual_hash,
                }
            )
        if actual_size != expected_entry["size"]:
            mismatches.append(
                {
                    "path": relative,
                    "reason": "size_mismatch_after_restore",
                    "expected": expected_entry["size"],
                    "actual": actual_size,
                }
            )

    return {
        "status": "ok",
        "store_dir": str(store_dir),
        "valid": not mismatches,
        "file_count": len(expected),
        "mismatches": mismatches,
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
    if not source.is_dir():
        raise ValueError(f"Store path is not a directory: {source}")
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
    manifest = _read_backup_manifest(path)
    with ZipFile(path, "r") as archive:
        _safe_archive_members(archive)
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
    if destination.exists() and not destination.is_dir():
        raise ValueError(f"Target store path is not a directory: {destination}")
    manifest = _read_backup_manifest(archive)
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
            members = _safe_archive_members(zip_archive)
            for archive_name, relative_path in members:
                target = tmp_path / Path(relative_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zip_archive.read(archive_name))
        restored_root = tmp_path
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

    restored_verification = _verify_restored_store(destination, manifest)
    if verify and not restored_verification["valid"]:
        raise ValueError(f"Restored store verification failed for {destination}")
    backend = get_storage_backend(destination)
    return {
        "status": "ok",
        "archive": str(archive),
        "store_dir": str(destination),
        "verified": restored_verification["valid"],
        "verification": restored_verification,
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
