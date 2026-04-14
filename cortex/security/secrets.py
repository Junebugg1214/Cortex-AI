"""Secret detection and `.cortexignore` support for Cortex ingestion flows."""

from __future__ import annotations

import fnmatch
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .validate import InputValidator

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from cortex.graph import CortexGraph

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("anthropic_api_key", re.compile(r"\bsk-ant-[A-Za-z0-9\-_]{16,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    (
        "private_key_block",
        re.compile(r"-----BEGIN (?:RSA|EC|OPENSSH|DSA|PGP|PRIVATE) KEY-----"),
    ),
    (
        "generic_assignment",
        re.compile(r"\b(?:api[_-]?key|secret|token|password)\b\s*[:=]\s*['\"]?[A-Za-z0-9_\-\/+=]{8,}"),
    ),
)


@dataclass(frozen=True, slots=True)
class SecretMatch:
    """A potential secret detected in Cortex-managed content."""

    rule_id: str
    snippet: str
    start: int
    end: int

    def to_dict(self) -> dict[str, Any]:
        """Serialize the match for JSON responses or logs."""
        return {
            "rule_id": self.rule_id,
            "snippet": self.snippet,
            "start": self.start,
            "end": self.end,
        }


@dataclass(frozen=True, slots=True)
class CortexIgnore:
    """Simple `.cortexignore` matcher based on glob patterns."""

    root_dir: Path
    patterns: tuple[str, ...]

    @classmethod
    def discover(cls, *, start: str | Path | None = None) -> "CortexIgnore":
        """Load the nearest `.cortexignore` file walking upward from `start`."""
        origin = Path(start or Path.cwd()).expanduser().resolve()
        for candidate in (origin, *origin.parents):
            ignore_path = candidate / ".cortexignore"
            if ignore_path.exists():
                lines = [
                    line.strip()
                    for line in ignore_path.read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.strip().startswith("#")
                ]
                return cls(root_dir=candidate, patterns=tuple(lines))
        return cls(root_dir=origin, patterns=tuple())

    def matches(self, path: str | Path) -> bool:
        """Return True when the path should be excluded from ingestion."""
        candidate = Path(path).expanduser().resolve(strict=False)
        rel = str(candidate)
        if candidate.is_relative_to(self.root_dir):
            rel = candidate.relative_to(self.root_dir).as_posix()
        name = candidate.name
        return any(fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(name, pattern) for pattern in self.patterns)


@dataclass(slots=True)
class SecretsScanner:
    """Detect secret-like strings inside graph nodes, text, and source files."""

    validator: InputValidator = InputValidator()

    def scan_text(self, text: str | bytes, *, field_name: str = "text") -> list[SecretMatch]:
        """Return all secret-like matches found in a text value."""
        normalized = self.validator.validate_text(text, field_name=field_name)
        matches: list[SecretMatch] = []
        for rule_id, pattern in _SECRET_PATTERNS:
            for match in pattern.finditer(normalized):
                snippet = normalized[max(0, match.start() - 8) : min(len(normalized), match.end() + 8)]
                matches.append(
                    SecretMatch(
                        rule_id=rule_id,
                        snippet=snippet,
                        start=match.start(),
                        end=match.end(),
                    )
                )
        return matches

    def scan_node(self, node: Any) -> list[SecretMatch]:
        """Scan a Cortex node-like object for secret material."""
        values: list[str] = [
            str(getattr(node, "label", "") or ""),
            str(getattr(node, "brief", "") or ""),
            str(getattr(node, "full_description", "") or ""),
            *[str(item) for item in list(getattr(node, "aliases", []) or [])],
            *[str(item) for item in list(getattr(node, "source_quotes", []) or [])],
        ]
        properties = dict(getattr(node, "properties", {}) or {})
        for key, value in properties.items():
            if isinstance(value, (str, bytes)):
                values.append(f"{key}={value}")
        matches: list[SecretMatch] = []
        for index, value in enumerate(values):
            matches.extend(self.scan_text(value, field_name=f"node[{getattr(node, 'id', 'unknown')}].{index}"))
        return matches

    def scan_graph(self, graph: CortexGraph) -> dict[str, Any]:
        """Return a secret scan report for every node in a graph."""
        findings: list[dict[str, Any]] = []
        for node in graph.nodes.values():
            matches = self.scan_node(node)
            if matches:
                findings.append(
                    {
                        "node_id": node.id,
                        "label": node.label,
                        "matches": [match.to_dict() for match in matches],
                    }
                )
        return {
            "status": "ok",
            "finding_count": len(findings),
            "findings": findings,
        }

    def secret_node_ids(self, graph: CortexGraph) -> list[str]:
        """Return node ids whose content matches a secret rule."""
        return [item["node_id"] for item in self.scan_graph(graph)["findings"]]

    def warn_if_graph_contains_secrets(self, graph: CortexGraph, *, operation: str) -> dict[str, Any]:
        """Log a warning when the graph contains likely secrets."""
        report = self.scan_graph(graph)
        if report["finding_count"]:
            logger.warning(
                "Detected %s secret-like graph finding(s) during %s.",
                report["finding_count"],
                operation,
                extra={"operation": operation, "finding_count": report["finding_count"]},
            )
        return report


__all__ = ["CortexIgnore", "SecretMatch", "SecretsScanner"]
