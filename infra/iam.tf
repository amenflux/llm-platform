resource "oci_identity_group" "architects" {
  compartment_id = var.tenancy_ocid
  name           = "architects"
  description    = "Admin group for infra automation"
}

resource "oci_identity_user" "architect" {
  compartment_id = var.tenancy_ocid
  name           = "architect"
  description    = "Terraform automation user"
  email          = "bouteraa.amen.allah@gmail.com"
}

resource "oci_identity_user_group_membership" "arch_member" {
  group_id = oci_identity_group.architects.id
  user_id  = oci_identity_user.architect.id
}

resource "oci_identity_policy" "architects_admin" {
  compartment_id = var.tenancy_ocid
  name           = "architects-admin"
  description    = "Admin for architects group"
  statements     = ["Allow group architects to manage all-resources in tenancy"]
}

resource "oci_identity_api_key" "architect_key" {
  user_id   = oci_identity_user.architect.id
  key_value = sensitive(file(pathexpand("~/.oci/oci_api_key_public.pem")))
}

output "architect_user_ocid" {
  value = oci_identity_user.architect.id
}
