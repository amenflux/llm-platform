data "oci_identity_availability_domains" "ads" {
  compartment_id = var.tenancy_ocid
}

resource "oci_identity_compartment" "llm_platform" {
  compartment_id = var.tenancy_ocid   # parent = the root/tenancy
  name           = "llm-platform"
  description    = "Compartment for the LLM platform project"
  enable_delete  = true               # lets `terraform destroy` remove it later
}

output "compartment_id" {
  value = oci_identity_compartment.llm_platform.id
}

data "oci_objectstorage_namespace" "ns" {
  compartment_id = var.tenancy_ocid
}

resource "oci_objectstorage_bucket" "tf_state" {
  compartment_id = oci_identity_compartment.llm_platform.id
  namespace      = data.oci_objectstorage_namespace.ns.namespace
  name           = "terraform-state"
}