resource "oci_core_vcn" "main" {
  compartment_id = oci_identity_compartment.llm_platform.id
  cidr_blocks    = ["10.0.0.0/16"]
  display_name   = "llm-platform-vcn"
  dns_label      = "llmplatform"
}

resource "oci_core_internet_gateway" "igw" {
  compartment_id = oci_identity_compartment.llm_platform.id
  vcn_id         = oci_core_vcn.main.id
  display_name   = "llm-platform-igw"
}

resource "oci_core_route_table" "public" {
  compartment_id = oci_identity_compartment.llm_platform.id
  vcn_id         = oci_core_vcn.main.id
  display_name   = "public-rt"

  route_rules {
    destination       = "0.0.0.0/0"
    network_entity_id = oci_core_internet_gateway.igw.id
  }
}

resource "oci_core_security_list" "public" {
  compartment_id = oci_identity_compartment.llm_platform.id
  vcn_id         = oci_core_vcn.main.id
  display_name   = "public-sl"

  egress_security_rules {
    destination = "0.0.0.0/0"
    protocol    = "all"
  }

  ingress_security_rules {
    source   = "0.0.0.0/0"
    protocol = "6"        # TCP
    tcp_options {
      min = 22            # SSH
      max = 22
    }
  }
}

resource "oci_core_subnet" "public" {
  compartment_id    = oci_identity_compartment.llm_platform.id
  vcn_id            = oci_core_vcn.main.id
  cidr_block        = "10.0.1.0/24"
  display_name      = "public-subnet"
  route_table_id    = oci_core_route_table.public.id
  security_list_ids = [oci_core_security_list.public.id]
  dns_label         = "public"
}
