"""Static file serving for the Cortex Web UI."""

from __future__ import annotations

import mimetypes
from pathlib import Path

# Ensure common web MIME types are registered
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("text/html", ".html")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/json", ".json")

# Webapp root directory
WEBAPP_DIR = Path(__file__).parent


def resolve_webapp_path(url_path: str) -> Path | None:
    """Resolve a URL path to a file inside the webapp directory.

    Returns None if the path escapes the webapp directory or the file
    does not exist.  ``/app`` and ``/app/`` resolve to ``index.html``.
    """
    import sys
    # Strip the /app prefix
    rel = url_path.lstrip("/")
    if rel.startswith("app"):
        rel = rel[len("app"):]
    rel = rel.lstrip("/")

    if not rel or rel == "":
        rel = "index.html"

    resolved = (WEBAPP_DIR / rel).resolve()

    # Debug logging
    print(f"DEBUG resolve_webapp_path: url_path={url_path!r}, rel={rel!r}, WEBAPP_DIR={WEBAPP_DIR}, resolved={resolved}, is_file={resolved.is_file()}", file=sys.stderr)

    # Prevent directory traversal
    if not str(resolved).startswith(str(WEBAPP_DIR.resolve())):
        return None

    if resolved.is_file():
        return resolved
    return None


def guess_webapp_content_type(path: Path) -> str:
    """Return the MIME type for a file path."""
    ct, _ = mimetypes.guess_type(str(path))
    return ct or "application/octet-stream"
