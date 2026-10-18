# Aurora PostgreSQL Serverless v2 (ADR-001, ADR-004): RLS, pgvector, PostGIS, FTS.
# Applications authenticate with IAM tokens; only the migrate function reads the master
# secret, which RDS generates and rotates in Secrets Manager.

resource "aws_db_subnet_group" "main" {
  name       = var.name
  subnet_ids = aws_subnet.private[*].id
}
resource "aws_rds_cluster" "main" {
  cluster_identifier                  = var.name
  engine                              = "aurora-postgresql"
  engine_mode                         = "provisioned"
  engine_version                      = var.aurora_engine_version
  database_name                       = "secondchance"
  master_username                     = "secondchance_master"
  manage_master_user_password         = true
  master_user_secret_kms_key_id       = aws_kms_key.main.key_id
  iam_database_authentication_enabled = true
  storage_encrypted                   = true
  kms_key_id                          = aws_kms_key.main.arn
  db_subnet_group_name                = aws_db_subnet_group.main.name
  vpc_security_group_ids              = [aws_security_group.db.id]
  backup_retention_period             = var.backup_retention_days
  preferred_backup_window             = "02:00-03:00"
  copy_tags_to_snapshot               = true
  deletion_protection                 = var.deletion_protection
  skip_final_snapshot                 = !var.deletion_protection
  final_snapshot_identifier           = var.deletion_protection ? "${var.name}-final" : null
  enabled_cloudwatch_logs_exports     = ["postgresql"]

  serverlessv2_scaling_configuration {
    min_capacity             = var.aurora_min_acu
    max_capacity             = var.aurora_max_acu
    seconds_until_auto_pause = var.aurora_min_acu == 0 ? 900 : null
  }
}

resource "aws_rds_cluster_instance" "main" {
  count               = var.aurora_instances
  identifier          = "${var.name}-${count.index}"
  cluster_identifier  = aws_rds_cluster.main.id
  instance_class      = "db.serverless"
  engine              = aws_rds_cluster.main.engine
  engine_version      = aws_rds_cluster.main.engine_version
  publicly_accessible = false
}

locals {
  db_cluster_host = aws_rds_cluster.main.endpoint
  db_cluster_user_arn = {
    for user in ["secondchance_app", "secondchance_migrator", "secondchance_maintenance"] :
    user => "arn:${local.partition}:rds-db:${var.region}:${local.account_id}:dbuser:${aws_rds_cluster.main.cluster_resource_id}/${user}"
  }
}

# Lambda concurrency must terminate at a pool, not at PostgreSQL. End-to-end IAM
# authentication keeps the existing short-lived-token model and requires no per-user secret.
data "aws_iam_policy_document" "rds_proxy_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["rds.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "rds_proxy" {
  name               = "${var.name}-rds-proxy"
  assume_role_policy = data.aws_iam_policy_document.rds_proxy_trust.json
}

resource "aws_iam_role_policy" "rds_proxy" {
  role = aws_iam_role.rds_proxy.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "rds-db:connect"
      Resource = values(local.db_cluster_user_arn)
    }]
  })
}

resource "aws_db_proxy" "main" {
  name                   = var.name
  engine_family          = "POSTGRESQL"
  default_auth_scheme    = "IAM_AUTH"
  require_tls            = true
  debug_logging          = false
  idle_client_timeout    = 1800
  role_arn               = aws_iam_role.rds_proxy.arn
  vpc_subnet_ids         = aws_subnet.private[*].id
  vpc_security_group_ids = [aws_security_group.rds_proxy.id]
}

resource "aws_db_proxy_default_target_group" "main" {
  db_proxy_name = aws_db_proxy.main.name
  connection_pool_config {
    connection_borrow_timeout    = 30
    max_connections_percent      = 80
    max_idle_connections_percent = 40
  }
}

resource "aws_db_proxy_target" "main" {
  db_proxy_name         = aws_db_proxy.main.name
  target_group_name     = aws_db_proxy_default_target_group.main.name
  db_cluster_identifier = aws_rds_cluster.main.id
}

locals {
  db_proxy_resource_id = regex("prx-[0-9a-f]+", aws_db_proxy.main.arn)
  db_user_arn = {
    for user in keys(local.db_cluster_user_arn) :
    user => "arn:${local.partition}:rds-db:${var.region}:${local.account_id}:dbuser:${local.db_proxy_resource_id}/${user}"
  }
  db_url = {
    for user in keys(local.db_user_arn) :
    user => "postgresql+psycopg://${user}@${aws_db_proxy.main.endpoint}:5432/secondchance"
  }
}

resource "aws_dynamodb_table" "mcp_rate_limit" {
  name         = "${var.name}-mcp-rate-limit"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "bucket"

  attribute {
    name = "bucket"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = var.environment == "pilot"
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.main.arn
  }
}
