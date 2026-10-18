output "resource_group_name" {
  value = azurerm_resource_group.app.name
}

output "api_app_name" {
  description = "GitHub variable API_APP_NAME."
  value       = azurerm_linux_web_app.api.name
}

output "ui_app_name" {
  description = "GitHub variable UI_APP_NAME."
  value       = azurerm_linux_web_app.ui.name
}

output "api_url" {
  value = "https://${azurerm_linux_web_app.api.default_hostname}"
}

output "ui_url" {
  value = "https://${azurerm_linux_web_app.ui.default_hostname}"
}

output "github_identity_client_id" {
  description = "GitHub secret AZURE_CLIENT_ID."
  value       = azurerm_user_assigned_identity.github.client_id
}

output "github_identity_principal_id" {
  description = "Object ID of the GitHub identity (input for infra/databricks)."
  value       = azurerm_user_assigned_identity.github.principal_id
}

output "tenant_id" {
  description = "GitHub secret AZURE_TENANT_ID."
  value       = data.azurerm_client_config.current.tenant_id
}

output "subscription_id" {
  description = "GitHub secret AZURE_SUBSCRIPTION_ID."
  value       = var.subscription_id
}
