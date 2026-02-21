"""Tests for cortex.caas.swagger — Swagger UI and OpenAPI spec serving."""

from __future__ import annotations

import json

import pytest

from cortex.caas.swagger import _SPEC_PATH, load_openapi_spec, swagger_html

# ---------------------------------------------------------------------------
# swagger_html tests
# ---------------------------------------------------------------------------

class TestSwaggerHtml:
    def test_returns_html_string(self):
        html = swagger_html()
        assert isinstance(html, str)
        assert html.startswith("<!DOCTYPE html>")

    def test_contains_swagger_ui_div(self):
        html = swagger_html()
        assert 'id="swagger-ui"' in html

    def test_contains_swagger_ui_bundle_script(self):
        html = swagger_html()
        assert "swagger-ui-bundle.js" in html

    def test_default_spec_url(self):
        html = swagger_html()
        assert '"/openapi.json"' in html

    def test_custom_spec_url(self):
        html = swagger_html("/api/v2/spec.json")
        assert '"/api/v2/spec.json"' in html

    def test_contains_css_link(self):
        html = swagger_html()
        assert "swagger-ui.css" in html

    def test_title(self):
        html = swagger_html()
        assert "Cortex CaaS API" in html


# ---------------------------------------------------------------------------
# load_openapi_spec tests
# ---------------------------------------------------------------------------

class TestLoadOpenApiSpec:
    def test_loads_spec(self):
        spec = load_openapi_spec()
        if not _SPEC_PATH.exists():
            pytest.skip("spec/openapi.json not found")
        assert spec is not None
        assert isinstance(spec, dict)

    def test_spec_has_openapi_field(self):
        spec = load_openapi_spec()
        if spec is None:
            pytest.skip("spec/openapi.json not found")
        assert "openapi" in spec

    def test_spec_has_info(self):
        spec = load_openapi_spec()
        if spec is None:
            pytest.skip("spec/openapi.json not found")
        assert "info" in spec
        assert "title" in spec["info"]

    def test_spec_has_paths(self):
        spec = load_openapi_spec()
        if spec is None:
            pytest.skip("spec/openapi.json not found")
        assert "paths" in spec
        assert len(spec["paths"]) > 0

    def test_spec_is_valid_json(self):
        """Spec should round-trip through JSON without loss."""
        spec = load_openapi_spec()
        if spec is None:
            pytest.skip("spec/openapi.json not found")
        # Round-trip
        json_str = json.dumps(spec)
        parsed = json.loads(json_str)
        assert parsed == spec

    def test_spec_path_constant(self):
        """_SPEC_PATH should point to spec/openapi.json."""
        assert _SPEC_PATH.name == "openapi.json"
        assert "spec" in str(_SPEC_PATH)
