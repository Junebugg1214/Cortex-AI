"""
Professional Timeline — Structured work and education history nodes.

Provides dataclasses, validation, and graph helpers for work_history
and education_history node types with dates, employers, achievements,
and optional cryptographic attestation binding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from cortex.graph import CortexGraph, Node, make_node_id_with_tag

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EMPLOYMENT_TYPES = {"full-time", "part-time", "contract", "internship", "freelance"}

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class WorkHistoryEntry:
    """Structured work history entry."""

    employer: str
    role: str
    start_date: str            # ISO date YYYY-MM-DD
    end_date: str = ""         # ISO date or "" (current)
    location: str = ""
    description: str = ""
    achievements: list[str] = field(default_factory=list)
    employment_type: str = "full-time"

    @property
    def current(self) -> bool:
        return self.end_date == ""

    def to_properties(self) -> dict[str, Any]:
        return {
            "employer": self.employer,
            "role": self.role,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "current": self.current,
            "location": self.location,
            "description": self.description,
            "achievements": list(self.achievements),
            "employment_type": self.employment_type,
        }

    @classmethod
    def from_properties(cls, props: dict) -> WorkHistoryEntry:
        return cls(
            employer=props.get("employer", ""),
            role=props.get("role", ""),
            start_date=props.get("start_date", ""),
            end_date=props.get("end_date", ""),
            location=props.get("location", ""),
            description=props.get("description", ""),
            achievements=list(props.get("achievements", [])),
            employment_type=props.get("employment_type", "full-time"),
        )


@dataclass
class EducationHistoryEntry:
    """Structured education history entry."""

    institution: str
    degree: str
    field_of_study: str = ""
    start_date: str = ""       # ISO date YYYY-MM-DD
    end_date: str = ""         # ISO date or ""
    gpa: str = ""
    achievements: list[str] = field(default_factory=list)
    courses: list[str] = field(default_factory=list)

    @property
    def current(self) -> bool:
        return self.end_date == ""

    def to_properties(self) -> dict[str, Any]:
        return {
            "institution": self.institution,
            "degree": self.degree,
            "field_of_study": self.field_of_study,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "current": self.current,
            "gpa": self.gpa,
            "achievements": list(self.achievements),
            "courses": list(self.courses),
        }

    @classmethod
    def from_properties(cls, props: dict) -> EducationHistoryEntry:
        return cls(
            institution=props.get("institution", ""),
            degree=props.get("degree", ""),
            field_of_study=props.get("field_of_study", ""),
            start_date=props.get("start_date", ""),
            end_date=props.get("end_date", ""),
            gpa=props.get("gpa", ""),
            achievements=list(props.get("achievements", [])),
            courses=list(props.get("courses", [])),
        )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_work_history_properties(props: dict) -> list[str]:
    """Validate work history properties. Returns list of error strings."""
    errors: list[str] = []

    # Required fields
    for req in ("employer", "role", "start_date"):
        val = props.get(req, "")
        if not val or not str(val).strip():
            errors.append(f"missing required field: {req}")

    # Date format
    start = props.get("start_date", "")
    if start and not _ISO_DATE_RE.match(start):
        errors.append(f"invalid start_date format: {start!r} (expected YYYY-MM-DD)")

    end = props.get("end_date", "")
    if end and not _ISO_DATE_RE.match(end):
        errors.append(f"invalid end_date format: {end!r} (expected YYYY-MM-DD)")

    # Date logic: end >= start
    if start and end and _ISO_DATE_RE.match(start) and _ISO_DATE_RE.match(end):
        if end < start:
            errors.append("end_date cannot be before start_date")

    # Employment type
    emp_type = props.get("employment_type", "full-time")
    if emp_type and emp_type not in EMPLOYMENT_TYPES:
        errors.append(
            f"invalid employment_type: {emp_type!r} "
            f"(expected one of: {', '.join(sorted(EMPLOYMENT_TYPES))})"
        )

    return errors


def validate_education_properties(props: dict) -> list[str]:
    """Validate education history properties. Returns list of error strings."""
    errors: list[str] = []

    # Required fields
    for req in ("institution", "degree"):
        val = props.get(req, "")
        if not val or not str(val).strip():
            errors.append(f"missing required field: {req}")

    # Date format
    start = props.get("start_date", "")
    if start and not _ISO_DATE_RE.match(start):
        errors.append(f"invalid start_date format: {start!r} (expected YYYY-MM-DD)")

    end = props.get("end_date", "")
    if end and not _ISO_DATE_RE.match(end):
        errors.append(f"invalid end_date format: {end!r} (expected YYYY-MM-DD)")

    if start and end and _ISO_DATE_RE.match(start) and _ISO_DATE_RE.match(end):
        if end < start:
            errors.append("end_date cannot be before start_date")

    return errors


# ---------------------------------------------------------------------------
# Node creation
# ---------------------------------------------------------------------------

def create_work_history_node(entry: WorkHistoryEntry) -> Node:
    """Create a graph Node from a WorkHistoryEntry."""
    label = f"{entry.role} at {entry.employer}"
    node_id = make_node_id_with_tag(label, "work_history")
    now = datetime.now(timezone.utc).isoformat()
    return Node(
        id=node_id,
        label=label,
        tags=["work_history"],
        confidence=0.95,
        properties=entry.to_properties(),
        brief=f"{entry.role} at {entry.employer}" + (
            f" ({entry.start_date} - {'present' if entry.current else entry.end_date})"
            if entry.start_date else ""
        ),
        first_seen=now,
        last_seen=now,
    )


def create_education_node(entry: EducationHistoryEntry) -> Node:
    """Create a graph Node from an EducationHistoryEntry."""
    label = f"{entry.degree} at {entry.institution}"
    node_id = make_node_id_with_tag(label, "education_history")
    now = datetime.now(timezone.utc).isoformat()
    return Node(
        id=node_id,
        label=label,
        tags=["education_history"],
        confidence=0.95,
        properties=entry.to_properties(),
        brief=f"{entry.degree} at {entry.institution}" + (
            f" ({entry.start_date} - {'present' if entry.current else entry.end_date})"
            if entry.start_date else ""
        ),
        first_seen=now,
        last_seen=now,
    )


# ---------------------------------------------------------------------------
# Timeline helpers
# ---------------------------------------------------------------------------

def get_timeline(graph: CortexGraph) -> list[Node]:
    """Get all timeline entries (work + education) sorted by start_date descending."""
    entries: list[Node] = []
    for node in graph.nodes.values():
        if "work_history" in node.tags or "education_history" in node.tags:
            entries.append(node)

    def _sort_key(n: Node) -> str:
        sd = n.properties.get("start_date", "")
        return sd if sd else "0000-00-00"

    entries.sort(key=_sort_key, reverse=True)
    return entries
