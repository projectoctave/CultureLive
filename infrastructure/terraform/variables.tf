variable "aws_region" {
  type    = string
  default = "eu-west-3"
}

variable "instance_type" {
  type    = string
  default = "t3.small"
}

variable "key_name" {
  type        = string
  description = "Nom de la clé SSH EC2 existante"
}

variable "ssh_cidr" {
  type        = string
  default     = "0.0.0.0/0"
  description = "CIDR autorisé pour SSH (à restreindre en prod)"
}

variable "domain_name" {
  type        = string
  description = "FQDN pointant vers l'EIP (dashboard + API /api)"
}

variable "letsencrypt_email" {
  type = string
}

variable "repo_clone_url" {
  type        = string
  description = "URL git du repo CultureLive (HTTPS public ou deploy key)"
  default     = ""
}
