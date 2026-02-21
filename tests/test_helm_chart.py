"""Tests for deploy/helm/cortex — Kubernetes Helm chart validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

HELM_DIR = Path(__file__).resolve().parent.parent / "deploy" / "helm" / "cortex"


class TestHelmChartStructure:
    def test_chart_yaml_exists(self):
        assert (HELM_DIR / "Chart.yaml").exists()

    def test_values_yaml_exists(self):
        assert (HELM_DIR / "values.yaml").exists()

    def test_templates_dir_exists(self):
        assert (HELM_DIR / "templates").is_dir()

    def test_required_templates_exist(self):
        templates = HELM_DIR / "templates"
        expected = [
            "_helpers.tpl",
            "deployment.yaml",
            "service.yaml",
            "configmap.yaml",
            "serviceaccount.yaml",
            "ingress.yaml",
            "hpa.yaml",
            "servicemonitor.yaml",
            "pvc.yaml",
            "NOTES.txt",
        ]
        for name in expected:
            assert (templates / name).exists(), f"Missing template: {name}"

    def test_test_connection_exists(self):
        assert (HELM_DIR / "templates" / "tests" / "test-connection.yaml").exists()


@pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
class TestHelmChartContent:
    def test_chart_yaml_fields(self):
        chart = yaml.safe_load((HELM_DIR / "Chart.yaml").read_text())
        assert chart["apiVersion"] == "v2"
        assert chart["name"] == "cortex"
        assert "version" in chart
        assert "appVersion" in chart

    def test_values_yaml_defaults(self):
        values = yaml.safe_load((HELM_DIR / "values.yaml").read_text())
        assert values["replicaCount"] == 1
        assert values["service"]["port"] == 8421
        assert values["storage"]["backend"] == "json"
        assert values["metrics"]["enabled"] is False

    def test_values_yaml_has_all_sections(self):
        values = yaml.safe_load((HELM_DIR / "values.yaml").read_text())
        for section in ("server", "storage", "sse", "webhooks", "metrics",
                        "logging", "security", "plugins", "service",
                        "ingress", "resources", "autoscaling", "persistence",
                        "serviceMonitor"):
            assert section in values, f"Missing values section: {section}"


class TestHelmTemplateContent:
    """Validate template files contain expected patterns (text-based, no YAML parsing needed)."""

    def test_deployment_has_health_probe(self):
        text = (HELM_DIR / "templates" / "deployment.yaml").read_text()
        assert "livenessProbe" in text
        assert "/health" in text

    def test_deployment_has_readiness_probe(self):
        text = (HELM_DIR / "templates" / "deployment.yaml").read_text()
        assert "readinessProbe" in text

    def test_deployment_mounts_config(self):
        text = (HELM_DIR / "templates" / "deployment.yaml").read_text()
        assert "configMap" in text
        assert "/etc/cortex" in text

    def test_configmap_generates_ini(self):
        text = (HELM_DIR / "templates" / "configmap.yaml").read_text()
        assert "[server]" in text
        assert "[storage]" in text
        assert "[metrics]" in text

    def test_service_exposes_http(self):
        text = (HELM_DIR / "templates" / "service.yaml").read_text()
        assert "http" in text

    def test_ingress_conditional(self):
        text = (HELM_DIR / "templates" / "ingress.yaml").read_text()
        assert "if .Values.ingress.enabled" in text

    def test_hpa_conditional(self):
        text = (HELM_DIR / "templates" / "hpa.yaml").read_text()
        assert "if .Values.autoscaling.enabled" in text

    def test_servicemonitor_conditional(self):
        text = (HELM_DIR / "templates" / "servicemonitor.yaml").read_text()
        assert "if .Values.serviceMonitor.enabled" in text
        assert "/metrics" in text

    def test_notes_contains_instructions(self):
        text = (HELM_DIR / "templates" / "NOTES.txt").read_text()
        assert "/health" in text
        assert "port-forward" in text
