terraform {
  required_version = ">= 1.6"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.14"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # resource_group_name / storage_account_name / container_name come from
  # `terraform init -backend-config=backend.hcl` (local) or -backend-config flags (CI).
  backend "azurerm" {
    key              = "app.tfstate"
    use_azuread_auth = true
  }
}

provider "azurerm" {
  features {
    # Application Insights makes Azure create an "Application Insights Smart Detection"
    # action group in rg-gnss-app that Terraform does not manage; without this,
    # destroy fails on "the Resource Group still contains Resources". rg-gnss-app
    # belongs to this stack only, so anything left in it is safe to delete.
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
  }
  subscription_id = var.subscription_id
  # Do not auto-register dozens of resource providers (hangs on student subscriptions;
  # CI only has Reader). The few this project needs are registered once, see README.
  resource_provider_registrations = "none"
}
