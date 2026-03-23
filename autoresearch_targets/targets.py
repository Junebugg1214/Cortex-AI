from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLES = ROOT / "autoresearch_targets"


@dataclass(frozen=True)
class TargetConfig:
    key: str
    display_name: str
    editable_files: tuple[Path, ...]
    bundle_dir: Path
    target_score: float
    max_experiments: int = 40
    no_improvement_limit: int = 10

    @property
    def program_file(self) -> Path:
        return self.bundle_dir / "program.md"

    @property
    def eval_script(self) -> Path:
        return self.bundle_dir / "eval.py"

    @property
    def generate_corpus_script(self) -> Path:
        return self.bundle_dir / "generate_corpus.py"

    @property
    def corpus_manifest(self) -> Path:
        return self.bundle_dir / "corpus" / "manifest.json"

    @property
    def log_file(self) -> Path:
        return self.bundle_dir / "autoresearch_log.jsonl"

    @property
    def status_json_file(self) -> Path:
        return self.bundle_dir / "autoresearch_status.json"

    @property
    def status_md_file(self) -> Path:
        return self.bundle_dir / "autoresearch_status.md"


TARGET_SEQUENCE = [
    TargetConfig(
        key="extract_coding",
        display_name="Extract Coding",
        editable_files=(ROOT / "cortex" / "coding.py",),
        bundle_dir=BUNDLES / "extract_coding",
        target_score=0.99,
        max_experiments=40,
        no_improvement_limit=10,
    ),
    TargetConfig(
        key="edge_extraction",
        display_name="Edge Extraction",
        editable_files=(ROOT / "cortex" / "edge_extraction.py",),
        bundle_dir=BUNDLES / "edge_extraction",
        target_score=0.97,
        max_experiments=30,
        no_improvement_limit=8,
    ),
    TargetConfig(
        key="contradictions",
        display_name="Contradictions",
        editable_files=(ROOT / "cortex" / "contradictions.py",),
        bundle_dir=BUNDLES / "contradictions",
        target_score=0.97,
        max_experiments=30,
        no_improvement_limit=8,
    ),
    TargetConfig(
        key="timeline",
        display_name="Timeline",
        editable_files=(ROOT / "cortex" / "timeline.py",),
        bundle_dir=BUNDLES / "timeline",
        target_score=0.97,
        max_experiments=30,
        no_improvement_limit=8,
    ),
    TargetConfig(
        key="search",
        display_name="Search",
        editable_files=(ROOT / "cortex" / "search.py",),
        bundle_dir=BUNDLES / "search",
        target_score=0.96,
        max_experiments=30,
        no_improvement_limit=8,
    ),
    TargetConfig(
        key="query_mapping",
        display_name="Query Mapping",
        editable_files=(ROOT / "cortex" / "query.py", ROOT / "cortex" / "query_lang.py"),
        bundle_dir=BUNDLES / "query_mapping",
        target_score=0.95,
        max_experiments=35,
        no_improvement_limit=10,
    ),
    TargetConfig(
        key="dedup",
        display_name="Dedup",
        editable_files=(ROOT / "cortex" / "dedup.py",),
        bundle_dir=BUNDLES / "dedup",
        target_score=0.95,
        max_experiments=30,
        no_improvement_limit=8,
    ),
    TargetConfig(
        key="intelligence",
        display_name="Intelligence",
        editable_files=(ROOT / "cortex" / "intelligence.py",),
        bundle_dir=BUNDLES / "intelligence",
        target_score=0.95,
        max_experiments=30,
        no_improvement_limit=8,
    ),
]


def get_target(key: str) -> TargetConfig:
    for target in TARGET_SEQUENCE:
        if target.key == key:
            return target
    raise KeyError(f"Unknown target: {key}")
