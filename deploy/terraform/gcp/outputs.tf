output "service_url" {
  description = "URL of the Cloud Run service"
  value       = google_cloud_run_v2_service.main.uri
}

output "service_name" {
  description = "Name of the Cloud Run service"
  value       = google_cloud_run_v2_service.main.name
}

output "cloud_sql_connection_name" {
  description = "Cloud SQL connection name (if enabled)"
  value       = var.enable_cloud_sql ? google_sql_database_instance.main[0].connection_name : ""
}
