variable "github_repo" {
  description = "GitHub repo in 'owner/name' form, e.g. 'liude/bot-defense-lab'."
  type        = string
}

variable "allowed_refs" {
  description = "Git refs allowed to assume the role (the sub-claim suffixes)."
  type        = list(string)
  default     = ["ref:refs/heads/main"]
}

variable "role_name" {
  description = "Name of the IAM role GitHub Actions assumes."
  type        = string
  default     = "github-actions-deploy"
}

variable "permissions_policy_json" {
  description = "JSON IAM policy granting the deploy role its permissions (scoped by the caller)."
  type        = string
}
