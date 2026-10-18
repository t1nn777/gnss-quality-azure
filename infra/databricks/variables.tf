variable "subscription_id" {
  description = "Azure subscription ID."
  type        = string
}

variable "location" {
  type    = string
  default = "southeastasia"
}

variable "prefix" {
  type    = string
  default = "gnss"
}

variable "user_name" {
  description = "Your Databricks login (Entra ID e-mail); owner of the single-user cluster."
  type        = string
}

variable "github_identity_client_id" {
  description = "Client ID of the GitHub managed identity (output github_identity_client_id of infra/app). Empty = skip."
  type        = string
  default     = ""
}

variable "tags" {
  type = map(string)
  default = {
    project = "gnss-quality-azure"
    data    = "simulated"
  }
}
