from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from cortex.coding import enrich_project
from cortex.graph.graph import CortexGraph, Node, make_node_id_with_tag
from cortex.portability.portable_graphs import extract_graph_from_statement, merge_graphs

FRAMEWORK_LABELS = {
    "next": "Next.js",
    "react": "React",
    "tailwindcss": "Tailwind CSS",
    "prisma": "Prisma",
    "@trpc/server": "tRPC",
    "@trpc/client": "tRPC",
    "vitest": "Vitest",
    "jest": "Jest",
    "vite": "Vite",
    "fastapi": "FastAPI",
    "uvicorn": "Uvicorn",
    "django": "Django",
    "flask": "Flask",
    "sqlalchemy": "SQLAlchemy",
    "pydantic": "Pydantic",
    "tokio": "Tokio",
    "axum": "Axum",
    "serde": "Serde",
    "sqlx": "SQLx",
    "docker": "Docker",
}


def _package_dependencies(data: dict[str, Any]) -> dict[str, str]:
    dependencies: dict[str, str] = {}
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        block = data.get(key, {})
        if not isinstance(block, dict):
            continue
        for name, version in block.items():
            dependencies[str(name)] = str(version)
    return dependencies


def _manifest_signals(project_dir: Path) -> tuple[list[str], dict[str, str], list[str]]:
    labels: list[str] = []
    versions: dict[str, str] = {}
    notes: list[str] = []

    package_json = project_dir / "package.json"
    if package_json.exists():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            dependencies = _package_dependencies(data)
            for dep, version in dependencies.items():
                label = FRAMEWORK_LABELS.get(dep)
                if label is None:
                    continue
                labels.append(label)
                versions[label] = version
            if dependencies:
                notes.append("package.json")

    pyproject = project_dir / "pyproject.toml"
    if pyproject.exists():
        try:
            text = pyproject.read_text(encoding="utf-8")
        except OSError:
            text = ""
        for dep, label in FRAMEWORK_LABELS.items():
            if dep.lower() in text.lower():
                labels.append(label)
                versions.setdefault(label, "")
        if text:
            notes.append("pyproject.toml")

    cargo = project_dir / "Cargo.toml"
    if cargo.exists():
        try:
            text = cargo.read_text(encoding="utf-8")
        except OSError:
            text = ""
        for dep, label in FRAMEWORK_LABELS.items():
            if dep.lower() in text.lower():
                labels.append(label)
                versions.setdefault(label, "")
        if text:
            notes.append("Cargo.toml")

    if (project_dir / ".github" / "workflows").is_dir():
        labels.append("GitHub Actions")
    if (project_dir / "Dockerfile").exists() or (project_dir / "docker-compose.yml").exists():
        labels.append("Docker")

    deduped: list[str] = []
    seen: set[str] = set()
    for label in labels:
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(label)
    return deduped, versions, notes


def build_project_graph(project_dir: Path) -> tuple[CortexGraph, dict[str, Any]]:
    graph = CortexGraph()
    metadata = enrich_project(str(project_dir))
    repo_name = metadata.name or project_dir.name
    detected_labels, versions, notes = _manifest_signals(project_dir)

    summary: dict[str, Any] = {
        "project": repo_name,
        "languages": list(metadata.languages),
        "frameworks": list(detected_labels),
        "notes": list(notes),
    }

    graph.add_node(
        Node(
            id=make_node_id_with_tag(repo_name, "active_priorities"),
            label=repo_name,
            tags=["active_priorities"],
            confidence=0.9,
            brief=f"Active project: {repo_name}" + (f" - {metadata.description}" if metadata.description else ""),
            full_description=metadata.readme_summary or metadata.description,
            provenance=[{"source": str(project_dir), "method": "project_metadata"}],
        )
    )

    for language in metadata.languages:
        graph.add_node(
            Node(
                id=make_node_id_with_tag(language, "technical_expertise"),
                label=language,
                tags=["technical_expertise"],
                confidence=0.86,
                brief=f"Uses {language}",
                provenance=[{"source": str(project_dir), "method": "project_manifest"}],
            )
        )

    for label in detected_labels:
        version = versions.get(label, "")
        brief = f"{label} {version}".strip()
        graph.add_node(
            Node(
                id=make_node_id_with_tag(label, "technical_expertise"),
                label=label,
                tags=["technical_expertise"],
                confidence=0.88,
                brief=brief,
                provenance=[{"source": str(project_dir), "method": "project_manifest"}],
            )
        )

    if metadata.description:
        graph.add_node(
            Node(
                id=make_node_id_with_tag(f"{repo_name} purpose", "domain_knowledge"),
                label=f"{repo_name} purpose",
                tags=["domain_knowledge"],
                confidence=0.8,
                brief=metadata.description[:220],
                full_description=metadata.readme_summary or metadata.description,
                provenance=[{"source": str(project_dir), "method": "readme"}],
            )
        )

    return graph, summary


def _extract_resume_text(path: Path) -> str:
    if path.suffix.lower() in {".txt", ".md", ".markdown", ".rst"}:
        return path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return json.dumps(payload, indent=2)
        return str(payload)
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            return path.read_bytes().decode("utf-8", errors="ignore")
    return path.read_text(encoding="utf-8", errors="replace")


def build_resume_graph(path: Path) -> tuple[CortexGraph, dict[str, Any]]:
    text = _extract_resume_text(path)
    graph = extract_graph_from_statement(text, confidence=0.82)
    summary = {"source": str(path), "chars": len(text)}
    return graph, summary


def _git(args: list[str], *, cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _find_git_repos(search_roots: list[Path]) -> list[Path]:
    repos: list[Path] = []
    seen: set[str] = set()
    for root in search_roots:
        root = root.resolve()
        if (root / ".git").exists():
            key = str(root)
            if key not in seen:
                seen.add(key)
                repos.append(root)
        for git_dir in root.glob("*/.git"):
            repo = git_dir.parent.resolve()
            key = str(repo)
            if key not in seen:
                seen.add(key)
                repos.append(repo)
    return repos


def build_github_graph(search_roots: list[Path]) -> tuple[CortexGraph, dict[str, Any]]:
    graph = CortexGraph()
    repos = _find_git_repos(search_roots)
    repo_summaries: list[dict[str, Any]] = []

    for repo in repos:
        remote = _git(["remote", "get-url", "origin"], cwd=repo)
        if remote and "github.com" not in remote:
            continue
        repo_graph, summary = build_project_graph(repo)
        graph = merge_graphs(graph, repo_graph)
        repo_summaries.append(summary)

    all_languages = sorted({lang for summary in repo_summaries for lang in summary.get("languages", [])})
    all_frameworks = sorted({label for summary in repo_summaries for label in summary.get("frameworks", [])})
    summary = {
        "repo_count": len(repo_summaries),
        "languages": all_languages,
        "frameworks": all_frameworks,
        "repos": [summary.get("project", "") for summary in repo_summaries],
    }
    return graph, summary


def build_git_history_graph(project_dir: Path) -> tuple[CortexGraph, dict[str, Any]]:
    graph = CortexGraph()
    log_output = _git(["log", "--pretty=format:%H%x1f%s%x1f%ad", "--date=iso", "-n", "200"], cwd=project_dir)
    summary = {
        "commit_count": 0,
        "active_hours": [],
        "patterns": [],
    }
    if not log_output:
        return graph, summary

    lines = [line for line in log_output.splitlines() if line.strip()]
    summary["commit_count"] = len(lines)
    hour_counts: dict[int, int] = {}
    conventional = 0
    test_commits = 0
    descriptive = 0

    for line in lines:
        parts = line.split("\x1f")
        if len(parts) != 3:
            continue
        _, subject, timestamp = parts
        if re.match(r"^(feat|fix|docs|refactor|test|chore|ci|build)(\(.+\))?:", subject.strip().lower()):
            conventional += 1
        if re.search(r"\b(test|pytest|vitest|jest)\b", subject, re.IGNORECASE):
            test_commits += 1
        if len(subject.split()) >= 5:
            descriptive += 1
        try:
            parsed = datetime.fromisoformat(timestamp.strip())
            hour_counts[parsed.hour] = hour_counts.get(parsed.hour, 0) + 1
        except ValueError:
            continue

    active_hours = [hour for hour, _ in sorted(hour_counts.items(), key=lambda item: (-item[1], item[0]))[:3]]
    summary["active_hours"] = active_hours

    if conventional >= max(5, len(lines) // 4):
        summary["patterns"].append("Conventional commits")
        graph.add_node(
            Node(
                id=make_node_id_with_tag("Conventional commits", "user_preferences"),
                label="Conventional commits",
                tags=["user_preferences"],
                confidence=0.76,
                brief="Commit messages usually follow conventional commit prefixes",
                provenance=[{"source": str(project_dir), "method": "git_history"}],
            )
        )
    if test_commits >= max(3, len(lines) // 8):
        summary["patterns"].append("Testing-focused workflow")
        graph.add_node(
            Node(
                id=make_node_id_with_tag("Testing-focused workflow", "user_preferences"),
                label="Testing-focused workflow",
                tags=["user_preferences"],
                confidence=0.72,
                brief="Git history frequently references tests and verification",
                provenance=[{"source": str(project_dir), "method": "git_history"}],
            )
        )
    if descriptive >= max(5, len(lines) // 3):
        summary["patterns"].append("Descriptive commit style")
        graph.add_node(
            Node(
                id=make_node_id_with_tag("Descriptive commit style", "communication_preferences"),
                label="Descriptive commit style",
                tags=["communication_preferences"],
                confidence=0.68,
                brief="Commit messages are usually sentence-like and descriptive",
                provenance=[{"source": str(project_dir), "method": "git_history"}],
            )
        )

    if active_hours:
        hours_label = ", ".join(f"{hour:02d}:00" for hour in active_hours)
        graph.add_node(
            Node(
                id=make_node_id_with_tag("Peak coding hours", "user_preferences"),
                label="Peak coding hours",
                tags=["user_preferences"],
                confidence=0.65,
                brief=f"Most active commit hours: {hours_label}",
                provenance=[{"source": str(project_dir), "method": "git_history"}],
            )
        )

    return graph, summary


__all__ = [
    "build_git_history_graph",
    "build_github_graph",
    "build_project_graph",
    "build_resume_graph",
]
