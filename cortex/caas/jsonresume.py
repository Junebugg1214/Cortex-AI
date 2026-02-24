"""
JSON Resume Export — Map a Cortex graph to JSON Resume v1.0.0 schema.

See https://jsonresume.org/schema for the specification.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cortex.graph import CortexGraph


# ---------------------------------------------------------------------------
# Confidence → skill level mapping
# ---------------------------------------------------------------------------

def _confidence_to_level(confidence: float) -> str:
    """Map a 0.0-1.0 confidence score to a JSON Resume skill level."""
    if confidence < 0.4:
        return "Beginner"
    elif confidence < 0.6:
        return "Intermediate"
    elif confidence < 0.8:
        return "Advanced"
    return "Expert"


# ---------------------------------------------------------------------------
# Section mappers
# ---------------------------------------------------------------------------

def _map_basics(graph: CortexGraph) -> dict[str, Any]:
    """Extract basics (name, headline, email, profiles) from identity nodes."""
    basics: dict[str, Any] = {}

    for node in graph.nodes.values():
        if "identity" not in node.tags:
            continue
        # Name: use the label of the identity node
        if not basics.get("name"):
            basics["name"] = node.label
        # Email from properties
        if not basics.get("email") and node.properties.get("email"):
            basics["email"] = node.properties["email"]
        # Phone
        if not basics.get("phone") and node.properties.get("phone"):
            basics["phone"] = node.properties["phone"]
        # URL
        if not basics.get("url") and node.properties.get("url"):
            basics["url"] = node.properties["url"]
        # Location
        if not basics.get("location") and node.properties.get("location"):
            basics["location"] = {"address": node.properties["location"]}

    # Headline from professional_context
    for node in graph.nodes.values():
        if "professional_context" not in node.tags:
            continue
        if not basics.get("summary") and node.brief:
            # Use the first professional_context brief that looks like a headline
            if "headline" in node.brief.lower() or len(node.brief) < 200:
                basics["summary"] = node.brief
                break

    # Profiles from properties
    profiles: list[dict] = []
    for node in graph.nodes.values():
        url = node.properties.get("linkedin_url", "") or node.properties.get("url", "")
        if url and "linkedin.com" in url:
            profiles.append({"network": "LinkedIn", "url": url})
        gh_url = node.properties.get("github_url", "")
        if gh_url:
            profiles.append({"network": "GitHub", "url": gh_url})
    if profiles:
        basics["profiles"] = profiles

    return basics


def _map_work(graph: CortexGraph) -> list[dict]:
    """Map work_history nodes to JSON Resume work[] entries."""
    entries: list[dict] = []

    work_nodes = [n for n in graph.nodes.values() if "work_history" in n.tags]
    # Sort by start_date descending
    work_nodes.sort(key=lambda n: n.properties.get("start_date", ""), reverse=True)

    for node in work_nodes:
        p = node.properties
        entry: dict[str, Any] = {
            "name": p.get("employer", ""),
            "position": p.get("role", ""),
            "startDate": p.get("start_date", ""),
        }
        end = p.get("end_date", "")
        if end:
            entry["endDate"] = end
        if p.get("description"):
            entry["summary"] = p["description"]
        if p.get("location"):
            entry["location"] = p["location"]
        achievements = p.get("achievements", [])
        if achievements:
            entry["highlights"] = list(achievements)
        entries.append(entry)

    return entries


def _map_education(graph: CortexGraph) -> list[dict]:
    """Map education_history nodes to JSON Resume education[] entries."""
    entries: list[dict] = []

    edu_nodes = [n for n in graph.nodes.values() if "education_history" in n.tags]
    edu_nodes.sort(key=lambda n: n.properties.get("start_date", ""), reverse=True)

    for node in edu_nodes:
        p = node.properties
        entry: dict[str, Any] = {
            "institution": p.get("institution", ""),
            "area": p.get("field_of_study", ""),
            "studyType": p.get("degree", ""),
        }
        start = p.get("start_date", "")
        if start:
            entry["startDate"] = start
        end = p.get("end_date", "")
        if end:
            entry["endDate"] = end
        if p.get("gpa"):
            entry["score"] = p["gpa"]
        courses = p.get("courses", [])
        if courses:
            entry["courses"] = list(courses)
        entries.append(entry)

    return entries


def _map_skills(graph: CortexGraph) -> list[dict]:
    """Map technical_expertise nodes to JSON Resume skills[]."""
    entries: list[dict] = []
    for node in graph.nodes.values():
        if "technical_expertise" not in node.tags:
            continue
        entry: dict[str, Any] = {
            "name": node.label,
            "level": _confidence_to_level(node.confidence),
        }
        entries.append(entry)
    # Sort by confidence desc
    entries.sort(key=lambda e: {"Expert": 4, "Advanced": 3, "Intermediate": 2, "Beginner": 1}.get(e["level"], 0), reverse=True)
    return entries


def _map_languages(graph: CortexGraph) -> list[dict]:
    """Map communication_preferences nodes that are spoken languages."""
    entries: list[dict] = []
    for node in graph.nodes.values():
        if "communication_preferences" not in node.tags:
            continue
        if node.brief and "spoken language" in node.brief.lower():
            entries.append({
                "language": node.label,
                "fluency": "Native speaker" if node.confidence >= 0.9 else "Fluent",
            })
    return entries


def _map_certificates(graph: CortexGraph) -> list[dict]:
    """Map professional_context nodes that are certifications."""
    entries: list[dict] = []
    for node in graph.nodes.values():
        if "professional_context" not in node.tags:
            continue
        if node.brief and "certification" in node.brief.lower():
            entries.append({"name": node.label})
    return entries


def _map_projects(graph: CortexGraph) -> list[dict]:
    """Map active_priorities nodes to JSON Resume projects[]."""
    entries: list[dict] = []
    for node in graph.nodes.values():
        if "active_priorities" not in node.tags:
            continue
        entry: dict[str, Any] = {"name": node.label}
        if node.brief:
            entry["description"] = node.brief
        url = node.properties.get("url", "")
        if url:
            entry["url"] = url
        entries.append(entry)
    return entries


def _map_references(credential_store: Any | None) -> list[dict]:
    """Map ReferenceAttestation credentials to JSON Resume references[]."""
    if credential_store is None:
        return []
    entries: list[dict] = []
    for cred in credential_store.list_all():
        if "ReferenceAttestation" not in cred.credential_type:
            continue
        if cred.status != "active":
            continue
        ref: dict[str, Any] = {}
        # Attestor name from claims
        name = cred.claims.get("attestor_name", cred.issuer_did)
        ref["name"] = name
        text = cred.claims.get("reference_text", "")
        if text:
            ref["reference"] = text
        entries.append(ref)
    return entries


# ---------------------------------------------------------------------------
# Main export function
# ---------------------------------------------------------------------------

def graph_to_jsonresume(
    graph: CortexGraph,
    credential_store: Any | None = None,
) -> dict[str, Any]:
    """Convert a Cortex graph to a JSON Resume v1.0.0 dict.

    Handles sparse data gracefully — missing sections are omitted.
    """
    resume: dict[str, Any] = {}

    basics = _map_basics(graph)
    if basics:
        resume["basics"] = basics

    work = _map_work(graph)
    if work:
        resume["work"] = work

    education = _map_education(graph)
    if education:
        resume["education"] = education

    skills = _map_skills(graph)
    if skills:
        resume["skills"] = skills

    languages = _map_languages(graph)
    if languages:
        resume["languages"] = languages

    certificates = _map_certificates(graph)
    if certificates:
        resume["certificates"] = certificates

    projects = _map_projects(graph)
    if projects:
        resume["projects"] = projects

    references = _map_references(credential_store)
    if references:
        resume["references"] = references

    return resume
