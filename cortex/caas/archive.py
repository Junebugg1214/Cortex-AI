"""
Cortex Archive — ZIP export/import for graph + profiles + credentials.

All stdlib: zipfile, io, hashlib, json. No private keys are included.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cortex.graph import CortexGraph


def create_archive(
    graph: CortexGraph,
    profile_store: Any | None = None,
    credential_store: Any | None = None,
    identity: Any | None = None,
) -> bytes:
    """Create a ZIP archive containing graph, profiles, and credentials.

    Returns raw bytes of the ZIP file. No private keys are included.
    """
    graph_data = graph.export_v5()
    graph_json = json.dumps(graph_data, indent=2, ensure_ascii=False).encode("utf-8")
    graph_hash = hashlib.sha256(graph_json).hexdigest()

    profiles_data: list[dict] = []
    if profile_store is not None:
        profiles_data = [p.to_dict() for p in profile_store.list_all()]
    profiles_json = json.dumps(profiles_data, indent=2, ensure_ascii=False).encode("utf-8")
    profiles_hash = hashlib.sha256(profiles_json).hexdigest()

    credentials_data: list[dict] = []
    if credential_store is not None:
        creds = credential_store.list_all()
        credentials_data = [c.to_dict() for c in creds]
    credentials_json = json.dumps(credentials_data, indent=2, ensure_ascii=False).encode("utf-8")
    credentials_hash = hashlib.sha256(credentials_json).hexdigest()

    manifest = {
        "version": "1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "profile_count": len(profiles_data),
        "credential_count": len(credentials_data),
        "checksums": {
            "graph.json": graph_hash,
            "profiles.json": profiles_hash,
            "credentials.json": credentials_hash,
        },
    }
    if identity is not None:
        manifest["did"] = identity.did

    manifest_json = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("cortex-archive/manifest.json", manifest_json)
        zf.writestr("cortex-archive/graph.json", graph_json)
        zf.writestr("cortex-archive/profiles.json", profiles_json)
        zf.writestr("cortex-archive/credentials.json", credentials_json)

    return buf.getvalue()


def import_archive(data: bytes) -> dict:
    """Import a ZIP archive. Validates structure and checksums.

    Returns dict with keys: manifest, graph, profiles, credentials.
    Raises ValueError on invalid archive.
    """
    try:
        buf = io.BytesIO(data)
        zf = zipfile.ZipFile(buf, "r")
    except (zipfile.BadZipFile, Exception) as exc:
        raise ValueError(f"Invalid ZIP file: {exc}") from exc

    try:
        names = zf.namelist()

        # Find manifest
        manifest_path = None
        for n in names:
            if n.endswith("manifest.json"):
                manifest_path = n
                break
        if manifest_path is None:
            raise ValueError("Archive missing manifest.json")

        prefix = manifest_path.rsplit("manifest.json", 1)[0]

        try:
            manifest = json.loads(zf.read(manifest_path))
        except (json.JSONDecodeError, KeyError) as exc:
            raise ValueError(f"Invalid manifest: {exc}") from exc

        checksums = manifest.get("checksums", {})

        result: dict[str, Any] = {"manifest": manifest}

        for filename in ("graph.json", "profiles.json", "credentials.json"):
            entry_path = prefix + filename
            if entry_path not in names:
                continue
            raw = zf.read(entry_path)
            # Verify checksum
            expected = checksums.get(filename)
            if expected:
                actual = hashlib.sha256(raw).hexdigest()
                if actual != expected:
                    raise ValueError(
                        f"Checksum mismatch for {filename}: "
                        f"expected {expected[:16]}..., got {actual[:16]}..."
                    )
            key = filename.replace(".json", "")
            result[key] = json.loads(raw)

        return result
    finally:
        zf.close()
