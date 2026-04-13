from __future__ import annotations

import json
from pathlib import Path

from cortex.cli import main
from cortex.mind_mounts import query_mounted_pack_provenance
from cortex.minds import attach_pack_to_mind, init_mind
from cortex.packs import (
    compile_pack,
    ingest_pack,
    init_pack,
    inspect_pack_artifact,
    pack_fact_provenance,
    pack_status,
)


def _seed_source(path: Path) -> None:
    path.write_text(
        (
            "# Launch Notes\n\n"
            "On 2026-02-01 Atlas launched.\n"
            "Working with Alice on launch readiness.\n"
            "I use Python and FastAPI.\n"
        ),
        encoding="utf-8",
    )


def _compiled_pack(tmp_path: Path, *, mode: str) -> tuple[Path, dict]:
    store_dir = tmp_path / ".cortex"
    source = tmp_path / f"{mode}.md"
    artifact = tmp_path / f"{mode}.brainpack.json"
    _seed_source(source)
    init_pack(store_dir, f"pack-{mode}", description="Portable AI memory research", owner="marc")
    ingest_pack(store_dir, f"pack-{mode}", [str(source)], mode="copy")
    payload = compile_pack(store_dir, f"pack-{mode}", mode=mode, output_path=artifact)
    return store_dir, payload


def test_distribution_mode_output_contains_no_raw_lineage_fields(tmp_path):
    store_dir, payload = _compiled_pack(tmp_path, mode="distribution")
    artifact = json.loads(Path(payload["output_file"]).read_text(encoding="utf-8"))
    nodes = list(((artifact["graph"] or {}).get("graph") or {}).get("nodes", {}).values())
    claims = artifact["claims"]

    assert payload["compile_mode"] == "distribution"
    assert all(not node.get("provenance") for node in nodes)
    assert all(not node.get("source_quotes") for node in nodes)
    assert all("provenance" not in claim for claim in claims)
    assert all("claim_history" not in claim for claim in claims)
    assert pack_status(store_dir, "pack-distribution")["provenance_available"] is False


def test_full_mode_output_preserves_lineage_confidence_and_contested_state(tmp_path):
    _, payload = _compiled_pack(tmp_path, mode="full")
    artifact = json.loads(Path(payload["output_file"]).read_text(encoding="utf-8"))
    claims = artifact["claims"]

    assert payload["compile_mode"] == "full"
    assert claims
    assert all("provenance" in claim for claim in claims)
    assert all("claim_history" in claim for claim in claims)
    assert all("temporal_confidence" in claim for claim in claims)
    assert all("extraction_confidence" in claim for claim in claims)
    assert all("contested" in claim for claim in claims)
    assert any(claim["contested"] for claim in claims)


def test_full_pack_returns_provenance_for_a_fact(tmp_path):
    store_dir, _ = _compiled_pack(tmp_path, mode="full")

    payload = pack_fact_provenance(store_dir, "pack-full", "Alice")

    assert payload["status"] == "ok"
    assert payload["compile_mode"] == "full"
    assert payload["fact_label"] == "Alice"
    assert payload["provenance"]
    assert payload["claim_history"]


def test_distribution_pack_returns_provenance_unavailable_for_a_fact(tmp_path):
    store_dir, _ = _compiled_pack(tmp_path, mode="distribution")

    payload = pack_fact_provenance(store_dir, "pack-distribution", "Alice")

    assert payload["status"] == "PROVENANCE_UNAVAILABLE"
    assert payload["compile_mode"] == "distribution"


def test_mounted_full_pack_returns_correct_provenance(tmp_path):
    store_dir, _ = _compiled_pack(tmp_path, mode="full")
    init_mind(store_dir, "ops", owner="tester")
    attach_pack_to_mind(store_dir, "ops", "pack-full")

    payload = query_mounted_pack_provenance(store_dir, "ops", pack_name="pack-full", fact_identifier="Alice")

    assert payload["mind"] == "ops"
    assert payload["pack"] == "pack-full"
    assert payload["status"] == "ok"
    assert payload["provenance"]


def test_mounted_distribution_pack_returns_provenance_unavailable(tmp_path):
    store_dir, _ = _compiled_pack(tmp_path, mode="distribution")
    init_mind(store_dir, "ops", owner="tester")
    attach_pack_to_mind(store_dir, "ops", "pack-distribution")

    payload = query_mounted_pack_provenance(store_dir, "ops", pack_name="pack-distribution", fact_identifier="Alice")

    assert payload["status"] == "PROVENANCE_UNAVAILABLE"
    assert payload["compile_mode"] == "distribution"


def test_pack_inspect_identifies_distribution_mode(tmp_path):
    _, payload = _compiled_pack(tmp_path, mode="distribution")

    inspection = inspect_pack_artifact(payload["output_file"])

    assert inspection["compile_mode"] == "distribution"
    assert inspection["provenance_available"] is False
    assert inspection["lossy"] is True


def test_pack_inspect_identifies_full_mode_and_provenance_nodes(tmp_path):
    _, payload = _compiled_pack(tmp_path, mode="full")

    inspection = inspect_pack_artifact(payload["output_file"], show_provenance=True)

    assert inspection["compile_mode"] == "full"
    assert inspection["provenance_available"] is True
    assert inspection["provenance_nodes"]
    assert any(item["provenance_count"] > 0 for item in inspection["provenance_nodes"])


def test_pack_status_surfaces_compile_mode_metadata(tmp_path):
    store_dir, _ = _compiled_pack(tmp_path, mode="full")

    status = pack_status(store_dir, "pack-full")

    assert status["compile_mode"] == "full"
    assert status["provenance_available"] is True
    assert status["lossy"] is False


def test_pack_inspect_cli_reports_compilation_mode(tmp_path, capsys):
    _, payload = _compiled_pack(tmp_path, mode="full")

    rc = main(["pack", "inspect", payload["output_file"], "--show-provenance", "--format", "json"])
    output = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert output["compile_mode"] == "full"
    assert output["provenance_available"] is True
