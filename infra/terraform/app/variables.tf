variable "state_bucket" {
  description = "The Terraform state bucket, ehr-rwe-eln-tfstate-<account ID>, to read the foundation stack's outputs."
  type        = string
}

variable "domain_name" {
  description = "The app's own name, served through CloudFront (web_domain.tf). Its Route 53 zone is made in project-template's ops/dns."
  type        = string
  default     = "rwe-workbench.pilotbio.io"
}

variable "image_tag" {
  description = "The app image tag in ECR to run (scripts push it as the git commit)."
  type        = string
}

variable "alert_email" {
  description = "Address that gets the daily token alarm."
  type        = string
}

variable "daily_token_limit" {
  description = "Most tokens /api/agent may bill in one day (US Eastern); the app refuses calls past it."
  type        = number
  default     = 150000
}

variable "agent_enabled" {
  description = "AGENT_ENABLED: false turns /api/agent off (503) and leaves the rest of the app up."
  type        = bool
  default     = true
}

variable "model" {
  description = "MODEL: the Bedrock cross-region inference profile every Claude call uses."
  type        = string
  default     = "us.anthropic.claude-opus-4-6-v1"
}

variable "model_regions" {
  description = "Regions the inference profile routes to (aws bedrock get-inference-profile)."
  type        = list(string)
  default     = ["us-east-1", "us-east-2", "us-west-2"]
}
