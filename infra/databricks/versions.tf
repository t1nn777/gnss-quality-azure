terraform {
  required_version = ">= 1.6"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.14"
    }
    databricks = {
      source  = "databricks/databricks"
      version = "~> 1.60"
    }
  }

  # Separate state key from infra/app. Other settings via -backend-config=backend.hcl.
  backend "azurerm" {
    key              = "databricks.tfstate"
    use_azuread_auth = true
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
  # Do not auto-register dozens of resource providers (hangs on student subscriptions;
  # CI only has Reader). The few this project needs are registered once, see README.
  resource_provider_registrations = "none"
}

# Authenticates with your `az login` session against the workspace created below.
provider "databricks" {
  host                        = "https://${azurerm_databricks_workspace.this.workspace_url}"
  azure_workspace_resource_id = azurerm_databricks_workspace.this.id
}
