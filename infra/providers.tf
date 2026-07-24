terraform {
  required_version = ">= 1.5"
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 6.0"
    }
  }
  backend "oci" {
    bucket              = "terraform-state"
    namespace           = "fr6bua3mkjcm"
    key                 = "llm-platform/terraform.tfstate"
    region              = "eu-frankfurt-1"
    config_file_profile = "DEFAULT"
  }

}

provider "oci" {
  tenancy_ocid     = var.tenancy_ocid
  user_ocid        = var.user_ocid
  fingerprint      = var.fingerprint
  private_key_path = var.private_key_path
  region           = var.region
}
