variable "tenancy_ocid"     { type = string }
variable "user_ocid"        { type = string }
variable "fingerprint"      { type = string }
variable "private_key_path" { type = string }
variable "region"           { type = string }
variable "ad_index" {
  type    = number
  default = 0
}