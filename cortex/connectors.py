"""
Lightweight local ingestion connectors for GitHub, Slack, and docs.

These normalize exported files/directories into plain text so they can flow
through the existing Cortex extraction pipeline.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_timestamp(value: str) -> str:
    if not value:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        if "." in text and text.replace(".", "", 1).isdigit():
            timestamp = datetime.fromtimestamp(float(text), tz=timezone.utc)
            return timestamp.isoformat().replace("+00:00", "Z")
        timestamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        else:
            timestamp = timestamp.astimezone(timezone.utc)
        return timestamp.isoformat().replace("+00:00", "Z")
    except ValueError:
        return text


def _iter_github_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        if isinstance(data.get("items"), list):
            return [item for item in data["items"] if isinstance(item, dict)]
        if isinstance(data.get("nodes"), list):
            return [item for item in data["nodes"] if isinstance(item, dict)]
        return [data]
    return []


def _normalize_comment_blocks(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        if isinstance(value.get("nodes"), list):
            return [item for item in value["nodes"] if isinstance(item, dict)]
        if isinstance(value.get("comments"), list):
            return [item for item in value["comments"] if isinstance(item, dict)]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def github_export_to_text(input_path: Path) -> str:
    data = _load_json(input_path)
    items = _iter_github_items(data)
    lines: list[str] = []
    for item in items:
        item_type = "pull request" if "reviewDecision" in item or "merged" in item else "issue"
        repo = item.get("repository", {}).get("nameWithOwner") or item.get("repository", "") or ""
        number = item.get("number", "")
        title = item.get("title", "")
        state = item.get("state", "")
        author = item.get("author", {}).get("login") if isinstance(item.get("author"), dict) else item.get("author", "")
        labels_raw = item.get("labels", {})
        if isinstance(labels_raw, dict):
            labels = [node.get("name", "") for node in labels_raw.get("nodes", []) if isinstance(node, dict)]
        elif isinstance(labels_raw, list):
            labels = [node.get("name", "") if isinstance(node, dict) else str(node) for node in labels_raw]
        else:
            labels = []
        body = item.get("body", "") or item.get("bodyText", "") or ""
        lines.extend(
            [
                f"# GitHub {item_type.title()}",
                f"Repository: {repo or '-'}",
                f"Number: {number or '-'}",
                f"Title: {title or '-'}",
                f"State: {state or '-'}",
                f"Author: {author or '-'}",
                f"Labels: {', '.join(label for label in labels if label) or '-'}",
                "",
                body.strip(),
                "",
            ]
        )
        for comment in _normalize_comment_blocks(item.get("comments")):
            comment_author = (
                comment.get("author", {}).get("login")
                if isinstance(comment.get("author"), dict)
                else comment.get("user", "")
            )
            lines.append(
                f"Comment by {comment_author or '-'}: {comment.get('body', '') or comment.get('bodyText', '')}"
            )
        for review in _normalize_comment_blocks(item.get("reviews")):
            review_author = (
                review.get("author", {}).get("login")
                if isinstance(review.get("author"), dict)
                else review.get("user", "")
            )
            review_state = review.get("state", "")
            lines.append(
                f"Review by {review_author or '-'} [{review_state or '-'}]: {review.get('body', '') or review.get('bodyText', '')}"
            )
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _iter_slack_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    return [
        path
        for path in sorted(input_path.rglob("*.json"))
        if path.name not in {"users.json", "channels.json", "groups.json", "dms.json", "mpims.json"}
    ]


def slack_export_to_text(input_path: Path) -> str:
    lines: list[str] = []
    for path in _iter_slack_files(input_path):
        data = _load_json(path)
        if not isinstance(data, list):
            continue
        channel = path.parent.name if path.parent != input_path else path.stem
        lines.append(f"# Slack Channel: {channel}")
        for message in data:
            if not isinstance(message, dict):
                continue
            user = (
                (
                    message.get("user_profile", {}).get("real_name")
                    if isinstance(message.get("user_profile"), dict)
                    else message.get("username")
                )
                or message.get("user")
                or "unknown"
            )
            ts = _normalize_timestamp(str(message.get("ts", "")))
            text = str(message.get("text", "")).strip()
            subtype = str(message.get("subtype", "")).strip()
            prefix = f"[{ts}] {user}"
            if subtype:
                prefix += f" ({subtype})"
            lines.append(f"{prefix}: {text}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def docs_to_text(input_path: Path) -> str:
    if input_path.is_file():
        paths = [input_path]
        root = input_path.parent
    else:
        paths = sorted(
            path for path in input_path.rglob("*") if path.is_file() and path.suffix.lower() in {".md", ".txt", ".rst"}
        )
        root = input_path
    lines: list[str] = []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        lines.extend([f"# Document: {relative}", "", path.read_text(encoding="utf-8"), ""])
    return "\n".join(lines).strip() + "\n"


def connector_to_text(kind: str, input_path: Path) -> str:
    if kind == "github":
        return github_export_to_text(input_path)
    if kind == "slack":
        return slack_export_to_text(input_path)
    if kind == "docs":
        return docs_to_text(input_path)
    raise ValueError(f"Unsupported connector kind: {kind}")
