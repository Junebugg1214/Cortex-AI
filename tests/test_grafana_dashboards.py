"""Tests for Grafana dashboard JSON files — validate structure and metric references."""

import json
import re
from pathlib import Path

import pytest

GRAFANA_DIR = Path(__file__).resolve().parent.parent / "deploy" / "grafana"

DASHBOARD_FILES = [
    "cortex-overview.json",
    "cortex-graph.json",
    "cortex-webhooks.json",
]

# All 17 metric names from cortex/caas/instrumentation.py
KNOWN_METRICS = {
    "cortex_http_requests_total",
    "cortex_http_request_duration_seconds",
    "cortex_http_requests_in_flight",
    "cortex_grants_active",
    "cortex_graph_nodes",
    "cortex_graph_edges",
    "cortex_errors_total",
    "cortex_build_info",
    "cortex_rate_limit_rejected_total",
    "cortex_webhook_deliveries_total",
    "cortex_webhook_dead_letters",
    "cortex_circuit_breaker_state",
    "cortex_audit_entries_total",
    "cortex_cache_hits_total",
    "cortex_cache_misses_total",
    "cortex_sse_subscribers_active",
    "cortex_sse_events_total",
}


def _load_dashboard(name: str) -> dict:
    path = GRAFANA_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_metric_names(dashboard: dict) -> set[str]:
    """Extract all cortex_* metric names referenced in dashboard expressions."""
    text = json.dumps(dashboard)
    return set(re.findall(r"cortex_\w+", text))


@pytest.fixture(params=DASHBOARD_FILES)
def dashboard_file(request):
    return request.param


class TestDashboardStructure:
    def test_files_exist(self):
        for name in DASHBOARD_FILES:
            assert (GRAFANA_DIR / name).exists(), f"Missing dashboard: {name}"

    def test_valid_json(self, dashboard_file):
        data = _load_dashboard(dashboard_file)
        assert isinstance(data, dict)

    def test_has_title(self, dashboard_file):
        data = _load_dashboard(dashboard_file)
        assert "title" in data
        assert data["title"]

    def test_has_uid(self, dashboard_file):
        data = _load_dashboard(dashboard_file)
        assert "uid" in data
        assert data["uid"]

    def test_has_panels(self, dashboard_file):
        data = _load_dashboard(dashboard_file)
        assert "panels" in data
        assert len(data["panels"]) > 0

    def test_panels_have_titles(self, dashboard_file):
        data = _load_dashboard(dashboard_file)
        for panel in data["panels"]:
            assert "title" in panel, f"Panel missing title in {dashboard_file}"

    def test_panels_have_targets(self, dashboard_file):
        data = _load_dashboard(dashboard_file)
        for panel in data["panels"]:
            assert "targets" in panel, f"Panel '{panel.get('title')}' missing targets"
            assert len(panel["targets"]) > 0

    def test_has_schema_version(self, dashboard_file):
        data = _load_dashboard(dashboard_file)
        assert "schemaVersion" in data


class TestMetricReferences:
    def test_all_metrics_referenced_are_known(self, dashboard_file):
        data = _load_dashboard(dashboard_file)
        referenced = _extract_metric_names(data)
        # Filter to base metric names (remove _bucket, _total suffixes that
        # might appear in PromQL but not in our list)
        unknown = set()
        for m in referenced:
            base = m
            if base.endswith("_bucket"):
                base = base[: -len("_bucket")]
            if base not in KNOWN_METRICS:
                unknown.add(m)
        assert not unknown, f"Unknown metrics in {dashboard_file}: {unknown}"

    def test_all_17_metrics_covered_across_dashboards(self):
        all_referenced: set[str] = set()
        for name in DASHBOARD_FILES:
            data = _load_dashboard(name)
            refs = _extract_metric_names(data)
            # Normalize _bucket variants
            for m in refs:
                if m.endswith("_bucket"):
                    all_referenced.add(m[: -len("_bucket")])
                else:
                    all_referenced.add(m)
        missing = KNOWN_METRICS - all_referenced
        assert not missing, f"Metrics not covered by any dashboard: {missing}"


class TestProvisioningFiles:
    def test_dashboards_yml_exists(self):
        path = GRAFANA_DIR / "provisioning" / "dashboards.yml"
        assert path.exists()
        content = path.read_text()
        assert "apiVersion" in content

    def test_datasources_yml_exists(self):
        path = GRAFANA_DIR / "provisioning" / "datasources.yml"
        assert path.exists()
        content = path.read_text()
        assert "prometheus" in content.lower()
