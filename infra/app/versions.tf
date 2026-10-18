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
  features {}
  subscription_id = var.subscription_id
}
