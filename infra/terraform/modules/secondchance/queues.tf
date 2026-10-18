# jobs, notify, agents, each with a DLQ after 5 receives (ADR-005, ADR-011). Messages hold
# identifiers only, so SQS-managed encryption is enough.

resource "aws_sqs_queue" "dlq" {
  for_each                  = local.queues
  name                      = "${var.name}-${each.key}-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "main" {
  for_each                   = local.queues
  name                       = "${var.name}-${each.key}"
  visibility_timeout_seconds = each.value.visibility
  message_retention_seconds  = 345600
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq[each.key].arn
    maxReceiveCount     = 5
  })
}
