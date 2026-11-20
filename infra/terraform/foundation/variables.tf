variable "budget_email" {
  description = "Address that gets the budget alerts."
  type        = string
}

variable "budget_limit_usd" {
  description = "Monthly spend limit for resources tagged project=ehr-rwe-eln."
  type        = number
  default     = 100
}

variable "lake_admin_arns" {
  description = "IAM role ARNs that administer Lake Formation (your SSO role; later the CI role). Replaces the account's whole admin list."
  type        = list(string)
}
