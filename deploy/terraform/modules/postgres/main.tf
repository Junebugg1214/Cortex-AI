# Cortex-AI — Shared PostgreSQL Configuration Module
#
# This module generates the Cortex-compatible connection string and
# initializes the database schema. Can be used with either AWS RDS
# or GCP Cloud SQL.

terraform {
  required_version = ">= 1.5"
}

variable "host" {
  description = "PostgreSQL host"
  type        = string
}

variable "port" {
  description = "PostgreSQL port"
  type        = number
  default     = 5432
}

variable "database" {
  description = "Database name"
  type        = string
  default     = "cortex"
}

variable "username" {
  description = "Database username"
  type        = string
  sensitive   = true
}

variable "password" {
  description = "Database password"
  type        = string
  sensitive   = true
}

variable "ssl_mode" {
  description = "PostgreSQL SSL mode"
  type        = string
  default     = "require"
}

locals {
  # Cortex-compatible connection string (psycopg format)
  connection_string = "host=${var.host} port=${var.port} dbname=${var.database} user=${var.username} password=${var.password} sslmode=${var.ssl_mode}"

  # Standard PostgreSQL URI format
  connection_uri = "postgresql://${var.username}:${var.password}@${var.host}:${var.port}/${var.database}?sslmode=${var.ssl_mode}"
}

output "connection_string" {
  description = "psycopg-format connection string for CORTEX_STORAGE_DB_URL"
  value       = local.connection_string
  sensitive   = true
}

output "connection_uri" {
  description = "PostgreSQL URI format connection string"
  value       = local.connection_uri
  sensitive   = true
}

output "env_vars" {
  description = "Environment variables to set for Cortex-AI"
  value = {
    CORTEX_STORAGE_BACKEND = "postgres"
    CORTEX_STORAGE_DB_URL  = local.connection_string
  }
  sensitive = true
}
