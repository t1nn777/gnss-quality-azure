data "azurerm_client_config" "current" {}

resource "random_string" "suffix" {
  length  = 5
  upper   = false
  special = false
}

locals {
  name = "${var.prefix}-${random_string.suffix.result}"

  # Repos with immutable OIDC subjects send repo:OWNER@OWNER_ID/REPO@REPO_ID:...
  github_subject_prefix = (var.github_owner_id != "" && var.github_repo_id != ""
    ? "repo:${var.github_owner}@${var.github_owner_id}/${var.github_repo}@${var.github_repo_id}"
  : "repo:${var.github_owner}/${var.github_repo}")
}

resource "azurerm_resource_group" "app" {
  name     = "rg-${var.prefix}-app"
  location = var.location
  tags     = var.tags
}

# --------------------------------------------------------------------------- #
# Observability
# --------------------------------------------------------------------------- #
resource "azurerm_log_analytics_workspace" "this" {
  name                = "log-${local.name}"
  resource_group_name = azurerm_resource_group.app.name
  location            = azurerm_resource_group.app.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  daily_quota_gb      = 0.5 # keeps the student budget safe
  tags                = var.tags
}

resource "azurerm_application_insights" "this" {
  name                = "appi-${local.name}"
  resource_group_name = azurerm_resource_group.app.name
  location            = azurerm_resource_group.app.location
  workspace_id        = azurerm_log_analytics_workspace.this.id
  application_type    = "web"
  tags                = var.tags
}

# --------------------------------------------------------------------------- #
# App Service: one B1 Linux plan, two web apps (F1 breaks Streamlit websockets)
# --------------------------------------------------------------------------- #
resource "azurerm_service_plan" "this" {
  name                = "asp-${local.name}"
  resource_group_name = azurerm_resource_group.app.name
  location            = azurerm_resource_group.app.location
  os_type             = "Linux"
  sku_name            = "B1"
  tags                = var.tags
}

resource "azurerm_linux_web_app" "api" {
  name                = "app-${local.name}-api"
  resource_group_name = azurerm_resource_group.app.name
  location            = azurerm_resource_group.app.location
  service_plan_id     = azurerm_service_plan.this.id
  https_only          = true
  tags                = var.tags

  site_config {
    always_on                         = true
    ftps_state                        = "Disabled"
    health_check_path                 = "/health"
    health_check_eviction_time_in_min = 10
    app_command_line                  = "gunicorn -w 2 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --timeout 120 main:app"

    application_stack {
      python_version = "3.12"
    }
  }

  app_settings = {
    SCM_DO_BUILD_DURING_DEPLOYMENT        = "true"
    APPLICATIONINSIGHTS_CONNECTION_STRING = azurerm_application_insights.this.connection_string
    # Cold start (unpack Oryx output + import numpy/pandas/shapely) can exceed the 230 s default on B1.
    WEBSITES_CONTAINER_START_TIME_LIMIT = "600"
    OTEL_SERVICE_NAME                   = "gnss-api"
  }
}

resource "azurerm_linux_web_app" "ui" {
  name                = "app-${local.name}-ui"
  resource_group_name = azurerm_resource_group.app.name
  location            = azurerm_resource_group.app.location
  service_plan_id     = azurerm_service_plan.this.id
  https_only          = true
  tags                = var.tags

  site_config {
    always_on          = true
    ftps_state         = "Disabled"
    websockets_enabled = true
    app_command_line   = "python -m streamlit run app.py --server.port 8000 --server.address 0.0.0.0"

    application_stack {
      python_version = "3.12"
    }
  }

  app_settings = {
    SCM_DO_BUILD_DURING_DEPLOYMENT        = "true"
    APPLICATIONINSIGHTS_CONNECTION_STRING = azurerm_application_insights.this.connection_string
    # Cold start (unpack Oryx output + import numpy/pandas/shapely) can exceed the 230 s default on B1.
    WEBSITES_CONTAINER_START_TIME_LIMIT = "600"
    API_URL                             = "https://${azurerm_linux_web_app.api.default_hostname}"
  }
}

# --------------------------------------------------------------------------- #
# GitHub Actions identity (OIDC, no secrets): user-assigned managed identity
# with federated credentials for pushes to main and for pull requests.
# --------------------------------------------------------------------------- #
resource "azurerm_user_assigned_identity" "github" {
  name                = "id-${var.prefix}-github"
  resource_group_name = azurerm_resource_group.app.name
  location            = azurerm_resource_group.app.location
  tags                = var.tags
}

resource "azurerm_federated_identity_credential" "main" {
  name                = "github-main"
  resource_group_name = azurerm_resource_group.app.name
  parent_id           = azurerm_user_assigned_identity.github.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = "https://token.actions.githubusercontent.com"
  subject             = "${local.github_subject_prefix}:ref:refs/heads/main"
}

resource "azurerm_federated_identity_credential" "pull_request" {
  name                = "github-pull-request"
  resource_group_name = azurerm_resource_group.app.name
  parent_id           = azurerm_user_assigned_identity.github.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = "https://token.actions.githubusercontent.com"
  subject             = "${local.github_subject_prefix}:pull_request"
}

# Deploy + terraform apply inside the app resource group.
resource "azurerm_role_assignment" "github_contributor" {
  scope                = azurerm_resource_group.app.id
  role_definition_name = "Contributor"
  principal_id         = azurerm_user_assigned_identity.github.principal_id
}

# Read-only at subscription scope so `terraform plan` in CI can refresh every
# object in this state (incl. the role assignments below) and the provider can
# check resource provider registrations.
resource "azurerm_role_assignment" "github_reader" {
  scope                = "/subscriptions/${var.subscription_id}"
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.github.principal_id
}

# Read/write the remote state blobs (backends use Entra ID auth).
resource "azurerm_role_assignment" "github_tfstate" {
  scope                = var.tfstate_storage_account_id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.github.principal_id
}
