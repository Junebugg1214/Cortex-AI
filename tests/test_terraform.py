"""Tests for deploy/terraform/ — validate Terraform module structure."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

TERRAFORM_ROOT = Path(__file__).resolve().parent.parent / "deploy" / "terraform"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_tf(path: Path) -> str:
    """Read a .tf file as text."""
    return path.read_text(encoding="utf-8")


def _extract_blocks(content: str, block_type: str) -> list[str]:
    """Extract top-level block names of a given type from HCL.

    For ``resource "aws_vpc" "main"``, returns ``["aws_vpc.main"]``.
    For ``variable "foo"``, returns ``["foo"]``.
    For ``output "bar"``, returns ``["bar"]``.
    """
    # Match patterns like: resource "type" "name" {
    #                        variable "name" {
    #                        output "name" {
    if block_type == "resource":
        pattern = r'resource\s+"([^"]+)"\s+"([^"]+)"'
        return [f"{m[0]}.{m[1]}" for m in re.findall(pattern, content)]
    else:
        pattern = rf'{block_type}\s+"([^"]+)"'
        return re.findall(pattern, content)


# ---------------------------------------------------------------------------
# AWS module tests
# ---------------------------------------------------------------------------

class TestAWSModule:
    @pytest.fixture(autouse=True)
    def _check_exists(self):
        if not (TERRAFORM_ROOT / "aws" / "main.tf").exists():
            pytest.skip("AWS Terraform module not found")

    def test_main_tf_exists(self):
        assert (TERRAFORM_ROOT / "aws" / "main.tf").is_file()

    def test_variables_tf_exists(self):
        assert (TERRAFORM_ROOT / "aws" / "variables.tf").is_file()

    def test_outputs_tf_exists(self):
        assert (TERRAFORM_ROOT / "aws" / "outputs.tf").is_file()

    def test_required_resources(self):
        content = _read_tf(TERRAFORM_ROOT / "aws" / "main.tf")
        resources = _extract_blocks(content, "resource")
        resource_types = {r.split(".")[0] for r in resources}
        assert "aws_ecs_cluster" in resource_types
        assert "aws_ecs_service" in resource_types
        assert "aws_ecs_task_definition" in resource_types
        assert "aws_lb" in resource_types
        assert "aws_vpc" in resource_types

    def test_required_variables(self):
        content = _read_tf(TERRAFORM_ROOT / "aws" / "variables.tf")
        variables = _extract_blocks(content, "variable")
        assert "image" in variables
        assert "aws_region" in variables
        assert "container_port" in variables

    def test_outputs_defined(self):
        content = _read_tf(TERRAFORM_ROOT / "aws" / "outputs.tf")
        outputs = _extract_blocks(content, "output")
        assert "alb_dns_name" in outputs

    def test_health_check_configured(self):
        content = _read_tf(TERRAFORM_ROOT / "aws" / "main.tf")
        assert "/health" in content

    def test_container_port_referenced(self):
        content = _read_tf(TERRAFORM_ROOT / "aws" / "main.tf")
        assert "var.container_port" in content

    def test_terraform_version_constraint(self):
        content = _read_tf(TERRAFORM_ROOT / "aws" / "main.tf")
        assert "required_version" in content


# ---------------------------------------------------------------------------
# GCP module tests
# ---------------------------------------------------------------------------

class TestGCPModule:
    @pytest.fixture(autouse=True)
    def _check_exists(self):
        if not (TERRAFORM_ROOT / "gcp" / "main.tf").exists():
            pytest.skip("GCP Terraform module not found")

    def test_main_tf_exists(self):
        assert (TERRAFORM_ROOT / "gcp" / "main.tf").is_file()

    def test_variables_tf_exists(self):
        assert (TERRAFORM_ROOT / "gcp" / "variables.tf").is_file()

    def test_outputs_tf_exists(self):
        assert (TERRAFORM_ROOT / "gcp" / "outputs.tf").is_file()

    def test_required_resources(self):
        content = _read_tf(TERRAFORM_ROOT / "gcp" / "main.tf")
        resources = _extract_blocks(content, "resource")
        resource_types = {r.split(".")[0] for r in resources}
        assert "google_cloud_run_v2_service" in resource_types

    def test_required_variables(self):
        content = _read_tf(TERRAFORM_ROOT / "gcp" / "variables.tf")
        variables = _extract_blocks(content, "variable")
        assert "project_id" in variables
        assert "image" in variables
        assert "container_port" in variables

    def test_outputs_defined(self):
        content = _read_tf(TERRAFORM_ROOT / "gcp" / "outputs.tf")
        outputs = _extract_blocks(content, "output")
        assert "service_url" in outputs

    def test_health_check_configured(self):
        content = _read_tf(TERRAFORM_ROOT / "gcp" / "main.tf")
        assert "/health" in content

    def test_cloud_sql_optional(self):
        content = _read_tf(TERRAFORM_ROOT / "gcp" / "variables.tf")
        assert "enable_cloud_sql" in content

    def test_terraform_version_constraint(self):
        content = _read_tf(TERRAFORM_ROOT / "gcp" / "main.tf")
        assert "required_version" in content


# ---------------------------------------------------------------------------
# Shared Postgres module tests
# ---------------------------------------------------------------------------

class TestPostgresModule:
    @pytest.fixture(autouse=True)
    def _check_exists(self):
        if not (TERRAFORM_ROOT / "modules" / "postgres" / "main.tf").exists():
            pytest.skip("Postgres Terraform module not found")

    def test_main_tf_exists(self):
        assert (TERRAFORM_ROOT / "modules" / "postgres" / "main.tf").is_file()

    def test_required_variables(self):
        content = _read_tf(TERRAFORM_ROOT / "modules" / "postgres" / "main.tf")
        variables = _extract_blocks(content, "variable")
        assert "host" in variables
        assert "username" in variables
        assert "password" in variables

    def test_outputs_defined(self):
        content = _read_tf(TERRAFORM_ROOT / "modules" / "postgres" / "main.tf")
        outputs = _extract_blocks(content, "output")
        assert "connection_string" in outputs

    def test_sensitive_vars_marked(self):
        content = _read_tf(TERRAFORM_ROOT / "modules" / "postgres" / "main.tf")
        # Check that password variable is marked sensitive
        assert "sensitive" in content
