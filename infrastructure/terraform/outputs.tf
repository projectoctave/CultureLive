output "public_ip" {
  description = "Elastic IP — pointer le DNS A de domain_name vers cette IP"
  value       = aws_eip.culturelive.public_ip
}

output "instance_id" {
  value = aws_instance.culturelive.id
}

output "ssh_hint" {
  value = "ssh -i <your-key.pem> ubuntu@${aws_eip.culturelive.public_ip}"
}
