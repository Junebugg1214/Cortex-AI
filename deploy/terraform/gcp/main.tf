# Cortex-AI — GCP Deployment (Cloud Run + optional Cloud SQL)
#
# Usage:
#   cd deploy/terraform/gcp
#   terraform init
#   terraform plan -var="project_id=my-gcp-project" -var="image=gcr.io/my-project/cortex-ai:latest"
#   terraform apply

terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.gcp_region
}

# ---------------------------------------------------------------------------
# Cloud Run Service
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "main" {
  name     = var.service_name
  location = var.gcp_region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = var.image

      ports {
        container_port = var.container_port
      }

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
      }

      env {
        name  = "CORTEX_SERVER_PORT"
        value = tostring(var.container_port)
      }

      env {
        name  = "CORTEX_STORAGE_BACKEND"
        value = var.storage_backend
      }

      env {
        name  = "CORTEX_METRICS_ENABLED"
        value = var.enable_metrics ? "true" : "false"
      }

      startup_probe {
        http_get {
          path = "/health"
          port = var.container_port
        }
        initial_delay_seconds = 5
        period_seconds        = 10
        failure_threshold     = 3
      }

      liveness_probe {
        http_get {
          path = "/health"
          port = var.container_port
        }
        period_seconds = 30
      }
    }
  }
}

# Allow unauthenticated access (public API)
resource "google_cloud_run_v2_service_iam_member" "public" {
  count    = var.allow_unauthenticated ? 1 : 0
  project  = google_cloud_run_v2_service.main.project
  location = google_cloud_run_v2_service.main.location
  name     = google_cloud_run_v2_service.main.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ---------------------------------------------------------------------------
# Cloud SQL (optional)
# ---------------------------------------------------------------------------

resource "google_sql_database_instance" "main" {
  count            = var.enable_cloud_sql ? 1 : 0
  name             = "${var.service_name}-db"
  database_version = "POSTGRES_15"
  region           = var.gcp_region

  settings {
    tier              = var.sql_tier
    availability_type = "ZONAL"
    disk_size         = var.sql_disk_size

    ip_configuration {
      ipv4_enabled = true
    }

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
    }
  }

  deletion_protection = var.sql_deletion_protection
}

resource "google_sql_database" "main" {
  count    = var.enable_cloud_sql ? 1 : 0
  name     = "cortex"
  instance = google_sql_database_instance.main[0].name
}

resource "google_sql_user" "main" {
  count    = var.enable_cloud_sql ? 1 : 0
  name     = var.sql_username
  instance = google_sql_database_instance.main[0].name
  password = var.sql_password
}
