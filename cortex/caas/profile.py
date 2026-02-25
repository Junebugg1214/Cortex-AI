"""
Public Profile Page — Server-rendered HTML profile from the disclosed graph.

Provides:
- ProfileConfig dataclass with handle, sections, and disclosure policy
- ProfileStore for CRUD + persistence (JSON-backed, same pattern as ApiKeyStore)
- render_profile_html() for server-rendered HTML with inline CSS
- render_profile_jsonld() for schema.org/Person structured data
"""

from __future__ import annotations

import html
import json
import re
import threading
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cortex.graph import CortexGraph
    from cortex.upai.credentials import CredentialStore

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HANDLE_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{2,63}$")

RESERVED_HANDLES = frozenset({
    "admin", "api", "app", "dashboard", "health", "p", "static", "docs",
    "login", "logout", "settings", "profile",
})

DEFAULT_SECTIONS = [
    "about", "experience", "skills", "education", "projects", "endorsements",
]


# ---------------------------------------------------------------------------
# ProfileConfig
# ---------------------------------------------------------------------------

@dataclass
class ProfileConfig:
    """Public profile configuration."""

    handle: str
    display_name: str = ""
    headline: str = ""
    bio: str = ""
    avatar_url: str = ""
    policy: str = "professional"
    sections: list[str] = field(default_factory=lambda: list(DEFAULT_SECTIONS))
    custom_tags: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "handle": self.handle,
            "display_name": self.display_name,
            "headline": self.headline,
            "bio": self.bio,
            "avatar_url": self.avatar_url,
            "policy": self.policy,
            "sections": list(self.sections),
            "custom_tags": list(self.custom_tags),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ProfileConfig:
        return cls(
            handle=d.get("handle", ""),
            display_name=d.get("display_name", ""),
            headline=d.get("headline", ""),
            bio=d.get("bio", ""),
            avatar_url=d.get("avatar_url", ""),
            policy=d.get("policy", "professional"),
            sections=list(d.get("sections", DEFAULT_SECTIONS)),
            custom_tags=list(d.get("custom_tags", [])),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
        )


# ---------------------------------------------------------------------------
# Handle validation
# ---------------------------------------------------------------------------

def validate_handle(handle: str) -> list[str]:
    """Validate a profile handle. Returns list of error strings."""
    errors: list[str] = []
    if not handle:
        errors.append("handle is required")
        return errors
    if not _HANDLE_RE.match(handle):
        errors.append(
            "handle must be 3-64 chars, lowercase alphanumeric + hyphens, "
            "starting with alphanumeric"
        )
    if handle in RESERVED_HANDLES:
        errors.append(f"handle '{handle}' is reserved")
    return errors


def _slugify_handle(name: str) -> str:
    """Convert a display name into a valid profile handle.

    Normalizes unicode, lowercases, replaces non-alphanumeric chars with
    hyphens, collapses/strips hyphens, and enforces 3-64 char range.
    """
    slug = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = slug.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if len(slug) < 3:
        slug = (slug + "-profile")[:64]
    return slug[:64]


def auto_populate_profile(graph: CortexGraph) -> ProfileConfig:
    """Derive a ProfileConfig from graph data without side effects.

    Inspects identity and professional_context nodes to pre-fill
    display_name, handle, headline, bio, and avatar_url.
    """
    display_name = ""
    bio = ""
    avatar_url = ""

    # Extract from the first identity node
    for node in graph.nodes.values():
        if "identity" not in node.tags:
            continue
        if not display_name and node.label:
            display_name = node.label
        if not bio and node.brief:
            bio = node.brief
        if not avatar_url:
            avatar_url = node.properties.get("avatar_url", "")
        break  # use only the first identity node

    # Derive handle
    handle = _slugify_handle(display_name) if display_name else "my-profile"
    if handle in RESERVED_HANDLES:
        handle = handle + "-profile"

    # Extract headline from professional_context nodes
    headline = ""
    long_bio = ""
    for node in graph.nodes.values():
        if "professional_context" not in node.tags:
            continue
        if not headline and node.label and len(node.label) < 120:
            headline = node.label
        if not long_bio and node.brief and len(node.brief) >= 120:
            long_bio = node.brief[:500]

    # Fall back: use a long professional_context brief as bio if identity had none
    if not bio and long_bio:
        bio = long_bio

    return ProfileConfig(
        handle=handle,
        display_name=display_name,
        headline=headline,
        bio=bio,
        avatar_url=avatar_url,
        policy="professional",
        sections=list(DEFAULT_SECTIONS),
    )


# ---------------------------------------------------------------------------
# ProfileStore
# ---------------------------------------------------------------------------

class ProfileStore:
    """File-backed JSON store for profile configurations."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else None
        self._profiles: dict[str, ProfileConfig] = {}
        self._lock = threading.Lock()
        if self._path and self._path.exists():
            self._load()

    def _load(self) -> None:
        if self._path is None:
            return
        try:
            data = json.loads(self._path.read_text())
            for d in data.get("profiles", []):
                config = ProfileConfig.from_dict(d)
                self._profiles[config.handle] = config
        except (json.JSONDecodeError, OSError):
            pass

    def _save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {"profiles": [p.to_dict() for p in self._profiles.values()]}
        self._path.write_text(json.dumps(data, indent=2))

    def get(self, handle: str) -> ProfileConfig | None:
        with self._lock:
            return self._profiles.get(handle)

    def create(self, config: ProfileConfig) -> ProfileConfig:
        errors = validate_handle(config.handle)
        if errors:
            raise ValueError("; ".join(errors))
        with self._lock:
            if config.handle in self._profiles:
                raise ValueError(f"handle '{config.handle}' already exists")
            now = datetime.now(timezone.utc).isoformat()
            config.created_at = now
            config.updated_at = now
            self._profiles[config.handle] = config
            self._save()
        return config

    def update(self, handle: str, updates: dict) -> ProfileConfig | None:
        with self._lock:
            config = self._profiles.get(handle)
            if config is None:
                return None
            for key in ("display_name", "headline", "bio", "avatar_url",
                        "policy", "sections", "custom_tags"):
                if key in updates:
                    setattr(config, key, updates[key])
            config.updated_at = datetime.now(timezone.utc).isoformat()
            self._save()
            return config

    def delete(self, handle: str) -> bool:
        with self._lock:
            if handle not in self._profiles:
                return False
            del self._profiles[handle]
            self._save()
            return True

    def list_all(self) -> list[ProfileConfig]:
        with self._lock:
            return list(self._profiles.values())


# ---------------------------------------------------------------------------
# JSON-LD (schema.org/Person)
# ---------------------------------------------------------------------------

def render_profile_jsonld(graph: CortexGraph, config: ProfileConfig) -> dict:
    """Produce a schema.org/Person JSON-LD dict from graph + config."""
    person: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Person",
    }
    if config.display_name:
        person["name"] = config.display_name
    if config.headline:
        person["jobTitle"] = config.headline
    if config.bio:
        person["description"] = config.bio

    # Extract email/url from identity nodes
    for node in graph.nodes.values():
        if "identity" not in node.tags:
            continue
        if node.properties.get("email"):
            person["email"] = node.properties["email"]
        if node.properties.get("url"):
            person["url"] = node.properties["url"]

    return person


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def render_profile_html(
    graph: CortexGraph,
    config: ProfileConfig,
    credential_store: Any | None = None,
) -> str:
    """Render a self-contained HTML profile page.

    All dynamic content is escaped via html.escape() for XSS prevention.
    """
    e = html.escape  # shorthand

    # Collect sections
    sections_html: list[str] = []

    if "about" in config.sections:
        about = _render_about_section(graph, config, e)
        if about:
            sections_html.append(about)

    if "experience" in config.sections:
        exp = _render_experience_section(graph, e)
        if exp:
            sections_html.append(exp)

    if "skills" in config.sections:
        skills = _render_skills_section(graph, e)
        if skills:
            sections_html.append(skills)

    if "education" in config.sections:
        edu = _render_education_section(graph, e)
        if edu:
            sections_html.append(edu)

    if "projects" in config.sections:
        proj = _render_projects_section(graph, e)
        if proj:
            sections_html.append(proj)

    if "endorsements" in config.sections and credential_store is not None:
        endorse = _render_endorsements_section(credential_store, e)
        if endorse:
            sections_html.append(endorse)

    jsonld = render_profile_jsonld(graph, config)
    # Escape < and > in JSON-LD to prevent XSS inside <script> block
    jsonld_script = json.dumps(jsonld, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")

    body = "\n".join(sections_html) if sections_html else "<p>No public information available.</p>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{e(config.display_name or config.handle)} — Profile</title>
<meta property="og:title" content="{e(config.display_name or config.handle)}">
<meta property="og:description" content="{e(config.headline or '')}">
<meta property="og:type" content="profile">
<script type="application/ld+json">{jsonld_script}</script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
line-height:1.6;color:#1a1a2e;background:#f8f9fa;max-width:800px;margin:0 auto;
padding:24px 16px}}
.profile-header{{text-align:center;margin-bottom:32px}}
.profile-header h1{{font-size:28px;margin-bottom:4px}}
.profile-header .headline{{color:#6b7280;font-size:16px}}
.profile-header .bio{{margin-top:12px;color:#374151;max-width:600px;
margin-left:auto;margin-right:auto}}
.section{{margin-bottom:28px}}
.section h2{{font-size:18px;color:#4f46e5;border-bottom:2px solid #e5e7eb;
padding-bottom:6px;margin-bottom:14px}}
.entry{{margin-bottom:16px;padding-left:12px;border-left:3px solid #e5e7eb}}
.entry h3{{font-size:15px;margin-bottom:2px}}
.entry .meta{{font-size:13px;color:#6b7280}}
.entry .desc{{font-size:14px;color:#374151;margin-top:4px}}
.skill-list{{display:flex;flex-wrap:wrap;gap:8px}}
.skill-tag{{background:#eef2ff;color:#4338ca;padding:4px 12px;border-radius:12px;
font-size:13px}}
.verified{{color:#059669;font-size:12px;font-weight:600}}
.footer{{text-align:center;margin-top:40px;font-size:12px;color:#9ca3af}}
@media(max-width:600px){{body{{padding:16px 12px}}
.profile-header h1{{font-size:22px}}}}
</style>
</head>
<body>
<div class="profile-header">
<h1>{e(config.display_name or config.handle)}</h1>
{f'<div class="headline">{e(config.headline)}</div>' if config.headline else ''}
{f'<div class="bio">{e(config.bio)}</div>' if config.bio else ''}
</div>
{body}
<div class="footer">Powered by Cortex-AI</div>
</body>
</html>"""


def _render_about_section(
    graph: CortexGraph,
    config: ProfileConfig,
    e: Any,
) -> str:
    """Render About section from identity nodes."""
    items: list[str] = []
    for node in graph.nodes.values():
        if "identity" not in node.tags:
            continue
        if node.brief:
            items.append(f"<p>{e(node.brief)}</p>")
    if not items:
        return ""
    return f'<div class="section"><h2>About</h2>{"".join(items)}</div>'


def _render_experience_section(graph: CortexGraph, e: Any) -> str:
    """Render Experience section from work_history nodes."""
    nodes = [n for n in graph.nodes.values() if "work_history" in n.tags]
    nodes.sort(key=lambda n: n.properties.get("start_date", ""), reverse=True)
    if not nodes:
        return ""

    entries: list[str] = []
    for node in nodes:
        p = node.properties
        role = e(p.get("role", node.label))
        employer = e(p.get("employer", ""))
        start = p.get("start_date", "")
        end = p.get("end_date", "")
        date_str = start
        if start:
            date_str = f"{start} — {'Present' if not end else end}"
        desc = p.get("description", "")
        achievements = p.get("achievements", [])

        entry = f'<div class="entry"><h3>{role} at {employer}</h3>'
        entry += f'<div class="meta">{e(date_str)}</div>'
        if desc:
            entry += f'<div class="desc">{e(desc)}</div>'
        if achievements:
            entry += "<ul>" + "".join(f"<li>{e(a)}</li>" for a in achievements) + "</ul>"
        entry += "</div>"
        entries.append(entry)

    return f'<div class="section"><h2>Experience</h2>{"".join(entries)}</div>'


def _render_skills_section(graph: CortexGraph, e: Any) -> str:
    """Render Skills section from technical_expertise nodes."""
    nodes = [n for n in graph.nodes.values() if "technical_expertise" in n.tags]
    if not nodes:
        return ""
    nodes.sort(key=lambda n: n.confidence, reverse=True)
    tags = "".join(f'<span class="skill-tag">{e(n.label)}</span>' for n in nodes)
    return f'<div class="section"><h2>Skills</h2><div class="skill-list">{tags}</div></div>'


def _render_education_section(graph: CortexGraph, e: Any) -> str:
    """Render Education section from education_history nodes."""
    nodes = [n for n in graph.nodes.values() if "education_history" in n.tags]
    nodes.sort(key=lambda n: n.properties.get("start_date", ""), reverse=True)
    if not nodes:
        return ""

    entries: list[str] = []
    for node in nodes:
        p = node.properties
        degree = e(p.get("degree", ""))
        institution = e(p.get("institution", ""))
        start = p.get("start_date", "")
        end = p.get("end_date", "")
        date_str = f"{start} — {'Present' if not end else end}" if start else ""

        entry = f'<div class="entry"><h3>{degree} — {institution}</h3>'
        if date_str:
            entry += f'<div class="meta">{e(date_str)}</div>'
        entry += "</div>"
        entries.append(entry)

    return f'<div class="section"><h2>Education</h2>{"".join(entries)}</div>'


def _render_projects_section(graph: CortexGraph, e: Any) -> str:
    """Render Projects section from active_priorities nodes."""
    nodes = [n for n in graph.nodes.values() if "active_priorities" in n.tags]
    if not nodes:
        return ""

    entries: list[str] = []
    for node in nodes:
        entry = f'<div class="entry"><h3>{e(node.label)}</h3>'
        if node.brief:
            entry += f'<div class="desc">{e(node.brief)}</div>'
        entry += "</div>"
        entries.append(entry)

    return f'<div class="section"><h2>Projects</h2>{"".join(entries)}</div>'


def _render_endorsements_section(credential_store: Any, e: Any) -> str:
    """Render Endorsements section from attestation credentials."""
    from cortex.upai.attestations import ATTESTATION_TYPES
    attest_types = set(ATTESTATION_TYPES.keys())

    creds = credential_store.list_all()
    attestations = [c for c in creds
                    if c.status == "active"
                    and attest_types.intersection(set(c.credential_type))]
    if not attestations:
        return ""

    entries: list[str] = []
    for cred in attestations:
        name = e(cred.claims.get("subject_name", ""))
        # Determine type
        cred_types = [t for t in cred.credential_type if t != "VerifiableCredential"]
        type_label = cred_types[0] if cred_types else "Attestation"

        entry = f'<div class="entry"><h3>{e(type_label)}</h3>'
        if "reference_text" in cred.claims:
            entry += f'<div class="desc">"{e(cred.claims["reference_text"])}"</div>'
        if "skill" in cred.claims:
            entry += f'<div class="desc">Skill: {e(cred.claims["skill"])}</div>'
        entry += f'<div class="meta"><span class="verified">Verified</span> — signed by {e(cred.issuer_did[:24])}...</div>'
        entry += "</div>"
        entries.append(entry)

    return f'<div class="section"><h2>Endorsements</h2>{"".join(entries)}</div>'
