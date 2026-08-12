terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Enterprise State Management (S3 & DynamoDB)
  backend "s3" {
    bucket         = "finguard-terraform-state-bucket" 
    key            = "platform/terraform.tfstate"
    region         = "ap-southeast-1"
    dynamodb_table = "finguard-terraform-locks"
    encrypt        = true
  }
}

# Define the AWS Provider and Region
provider "aws" {
  region = "ap-southeast-1"
  
  default_tags {
    tags = {
      Project     = "FinGuard-Agentic"
      Environment = "Production"
      ManagedBy   = "Terraform"
    }
  }
}


# The Overarching Network Boundary (65,536 IPs)
resource "aws_vpc" "finguard_vpc" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "finguard-production-vpc"
  }
}

# Private Subnet in Availability Zone A (256 IPs)
resource "aws_subnet" "private_az1" {
  vpc_id            = aws_vpc.finguard_vpc.id
  cidr_block        = "10.0.1.0/24"
  availability_zone = "ap-southeast-1a"

  tags = {
    Name = "finguard-private-subnet-1a"
  }
}

# Private Subnet in Availability Zone B (256 IPs)
resource "aws_subnet" "private_az2" {
  vpc_id            = aws_vpc.finguard_vpc.id
  cidr_block        = "10.0.2.0/24"
  availability_zone = "ap-southeast-1b"

  tags = {
    Name = "finguard-private-subnet-1b"
  }
}

# Security Group (The Internal Firewall)
resource "aws_security_group" "msk_strict_internal" {
  name        = "msk-internal-firewall"
  description = "Allow internal VPC traffic only for MSK Kafka"
  vpc_id      = aws_vpc.finguard_vpc.id

  # Allow Kafka IAM Authentication Port (9098)
  ingress {
    from_port   = 9098
    to_port     = 9098
    protocol    = "tcp"
    cidr_blocks = [aws_vpc.finguard_vpc.cidr_block]
  }

  # Allow all outbound traffic (so MSK can talk to other AWS services if needed)
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# The Event Broker: Amazon MSK Serverless Cluster
resource "aws_msk_serverless_cluster" "finguard_kafka" {
  cluster_name = "finguard-event-stream"

  vpc_config {
    # Attach to the isolated private subnets
    subnet_ids         = [aws_subnet.private_az1.id, aws_subnet.private_az2.id]
    
    # Apply the strict internal firewall
    security_group_ids = [aws_security_group.msk_strict_internal.id]
  }

  client_authentication {
    sasl {
      iam {
        enabled = true
      }
    }
  }

  tags = {
    Name = "finguard-msk-serverless"
  }
}

# Output the connection string so the Python script can find it
output "kafka_bootstrap_servers" {
  description = "The connection string for the Python Producer"
  value       = aws_msk_serverless_cluster.finguard_kafka.endpoints[0].endpoints
}

# The Digital Identity for the Producer
resource "aws_iam_role" "producer_role" {
  name = "finguard-kafka-producer"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com" 
        }
      }
    ]
  })
}

# The Principle of Least Privilege: Write-Only Access
resource "aws_iam_role_policy" "producer_write_policy" {
  name = "msk-write-only"
  role = aws_iam_role.producer_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "kafka-cluster:Connect",
          "kafka-cluster:DescribeTopic",
          "kafka-cluster:WriteData"
        ]
        Resource = [
          "arn:aws:kafka:ap-southeast-1:*:cluster/finguard-event-stream/*",
          "arn:aws:kafka:ap-southeast-1:*:topic/finguard-event-stream/*"
        ]
      }
    ]
  })
}