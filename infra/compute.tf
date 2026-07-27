data "oci_core_images" "ubuntu" {
  compartment_id           = var.tenancy_ocid
  operating_system         = "Canonical Ubuntu"
  operating_system_version = "22.04"
  shape                    = "VM.Standard.A1.Flex"
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
}

resource "oci_core_instance" "server" {
  compartment_id      = oci_identity_compartment.llm_platform.id
  availability_domain = data.oci_identity_availability_domains.ads.availability_domains[var.ad_index].name
  shape               = "VM.Standard.A1.Flex"
  display_name        = "llm-platform-server"

  shape_config {
    ocpus         = 4
    memory_in_gbs = 24
  }

  source_details {
    source_type = "image"
    source_id   = data.oci_core_images.ubuntu.images[0].id
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.public.id
    assign_public_ip = true
  }

  metadata = {
    ssh_authorized_keys = file(pathexpand("~/.ssh/id_rsa.pub"))
  }
}

output "instance_public_ip" {
  value = oci_core_instance.server.public_ip
}
