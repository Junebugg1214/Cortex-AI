variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "gcp_region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

variable "service_name" {
  description = "Cloud Run service name"
  type        = string
  default     = "cortex-ai"
}

variable "image" {
  description = "Container image for Cortex-AI"
  type        = string
}

variable "container_port" {
  description = "Port the container listens on"
  type        = number
  default     = 8421
}

variable "cpu" {
  description = "CPU limit for Cloud Run"
  type        = string
  default     = "1"
}

variable "memory" {
  description = "Memory limit for Cloud Run"
  type        = string
  default     = "512Mi"
}

variable "min_instances" {
  description = "Minimum number of Cloud Run instances"
  type        = number
  default     = 0
}

variable "max_instances" {
  description = "Maximum number of Cloud Run instances"
  type        = number
  default     = 10
}

variable "storage_backend" {
  description = "Storage backend: json, sqlite, or postgres"
  type        = string
  default     = "sqlite"
}

variable "enable_metrics" {
  description = "Enable Prometheus metrics endpoint"
  type        = bool
  default     = true
}

variable "allow_unauthenticated" {
  description = "Allow unauthenticated access to Cloud Run service"
  type        = bool
  default     = false
}

variable "enable_cloud_sql" {
  description = "Deploy a Cloud SQL PostgreSQL instance"
  type        = bool
  default     = false
}

variable "sql_tier" {
  description = "Cloud SQL machine tier"
  type        = string
  default     = "db-f1-micro"
}

variable "sql_disk_size" {
  description = "Cloud SQL disk size in GB"
  type        = number
  default     = 10
}

variable "sql_username" {
  description = "Cloud SQL admin username"
  type        = string
  default     = "cortex"
  sensitive   = true
}

variable "sql_password" {
  description = "Cloud SQL admin password"
  type        = string
  default     = ""
  sensitive   = true
}

variable "sql_deletion_protection" {
  description = "Enable deletion protection on Cloud SQL instance"
  type        = bool
  default     = true
}
