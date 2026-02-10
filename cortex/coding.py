"""
Cortex Coding Session Extraction — Phase 7 (v6.1)

Extracts identity signals from coding tool sessions (Claude Code, Cursor, Copilot).
Unlike chatbot extraction (regex on declarative text), coding extraction infers
identity from behavior: files touched, tools used, commands run, patterns followed.

Zero external deps. Outputs v4-compatible dicts for merge with existing pipeline.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# File extension -> technology mapping
# ---------------------------------------------------------------------------

EXTENSION_MAP: dict[str, str] = {
    ".py": "Python", ".pyw": "Python",
    ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".jsx": "React (JSX)",
    ".rs": "Rust",
    ".go": "Go",
    ".java": "Java",
    ".kt": "Kotlin", ".kts": "Kotlin",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".c": "C", ".h": "C",
    ".cpp": "C++", ".hpp": "C++", ".cc": "C++",
    ".cs": "C#",
    ".scala": "Scala",
    ".sql": "SQL",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell",
    ".html": "HTML", ".htm": "HTML",
    ".css": "CSS", ".scss": "SCSS", ".less": "Less",
    ".yml": "YAML", ".yaml": "YAML",
    ".toml": "TOML",
    ".dockerfile": "Docker",
}

# Config/project file -> technology
CONFIG_FILE_PATTERNS: dict[str, str] = {
    "package.json": "Node.js",
    "tsconfig.json": "TypeScript",
    "Cargo.toml": "Rust",
    "go.mod": "Go",
    "pyproject.toml": "Python",
    "setup.py": "Python",
    "requirements.txt": "Python",
    "Pipfile": "Python",
    "Gemfile": "Ruby",
    "pom.xml": "Maven",
    "build.gradle": "Gradle",
    "docker-compose.yml": "Docker",
    "docker-compose.yaml": "Docker",
    "Dockerfile": "Docker",
    "Makefile": "Make",
    "CMakeLists.txt": "CMake",
    "jest.config": "Jest",
    "pytest.ini": "Pytest",
    "setup.cfg": "Python",
    ".eslintrc": "ESLint",
    ".prettierrc": "Prettier",
}

# Regex on bash commands -> tool/technology
BASH_TOOL_PATTERNS: dict[str, str] = {
    r"\bpytest\b": "Pytest",
    r"\bpython3?\b": "Python",
    r"\bnpm\b": "npm",
    r"\byarn\b": "Yarn",
    r"\bpnpm\b": "pnpm",
    r"\bcargo\b": "Cargo",
    r"\bgo\s+(?:build|run|test|mod|get)\b": "Go",
    r"\bdocker\b": "Docker",
    r"\bkubectl\b": "Kubernetes",
    r"\bgit\b": "Git",
    r"\bmake\b": "Make",
    r"\bpip3?\s+install\b": "pip",
    r"\bcurl\b": "curl",
    r"\baws\b": "AWS CLI",
    r"\bgcloud\b": "Google Cloud CLI",
    r"\baz\b": "Azure CLI",
    r"\bgh\b": "GitHub CLI",
}

# Valid Claude Code record types
_CC_RECORD_TYPES = frozenset({
    "user", "assistant", "progress", "file-history-snapshot", "system",
    "pr-link", "queue-operation",
})


# ---------------------------------------------------------------------------
# ProjectMetadata dataclass
# ---------------------------------------------------------------------------

@dataclass
class ProjectMetadata:
    """Metadata extracted from project files on disk."""

    name: str = ""               # From manifest or dir name
    description: str = ""        # From README or manifest description field
    readme_summary: str = ""     # First paragraph of README (up to 500 chars)
    license: str = ""            # License identifier (MIT, Apache-2.0, etc.)
    keywords: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    manifest_file: str = ""      # Which manifest found (package.json, etc.)
    has_ci: bool = False
    has_docker: bool = False
    enriched: bool = False       # True if enrichment found useful data


# ---------------------------------------------------------------------------
# CodingSession dataclass
# ---------------------------------------------------------------------------

@dataclass
class CodingSession:
    """Parsed representation of a coding tool session."""

    session_id: str = ""
    tool: str = ""                   # "claude_code", "cursor", "copilot"
    project_path: str = ""           # cwd / working directory
    git_branch: str = ""
    start_time: datetime | None = None
    end_time: datetime | None = None
    model: str = ""                  # AI model used
    version: str = ""                # tool version

    # Aggregated signals
    files_touched: Counter = field(default_factory=Counter)
    file_extensions: Counter = field(default_factory=Counter)
    tool_usage: Counter = field(default_factory=Counter)
    bash_commands: list[str] = field(default_factory=list)
    bash_tools: Counter = field(default_factory=Counter)
    user_prompts: list[str] = field(default_factory=list)
    technologies: Counter = field(default_factory=Counter)
    config_files: list[str] = field(default_factory=list)
    branches: set = field(default_factory=set)

    # Behavioral patterns
    test_files_written: int = 0
    impl_files_written: int = 0
    plan_mode_used: bool = False
    total_edits: int = 0
    total_reads: int = 0
    total_writes: int = 0
    error_count: int = 0

    # Project enrichment (populated by enrich_session())
    project_meta: ProjectMetadata = field(default_factory=ProjectMetadata)


# ---------------------------------------------------------------------------
# Claude Code JSONL detection
# ---------------------------------------------------------------------------

def is_claude_code_jsonl(records: list[dict]) -> bool:
    """Check if a list of JSONL records is Claude Code session format."""
    if not records or len(records) < 2:
        return False
    first_real = next(
        (r for r in records
         if isinstance(r, dict) and r.get("type") in ("user", "assistant", "system")),
        None,
    )
    if first_real is None:
        return False
    return (
        "sessionId" in first_real
        and "cwd" in first_real
        and first_real.get("type") in _CC_RECORD_TYPES
    )


# ---------------------------------------------------------------------------
# Claude Code JSONL parser
# ---------------------------------------------------------------------------

def parse_claude_code_session(records: list[dict]) -> CodingSession:
    """Parse Claude Code JSONL records into a CodingSession."""
    session = CodingSession(tool="claude_code")

    for record in records:
        if not isinstance(record, dict):
            continue
        rtype = record.get("type", "")
        ts = _parse_ts(record.get("timestamp"))

        # Session metadata
        if not session.session_id and record.get("sessionId"):
            session.session_id = record["sessionId"]
        if not session.project_path and record.get("cwd"):
            session.project_path = record["cwd"]
        if record.get("gitBranch"):
            session.git_branch = record["gitBranch"]
            session.branches.add(record["gitBranch"])
        if record.get("version") and not session.version:
            session.version = record["version"]

        # Track session time bounds
        if ts:
            if session.start_time is None or ts < session.start_time:
                session.start_time = ts
            if session.end_time is None or ts > session.end_time:
                session.end_time = ts

        # User messages
        if rtype == "user":
            msg = record.get("message", {})
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                session.user_prompts.append(content)

        # Assistant messages (tool usage)
        elif rtype == "assistant":
            msg = record.get("message", {})
            if msg.get("model") and not session.model:
                session.model = msg["model"]
            content = msg.get("content", [])
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "tool_use":
                        _process_tool_use(item, session)

    return session


def _process_tool_use(tool_use: dict, session: CodingSession) -> None:
    """Process a single tool_use block from an assistant message."""
    name = tool_use.get("name", "")
    inp = tool_use.get("input", {})
    if not isinstance(inp, dict):
        inp = {}

    session.tool_usage[name] += 1

    if name in ("Read", "Glob", "Grep"):
        session.total_reads += 1
        file_path = inp.get("file_path", "") or inp.get("path", "")
        if file_path:
            session.files_touched[file_path] += 1
            _track_file(file_path, session)

    elif name == "Write":
        session.total_writes += 1
        file_path = inp.get("file_path", "")
        if file_path:
            session.files_touched[file_path] += 1
            _track_file(file_path, session)
            if _is_test_file(file_path):
                session.test_files_written += 1
            else:
                session.impl_files_written += 1

    elif name == "Edit":
        session.total_edits += 1
        file_path = inp.get("file_path", "")
        if file_path:
            session.files_touched[file_path] += 1
            _track_file(file_path, session)

    elif name == "Bash":
        cmd = inp.get("command", "")
        if cmd:
            session.bash_commands.append(cmd)
            _parse_bash_command(cmd, session)

    elif name in ("EnterPlanMode", "ExitPlanMode"):
        session.plan_mode_used = True


def _track_file(file_path: str, session: CodingSession) -> None:
    """Track file extension and config file patterns."""
    p = Path(file_path)
    ext = p.suffix.lower()
    if ext:
        session.file_extensions[ext] += 1
    name = p.name
    # Check config file patterns
    for pattern, tech in CONFIG_FILE_PATTERNS.items():
        if name == pattern or pattern in file_path:
            session.technologies[tech] += 1
            if name not in session.config_files:
                session.config_files.append(name)
            break
    # Map extension to technology
    if ext in EXTENSION_MAP:
        session.technologies[EXTENSION_MAP[ext]] += 1


def _is_test_file(file_path: str) -> bool:
    """Heuristic: is this a test file?"""
    name = Path(file_path).name.lower()
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith(".test.ts")
        or name.endswith(".test.js")
        or name.endswith(".spec.ts")
        or name.endswith(".spec.js")
        or "/tests/" in file_path
        or "/test/" in file_path
        or "/__tests__/" in file_path
    )


def _parse_bash_command(cmd: str, session: CodingSession) -> None:
    """Extract tool/technology signals from bash commands."""
    for pattern, tool in BASH_TOOL_PATTERNS.items():
        if re.search(pattern, cmd):
            session.bash_tools[tool] += 1
            session.technologies[tool] += 1


def _parse_ts(ts_str: str | None) -> datetime | None:
    """Parse ISO-8601 timestamp string."""
    if not ts_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(ts_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Project enrichment (reads project files from disk)
# ---------------------------------------------------------------------------

_README_NAMES = ["README.md", "README.rst", "README.txt", "README"]

_LICENSE_PATTERNS: dict[str, str] = {
    "MIT": r"\bMIT\b",
    "Apache-2.0": r"Apache\s+License.*2\.0",
    "GPL-3.0": r"GNU\s+General\s+Public\s+License.*[Vv].*3",
    "GPL-2.0": r"GNU\s+General\s+Public\s+License.*[Vv].*2",
    "BSD-3-Clause": r"BSD\s+3-[Cc]lause",
    "BSD-2-Clause": r"BSD\s+2-[Cc]lause",
    "ISC": r"\bISC\b",
    "Unlicense": r"\bUnlicense\b",
}


def enrich_project(project_path: str) -> ProjectMetadata:
    """Read project files from disk to extract metadata.

    Reads README, package manifests, and checks for CI/Docker.
    Returns ProjectMetadata with whatever could be found.
    Gracefully handles missing files, permission errors, etc.
    """
    meta = ProjectMetadata()
    root = Path(project_path)

    if not root.is_dir():
        return meta

    meta.name = root.name

    # 1. README extraction
    meta.readme_summary = _extract_readme_summary(root)

    # 2. Manifest extraction (package.json, pyproject.toml, Cargo.toml, setup.cfg)
    _extract_manifest_metadata(root, meta)

    # 3. If no description from manifest, use README summary
    if not meta.description and meta.readme_summary:
        meta.description = meta.readme_summary

    # 4. Lightweight signals
    meta.has_ci = (root / ".github" / "workflows").is_dir()
    meta.has_docker = (
        (root / "Dockerfile").exists()
        or (root / "docker-compose.yml").exists()
        or (root / "docker-compose.yaml").exists()
    )

    # 5. License detection
    if not meta.license:
        meta.license = _detect_license(root)

    meta.enriched = bool(meta.description or meta.readme_summary)
    return meta


def enrich_session(session: CodingSession) -> None:
    """Enrich a CodingSession with project file metadata (I/O operation).

    Reads files from session.project_path if it exists on disk.
    Modifies session.project_meta in place.
    """
    if session.project_path:
        session.project_meta = enrich_project(session.project_path)


def _extract_readme_summary(root: Path) -> str:
    """Extract the first meaningful paragraph from a README file."""
    for name in _README_NAMES:
        readme_path = root / name
        if readme_path.exists():
            try:
                text = readme_path.read_text(encoding="utf-8", errors="replace")
                return _parse_readme_first_paragraph(text)
            except (OSError, PermissionError):
                continue
    return ""


def _parse_readme_first_paragraph(text: str) -> str:
    """Parse README text and extract the first meaningful paragraph.

    Skips headings (#), badges ([![), images (![), horizontal rules (---/===),
    code fences (```), and blank lines. Returns first contiguous text block,
    up to 500 chars truncated at word boundary.
    """
    lines = text.split("\n")
    paragraph_lines: list[str] = []
    in_paragraph = False
    in_code_fence = False

    for line in lines:
        stripped = line.strip()

        # Toggle code fence state
        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            if in_paragraph:
                break
            continue

        # Skip everything inside code fences
        if in_code_fence:
            continue

        # Skip empty lines
        if not stripped:
            if in_paragraph:
                break  # End of paragraph
            continue

        # Skip headings, badges, images, rules
        if (
            stripped.startswith("#")
            or stripped.startswith("![")
            or stripped.startswith("[![")
            or stripped.startswith("---")
            or stripped.startswith("===")
        ):
            if in_paragraph:
                break
            continue

        # Content line
        in_paragraph = True
        paragraph_lines.append(stripped)

    result = " ".join(paragraph_lines)
    if len(result) > 500:
        result = result[:500].rsplit(" ", 1)[0] + "..."
    return result


def _extract_manifest_metadata(root: Path, meta: ProjectMetadata) -> None:
    """Extract metadata from project manifest files."""
    # package.json
    pkg_json = root / "package.json"
    if pkg_json.exists():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                meta.manifest_file = "package.json"
                meta.description = data.get("description", "")
                if data.get("name"):
                    meta.name = data["name"]
                meta.license = data.get("license", "")
                kw = data.get("keywords", [])
                if isinstance(kw, list):
                    meta.keywords = [str(k) for k in kw]
                if "typescript" in str(data.get("devDependencies", {})).lower():
                    meta.languages.append("TypeScript")
                else:
                    meta.languages.append("JavaScript")
                return
        except (OSError, json.JSONDecodeError):
            pass

    # pyproject.toml
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            text = pyproject.read_text(encoding="utf-8")
            meta.manifest_file = "pyproject.toml"
            meta.description = _toml_value(text, "description")
            name = _toml_value(text, "name")
            if name:
                meta.name = name
            meta.license = _toml_value(text, "license")
            if "Python" not in meta.languages:
                meta.languages.append("Python")
            return
        except OSError:
            pass

    # Cargo.toml
    cargo = root / "Cargo.toml"
    if cargo.exists():
        try:
            text = cargo.read_text(encoding="utf-8")
            meta.manifest_file = "Cargo.toml"
            meta.description = _toml_value(text, "description")
            name = _toml_value(text, "name")
            if name:
                meta.name = name
            meta.license = _toml_value(text, "license")
            if "Rust" not in meta.languages:
                meta.languages.append("Rust")
            return
        except OSError:
            pass

    # setup.cfg
    setup_cfg = root / "setup.cfg"
    if setup_cfg.exists():
        try:
            import configparser
            cfg = configparser.ConfigParser()
            cfg.read(str(setup_cfg), encoding="utf-8")
            if cfg.has_option("metadata", "description"):
                meta.manifest_file = "setup.cfg"
                meta.description = cfg.get("metadata", "description")
                name = cfg.get("metadata", "name", fallback="")
                if name:
                    meta.name = name
                meta.license = cfg.get("metadata", "license", fallback="")
            if "Python" not in meta.languages:
                meta.languages.append("Python")
        except (OSError, Exception):
            pass


def _toml_value(text: str, key: str) -> str:
    """Extract a simple key = \"value\" from TOML text.

    Handles: key = \"value\" or key = 'value'.
    Does NOT handle multiline strings or inline tables.
    """
    pattern = rf'^\s*{re.escape(key)}\s*=\s*"(.+?)"|^\s*{re.escape(key)}\s*=\s*\'(.+?)\''
    m = re.search(pattern, text, re.MULTILINE)
    if not m:
        return ""
    return m.group(1) or m.group(2) or ""


def _detect_license(root: Path) -> str:
    """Detect license type from LICENSE file."""
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE"):
        path = root / name
        if path.exists():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")[:1000]
                for license_id, pattern in _LICENSE_PATTERNS.items():
                    if re.search(pattern, text):
                        return license_id
            except OSError:
                continue
    return ""


# ---------------------------------------------------------------------------
# CodingSession -> v4-compatible dict
# ---------------------------------------------------------------------------

def session_to_context(session: CodingSession) -> dict:
    """Convert a CodingSession to a v4-compatible extraction dict.

    Returns a dict with schema_version, meta, categories that can be
    fed directly to upgrade_v4_to_v5() or merged with existing context.
    """
    categories: dict[str, list[dict]] = defaultdict(list)
    now = datetime.now(timezone.utc).isoformat()
    first = session.start_time.isoformat() if session.start_time else now
    last = session.end_time.isoformat() if session.end_time else now

    # --- Technical expertise (from file extensions + technologies) ---
    seen_tech: set[str] = set()
    for tech, count in session.technologies.most_common():
        if count < 1:
            continue
        tech_lower = tech.lower()
        if tech_lower in seen_tech:
            continue
        seen_tech.add(tech_lower)
        categories["technical_expertise"].append(_make_topic(
            topic=tech,
            brief=f"Uses {tech} (observed in coding session)",
            confidence=_frequency_confidence(count),
            mention_count=count,
            first_seen=first,
            last_seen=last,
        ))

    # --- Active priorities (from project path, enriched if available) ---
    if session.project_path:
        pm = session.project_meta
        project_name = pm.name if pm.enriched else Path(session.project_path).name

        if pm.description:
            brief = f"Active project: {project_name} — {pm.description}"[:200]
        else:
            brief = f"Active project: {project_name}"

        desc_parts = [f"Working directory: {session.project_path}"]
        if pm.readme_summary and pm.readme_summary != pm.description:
            desc_parts.append(f"README: {pm.readme_summary}")
        if pm.license:
            desc_parts.append(f"License: {pm.license}")
        if pm.languages:
            desc_parts.append(f"Languages: {', '.join(pm.languages)}")
        if pm.manifest_file:
            desc_parts.append(f"Manifest: {pm.manifest_file}")

        metrics: list[str] = []
        if pm.has_ci:
            metrics.append("CI/CD configured")
        if pm.has_docker:
            metrics.append("Docker configured")
        if pm.keywords:
            metrics.append(f"Keywords: {', '.join(pm.keywords[:10])}")

        categories["active_priorities"].append(_make_topic(
            topic=project_name,
            brief=brief,
            full_description=" | ".join(desc_parts),
            confidence=0.90 if pm.enriched else 0.85,
            metrics=metrics,
            first_seen=first,
            last_seen=last,
        ))

        # Add domain_knowledge entry if we have a substantive description
        if pm.description and len(pm.description) > 20:
            categories.setdefault("domain_knowledge", [])
            categories["domain_knowledge"].append(_make_topic(
                topic=f"{project_name} purpose",
                brief=pm.description[:200],
                full_description=pm.readme_summary or pm.description,
                confidence=0.80,
                first_seen=first,
                last_seen=last,
            ))

    # --- User preferences (from coding patterns) ---
    if session.plan_mode_used:
        categories["user_preferences"].append(_make_topic(
            topic="Plans before coding",
            brief="Uses plan mode before implementation",
            confidence=0.7,
            first_seen=first,
            last_seen=last,
        ))

    if session.test_files_written > 0:
        categories["user_preferences"].append(_make_topic(
            topic="Writes tests",
            brief=f"Testing approach: {session.test_files_written} test files written",
            confidence=0.65,
            metrics=[
                f"{session.test_files_written} test files",
                f"{session.impl_files_written} implementation files",
            ],
            first_seen=first,
            last_seen=last,
        ))

    # --- CLI tools from bash commands ---
    seen_tools: set[str] = set()
    for tool, count in session.bash_tools.most_common():
        if count < 2:
            continue
        tool_lower = tool.lower()
        if tool_lower in seen_tech or tool_lower in seen_tools:
            continue
        seen_tools.add(tool_lower)
        categories["technical_expertise"].append(_make_topic(
            topic=tool,
            brief=f"CLI tool: {tool}",
            confidence=_frequency_confidence(count),
            mention_count=count,
            first_seen=first,
            last_seen=last,
        ))

    return {
        "schema_version": "4.0",
        "meta": {
            "generated_at": now,
            "method": "coding_session_extraction_v1",
            "features": ["behavioral_extraction", "coding_session"],
            "source_tool": session.tool,
            "session_id": session.session_id,
            "model": session.model,
        },
        "categories": dict(categories),
    }


def _make_topic(
    topic: str,
    brief: str,
    confidence: float = 0.5,
    full_description: str = "",
    mention_count: int = 1,
    metrics: list[str] | None = None,
    first_seen: str = "",
    last_seen: str = "",
) -> dict:
    """Build a v4-compatible topic dict with behavioral extraction method."""
    return {
        "topic": topic,
        "brief": brief,
        "full_description": full_description,
        "confidence": confidence,
        "mention_count": mention_count,
        "extraction_method": "behavioral",
        "metrics": metrics or [],
        "relationships": [],
        "timeline": ["current"],
        "source_quotes": [],
        "first_seen": first_seen,
        "last_seen": last_seen,
        "relationship_type": "",
    }


def _frequency_confidence(count: int) -> float:
    """Map occurrence count to confidence score."""
    if count >= 20:
        return 0.90
    if count >= 10:
        return 0.85
    if count >= 5:
        return 0.75
    if count >= 3:
        return 0.65
    return 0.50


# ---------------------------------------------------------------------------
# Multi-session aggregation
# ---------------------------------------------------------------------------

def aggregate_sessions(sessions: list[CodingSession]) -> CodingSession:
    """Merge multiple CodingSessions into one aggregated session."""
    agg = CodingSession(tool="aggregate")

    for s in sessions:
        agg.files_touched += s.files_touched
        agg.file_extensions += s.file_extensions
        agg.tool_usage += s.tool_usage
        agg.bash_commands.extend(s.bash_commands)
        agg.bash_tools += s.bash_tools
        agg.user_prompts.extend(s.user_prompts)
        agg.technologies += s.technologies
        agg.config_files.extend(
            f for f in s.config_files if f not in agg.config_files
        )
        agg.branches.update(s.branches)
        agg.test_files_written += s.test_files_written
        agg.impl_files_written += s.impl_files_written
        agg.total_edits += s.total_edits
        agg.total_reads += s.total_reads
        agg.total_writes += s.total_writes
        agg.error_count += s.error_count
        agg.plan_mode_used = agg.plan_mode_used or s.plan_mode_used

        if s.start_time:
            if agg.start_time is None or s.start_time < agg.start_time:
                agg.start_time = s.start_time
        if s.end_time:
            if agg.end_time is None or s.end_time > agg.end_time:
                agg.end_time = s.end_time
        if s.project_path and not agg.project_path:
            agg.project_path = s.project_path

        # Keep richest project metadata
        if s.project_meta.enriched and not agg.project_meta.enriched:
            agg.project_meta = s.project_meta
        elif (
            s.project_meta.enriched
            and agg.project_meta.enriched
            and len(s.project_meta.description) > len(agg.project_meta.description)
        ):
            agg.project_meta = s.project_meta

    return agg


# ---------------------------------------------------------------------------
# Session discovery
# ---------------------------------------------------------------------------

def discover_claude_code_sessions(
    project_filter: str | None = None,
    limit: int = 0,
) -> list[Path]:
    """Find Claude Code session JSONL files on this machine.

    Scans ~/.claude/projects/ for *.jsonl files.
    Optional project_filter: substring match on path.
    """
    claude_dir = Path.home() / ".claude" / "projects"
    if not claude_dir.exists():
        return []

    sessions: list[tuple[Path, float]] = []
    for jsonl_path in claude_dir.rglob("*.jsonl"):
        if project_filter and project_filter not in str(jsonl_path):
            continue
        try:
            mtime = jsonl_path.stat().st_mtime
            sessions.append((jsonl_path, mtime))
        except OSError:
            continue

    # Sort by modification time (newest first)
    sessions.sort(key=lambda x: x[1], reverse=True)

    paths = [p for p, _ in sessions]
    if limit > 0:
        paths = paths[:limit]
    return paths


def load_claude_code_session(path: Path) -> list[dict]:
    """Load JSONL records from a Claude Code session file."""
    records: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records
