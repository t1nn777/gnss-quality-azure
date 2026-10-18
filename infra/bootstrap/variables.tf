variable "subscription_id" {
  description = "Azure subscription ID (Azure for Students)."
  type        = string
}

variable "location" {
  type    = string
  default = "southeastasia"
}

variable "prefix" {
  description = "Short lowercase name prefix (letters/digits only)."
  type        = string
  default     = "gnss"
}

variable "tags" {
  type = map(string)
  default = {
    project = "gnss-quality-azure"
    data    = "simulated"
  }
}
