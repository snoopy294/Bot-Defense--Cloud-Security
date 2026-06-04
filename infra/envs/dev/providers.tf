provider "aws" {
  region = var.region

  # Tag everything so cost/ownership is always attributable — and so a single
  # `terraform destroy` (plus a tag-based sweep) can prove nothing was left running.
  default_tags {
    tags = {
      Project   = "bot-defense-lab"
      ManagedBy = "terraform"
      Env       = "dev"
    }
  }
}
