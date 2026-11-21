# One VPC. Databases sit in private subnets with no route to the internet. The load balancer and
# app tasks (step 4) go in public subnets, which saves a NAT gateway (~$33/month) and interface
# endpoints (~$7/month each per zone). The S3 gateway endpoint is free.

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, 3)
}

resource "aws_vpc" "main" {
  cidr_block           = "10.20.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = local.name }
}

# Three zones: Redshift Serverless wants subnets in three Availability Zones.
resource "aws_subnet" "private" {
  count             = 3
  vpc_id            = aws_vpc.main.id
  availability_zone = local.azs[count.index]
  cidr_block        = cidrsubnet(aws_vpc.main.cidr_block, 4, count.index)

  tags = { Name = "${local.name}-private-${local.azs[count.index]}" }
}

# Two zones: the minimum a load balancer accepts.
# trivy:ignore:AWS-0164 Tasks need a public IP to reach ECR and AWS APIs without a NAT gateway; only the app runs here.
resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  availability_zone       = local.azs[count.index]
  cidr_block              = cidrsubnet(aws_vpc.main.cidr_block, 4, 8 + count.index)
  map_public_ip_on_launch = true

  tags = { Name = "${local.name}-public-${local.azs[count.index]}" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = local.name }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${local.name}-public" }
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# No default route: nothing in a private subnet reaches the internet.
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${local.name}-private" }
}

resource "aws_route_table_association" "private" {
  count          = 3
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${local.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id, aws_route_table.public.id]

  tags = { Name = "${local.name}-s3" }
}

# Security groups. Each database accepts its port only from the app and batch tasks' group,
# which step 4 attaches to the containers.
resource "aws_security_group" "app" {
  name        = "${local.name}-app"
  description = "App and batch tasks"
  vpc_id      = aws_vpc.main.id
}

# Outbound is HTTPS to anywhere plus the two database ports. Every external call the code makes
# (AWS APIs, Bedrock, NCBI, gnomAD, Ensembl) is HTTPS; DNS goes to the VPC resolver, which
# security groups don't filter.
# trivy:ignore:AWS-0104 HTTPS only, to public APIs (NCBI, gnomAD, Ensembl) whose addresses change; no NAT to filter at.
resource "aws_vpc_security_group_egress_rule" "app_https" {
  security_group_id = aws_security_group.app.id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
  description       = "HTTPS to AWS APIs, Bedrock, NCBI, gnomAD, Ensembl"
}

resource "aws_vpc_security_group_egress_rule" "app_to_aurora" {
  security_group_id            = aws_security_group.app.id
  referenced_security_group_id = aws_security_group.aurora.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  description                  = "Postgres to Aurora"
}

resource "aws_vpc_security_group_egress_rule" "app_to_redshift" {
  security_group_id            = aws_security_group.app.id
  referenced_security_group_id = aws_security_group.redshift.id
  ip_protocol                  = "tcp"
  from_port                    = 5439
  to_port                      = 5439
  description                  = "Redshift to the workgroup"
}

resource "aws_security_group" "aurora" {
  name        = "${local.name}-aurora"
  description = "Aurora PostgreSQL"
  vpc_id      = aws_vpc.main.id
}

resource "aws_vpc_security_group_ingress_rule" "aurora_from_app" {
  security_group_id            = aws_security_group.aurora.id
  referenced_security_group_id = aws_security_group.app.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  description                  = "Postgres from app and batch tasks"
}

resource "aws_security_group" "redshift" {
  name        = "${local.name}-redshift"
  description = "Redshift Serverless"
  vpc_id      = aws_vpc.main.id
}

resource "aws_vpc_security_group_ingress_rule" "redshift_from_app" {
  security_group_id            = aws_security_group.redshift.id
  referenced_security_group_id = aws_security_group.app.id
  ip_protocol                  = "tcp"
  from_port                    = 5439
  to_port                      = 5439
  description                  = "Redshift from app and batch tasks"
}
