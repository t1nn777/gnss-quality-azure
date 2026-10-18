output "workspace_url" {
  description = "GitHub variable DATABRICKS_HOST."
  value       = "https://${azurerm_databricks_workspace.this.workspace_url}"
}

output "workspace_name" {
  value = azurerm_databricks_workspace.this.name
}

output "cluster_id" {
  description = "GitHub variable DATABRICKS_CLUSTER_ID / bundle variable cluster_id."
  value       = databricks_cluster.single_node.id
}

output "spark_version" {
  value = data.databricks_spark_version.lts.id
}
