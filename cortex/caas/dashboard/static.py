"""Static file serving for the CaaS dashboard."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import unquote

# Ensure common web MIME types are registered
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("text/html", ".html")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/json", ".json")

# Dashboard root directory
DASHBOARD_DIR = Path(__file__).parent


def resolve_dashboard_path(url_path: str) -> Path | None:
    """Resolve a URL path to a file inside the dashboard directory.

    Returns None if the path escapes the dashboard directory or the file
    does not exist.  ``/dashboard`` and ``/dashboard/`` resolve to
    ``index.html``.
    """
    # Decode and normalize incoming URL path before resolving to disk.
    rel = unquote(url_path or "").split("?", 1)[0].split("#", 1)[0].lstrip("/")
    while rel == "dashboard" or rel.startswith("dashboard/"):
        rel = rel[len("dashboard"):].lstrip("/")

    if not rel or rel == "":
        rel = "index.html"

    # Reject traversal attempts after path normalization.
    normalized = Path(rel)
    if ".." in normalized.parts:
        return None

    resolved = (DASHBOARD_DIR / normalized).resolve()

    # Prevent directory traversal
    if not str(resolved).startswith(str(DASHBOARD_DIR.resolve())):
        return None

    if resolved.is_file():
        return resolved
    return None


def guess_content_type(path: Path) -> str:
    """Return the MIME type for a file path."""
    ct, _ = mimetypes.guess_type(str(path))
    return ct or "application/octet-stream"
