output "vpc_id" {
  description = "ID of the VPC"
  value       = aws_vpc.this.id
}

output "vpc_cidr_block" {
  description = "CIDR block of the VPC"
  value       = aws_vpc.this.cidr_block
}

output "public_subnet_ids" {
  description = "List of public subnet IDs"
  value       = [aws_subnet.public_a.id, aws_subnet.public_b.id]
}

output "public_subnet_a_id" {
  description = "ID of public subnet A"
  value       = aws_subnet.public_a.id
}

output "public_subnet_b_id" {
  description = "ID of public subnet B"
  value       = aws_subnet.public_b.id
}

output "private_db_subnet_ids" {
  description = "List of private DB subnet IDs"
  value       = [aws_subnet.private_db_a.id, aws_subnet.private_db_b.id]
}

output "private_db_subnet_a_id" {
  description = "ID of private DB subnet A"
  value       = aws_subnet.private_db_a.id
}

output "private_db_subnet_b_id" {
  description = "ID of private DB subnet B"
  value       = aws_subnet.private_db_b.id
}

output "public_route_table_id" {
  description = "ID of the public route table"
  value       = aws_route_table.public.id
}

output "private_route_table_id" {
  description = "ID of the private route table"
  value       = aws_route_table.private.id
}

output "s3_vpc_endpoint_id" {
  description = "ID of the S3 Gateway VPC Endpoint"
  value       = aws_vpc_endpoint.s3.id
}

