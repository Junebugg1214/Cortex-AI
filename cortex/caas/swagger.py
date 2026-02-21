"""
Swagger UI — serves an interactive API documentation page.

Generates a single HTML page that loads Swagger UI from the unpkg CDN
and points it at the bundled OpenAPI spec.  No external dependencies.

Usage::

    from cortex.caas.swagger import swagger_html, load_openapi_spec

    html = swagger_html("/openapi.json")
    spec = load_openapi_spec()
"""

from __future__ import annotations

import json
from pathlib import Path

_SPEC_PATH = Path(__file__).resolve().parent.parent.parent / "spec" / "openapi.json"

_SWAGGER_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Cortex CaaS API — Swagger UI</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
  <style>
    html {{ box-sizing: border-box; overflow-y: scroll; }}
    *, *::before, *::after {{ box-sizing: inherit; }}
    body {{ margin: 0; background: #fafafa; }}
  </style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    SwaggerUIBundle({{
      url: "{spec_url}",
      dom_id: "#swagger-ui",
      presets: [
        SwaggerUIBundle.presets.apis,
        SwaggerUIBundle.SwaggerUIStandalonePreset,
      ],
      layout: "BaseLayout",
      deepLinking: true,
    }});
  </script>
</body>
</html>
"""


def swagger_html(spec_url: str = "/openapi.json") -> str:
    """Return the Swagger UI HTML page pointing at *spec_url*."""
    return _SWAGGER_HTML_TEMPLATE.format(spec_url=spec_url)


def load_openapi_spec() -> dict | None:
    """Load the OpenAPI spec from the bundled ``spec/openapi.json``.

    Returns ``None`` if the file does not exist.
    """
    if _SPEC_PATH.exists():
        return json.loads(_SPEC_PATH.read_text(encoding="utf-8"))
    return None
