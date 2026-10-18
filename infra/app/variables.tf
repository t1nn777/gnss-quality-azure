variable "subscription_id" {
  description = "Azure subscription ID."
  type        = string
}

variable "location" {
  type    = string
  default = "southeastasia"
}

variable "prefix" {
  description = "Short lowercase name prefix."
  type        = string
  default     = "gnss"
}

variable "github_owner" {
  description = "GitHub user or organisation that owns the repo."
  type        = string
}

variable "github_repo" {
  description = "GitHub repository name, e.g. gnss-quality-azure."
  type        = string
}

variable "tfstate_storage_account_id" {
  description = "Resource ID of the Terraform state storage account (output storage_account_id of infra/bootstrap)."
  type        = string
}

variable "tags" {
  type = map(string)
  default = {
    project = "gnss-quality-azure"
    data    = "simulated"
  }
}
