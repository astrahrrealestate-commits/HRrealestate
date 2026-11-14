output "bucket_id" {
  description = "S3 Bucket Name/ID"
  value       = aws_s3_bucket.this.id
}

output "bucket_arn" {
  description = "S3 Bucket ARN"
  value       = aws_s3_bucket.this.arn
}

output "bucket_domain_name" {
  description = "S3 Bucket Domain Name"
  value       = aws_s3_bucket.this.bucket_domain_name
}

output "bucket_regional_domain_name" {
  description = "S3 Bucket Regional Domain Name"
  value       = aws_s3_bucket.this.bucket_regional_domain_name
}

