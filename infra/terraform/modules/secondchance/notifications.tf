# FR-026: mission emails leave from one verified SES identity. The in-app notification is always
# written; email is the second channel. A new account starts in the SES sandbox: until production
# access is granted, SES delivers only to verified recipients and the notifier records the others
# as refused (no retry storm, no DLQ alarm). See docs/deployment.md.

locals {
  notification_sender = var.notification_sender_email != "" ? var.notification_sender_email : var.alarm_email
}

resource "aws_sesv2_email_identity" "sender" {
  email_identity = local.notification_sender
}
