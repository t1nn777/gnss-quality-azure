resource "azurerm_resource_group" "dbx" {
  name     = "rg-${var.prefix}-databricks"
  location = var.location
  tags     = var.tags
}

resource "azurerm_databricks_workspace" "this" {
  name                        = "dbw-${var.prefix}"
  resource_group_name         = azurerm_resource_group.dbx.name
  location                    = azurerm_resource_group.dbx.location
  sku                         = "premium" # Unity Catalog, cluster policies, job run_as
  managed_resource_group_name = "rg-${var.prefix}-databricks-managed"
  tags                        = var.tags
}

# --------------------------------------------------------------------------- #
# Single-node only: the subscription allows ~4 vCPU per region, so the policy
# pins one 4-core node (driver only) with a short auto-termination.
# --------------------------------------------------------------------------- #
locals {
  node_type = "Standard_DS3_v2" # 4 vCPU, 14 GB
}

resource "databricks_cluster_policy" "single_node" {
  name = "gnss-single-node-4core"
  definition = jsonencode({
    "num_workers"                                 = { type = "fixed", value = 0, hidden = true }
    "node_type_id"                                = { type = "fixed", value = local.node_type }
    "driver_node_type_id"                         = { type = "fixed", value = local.node_type }
    "autotermination_minutes"                     = { type = "fixed", value = 15 }
    "spark_conf.spark.databricks.cluster.profile" = { type = "fixed", value = "singleNode", hidden = true }
    "spark_conf.spark.master"                     = { type = "fixed", value = "local[*]", hidden = true }
    "custom_tags.ResourceClass"                   = { type = "fixed", value = "SingleNode", hidden = true }
    "autoscale.max_workers"                       = { type = "forbidden", hidden = true }
  })
}

data "databricks_spark_version" "lts" {
  long_term_support = true
  depends_on        = [azurerm_databricks_workspace.this]
}

resource "databricks_cluster" "single_node" {
  cluster_name            = "gnss-single-node"
  spark_version           = data.databricks_spark_version.lts.id
  policy_id               = databricks_cluster_policy.single_node.id
  node_type_id            = local.node_type
  driver_node_type_id     = local.node_type
  num_workers             = 0
  autotermination_minutes = 15
  data_security_mode      = "SINGLE_USER"
  single_user_name        = var.user_name

  spark_conf = {
    "spark.databricks.cluster.profile" = "singleNode"
    "spark.master"                     = "local[*]"
  }

  custom_tags = {
    "ResourceClass" = "SingleNode"
  }
}

# geo/ needs shapely on the cluster (numpy/pandas ship with the runtime).
resource "databricks_library" "shapely" {
  cluster_id = databricks_cluster.single_node.id
  pypi {
    package = "shapely==2.0.6"
  }
}

# --------------------------------------------------------------------------- #
# GitHub Actions identity (same user-assigned managed identity as infra/app)
# -> workspace service principal + admin, so `databricks bundle deploy` works
# with OIDC and the job can run_as your user on the single-user cluster.
# --------------------------------------------------------------------------- #
resource "databricks_service_principal" "github" {
  count          = var.github_identity_client_id == "" ? 0 : 1
  application_id = var.github_identity_client_id
  display_name   = "github-actions-${var.prefix}"
}

data "databricks_group" "admins" {
  display_name = "admins"
  depends_on   = [azurerm_databricks_workspace.this]
}

resource "databricks_group_member" "github_admin" {
  count     = var.github_identity_client_id == "" ? 0 : 1
  group_id  = data.databricks_group.admins.id
  member_id = databricks_service_principal.github[0].id
}
