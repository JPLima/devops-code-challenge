variable "name" {
  description = "Name prefix for the instance and its volumes"
  type        = string
}

variable "subnet_id" {
  description = "Subnet to launch the instance in"
  type        = string
}

variable "security_group_ids" {
  description = "Security groups to attach"
  type        = list(string)
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t3.micro"
}

variable "ami_id" {
  description = "AMI to launch"
  type        = string
  default     = null
}

variable "associate_public_ip_address" {
  description = "Give the instance a public IP. Only meaningful in a public subnet"
  type        = bool
  default     = false
}

variable "root_volume_size" {
  description = "Root volume size in GiB"
  type        = number
  default     = 20
}

variable "kms_key_arn" {
  description = "Customer-managed key for the root volume"
  type        = string
  default     = null
}

variable "iam_instance_profile" {
  description = "Name of an instance profile to attach"
  type        = string
  default     = null
}

variable "user_data" {
  description = "Cloud-init script"
  type        = string
  default     = null
}

variable "detailed_monitoring" {
  description = "One-minute CloudWatch metrics instead of five"
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags applied to the instance and its volumes"
  type        = map(string)
  default     = {}
}
