from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CORPUS_ROOT = Path(__file__).parent / "corpus"
INPUT_FILENAMES = {"input.md", "input.json", "input.jsonl"}
SOURCE_TYPES = {"chat", "doc", "code", "transcript"}
GOLD_SCHEMA_VERSION = "extraction-eval-v1"


def _parse_manifest(path: Path) -> list[dict[str, str]]:
    cases: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("- "):
            if current is not None:
                cases.append(current)
            current = {}
            stripped = stripped[2:]
        if current is None:
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        current[key.strip()] = value.strip().strip("\"'")
    if current is not None:
        cases.append(current)
    return cases


def _assert_non_empty_string(payload: dict[str, Any], key: str) -> None:
    assert isinstance(payload.get(key), str), f"{key} must be a string"
    assert payload[key].strip(), f"{key} must be non-empty"


def _assert_confidence(payload: dict[str, Any]) -> None:
    confidence = payload.get("confidence")
    assert isinstance(confidence, int | float), "confidence must be numeric"
    assert 0.0 <= float(confidence) <= 1.0, "confidence must be between 0 and 1"


def _assert_gold_schema(gold: dict[str, Any], *, case_id: str, source_type: str) -> None:
    assert gold.get("schema_version") == GOLD_SCHEMA_VERSION
    assert gold.get("case_id") == case_id
    assert gold.get("source_type") == source_type
    expected_graph = gold.get("expected_graph")
    assert isinstance(expected_graph, dict), "expected_graph must be an object"
    nodes = expected_graph.get("nodes")
    edges = expected_graph.get("edges")
    assert isinstance(nodes, list), "expected_graph.nodes must be a list"
    assert isinstance(edges, list), "expected_graph.edges must be a list"

    canonical_ids: set[str] = set()
    for node in nodes:
        assert isinstance(node, dict), "nodes must be objects"
        for key in ("id", "canonical_id", "label", "type"):
            _assert_non_empty_string(node, key)
        _assert_confidence(node)
        canonical_id = node["canonical_id"]
        assert canonical_id not in canonical_ids, f"duplicate canonical_id {canonical_id}"
        canonical_ids.add(canonical_id)

    for edge in edges:
        assert isinstance(edge, dict), "edges must be objects"
        for key in ("id", "source", "target", "type"):
            _assert_non_empty_string(edge, key)
        _assert_confidence(edge)
        assert edge["source"] in canonical_ids, f"edge source {edge['source']} missing from nodes"
        assert edge["target"] in canonical_ids, f"edge target {edge['target']} missing from nodes"


def test_every_case_has_input_and_gold_with_valid_schema() -> None:
    assert (CORPUS_ROOT / "README.md").is_file()
    manifest_path = CORPUS_ROOT / "manifest.yml"
    assert manifest_path.is_file()
    cases = _parse_manifest(manifest_path)
    assert len(cases) >= 5

    required_case_ids = {
        "chat_name_role_preference",
        "policy_two_rules",
        "transcript_contradiction",
        "code_readme_stack_mentions",
        "pathological_empty_garbled_profanity",
    }
    case_ids = {case.get("id", "") for case in cases}
    assert required_case_ids.issubset(case_ids)

    for case in cases:
        case_id = case.get("id", "")
        source_type = case.get("source_type", "")
        input_name = case.get("input", "")
        gold_name = case.get("gold", "")
        assert case_id
        assert source_type in SOURCE_TYPES
        assert input_name in INPUT_FILENAMES
        assert gold_name == "gold.json"

        case_dir = CORPUS_ROOT / case_id
        assert case_dir.is_dir(), f"missing case directory {case_id}"
        inputs = [path.name for path in case_dir.iterdir() if path.name in INPUT_FILENAMES]
        assert inputs == [input_name], f"{case_id} must contain exactly {input_name}"
        assert (case_dir / input_name).is_file()
        assert (case_dir / gold_name).is_file()

        gold = json.loads((case_dir / gold_name).read_text(encoding="utf-8"))
        assert isinstance(gold, dict)
        _assert_gold_schema(gold, case_id=case_id, source_type=source_type)
