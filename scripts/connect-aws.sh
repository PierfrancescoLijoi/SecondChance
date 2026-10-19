#!/usr/bin/env bash
# One entrypoint: preflight, idempotent account bootstrap, deployment and verification.
set -euo pipefail
ENVIRONMENT=${1:-demo}
case "$ENVIRONMENT" in demo|pilot) ;; *) echo "usage: scripts/connect-aws.sh <demo|pilot>" >&2; exit 2 ;; esac
: "${SECONDCHANCE_ALARM_EMAIL:?set SECONDCHANCE_ALARM_EMAIL}"
ROOT=$(cd "$(dirname "$0")/.." && pwd)
# Native Windows tools (aws.exe, python.exe) cannot open MSYS /tmp paths: use C:/... temp files.
if command -v cygpath >/dev/null; then TMPDIR=$(cygpath -m "${TMPDIR:-/tmp}"); export TMPDIR; fi
REGION=${AWS_REGION:-eu-central-1}
MODEL=${SECONDCHANCE_BEDROCK_MODEL:-eu.anthropic.claude-haiku-5-5}
for command in aws docker git curl python; do command -v "$command" >/dev/null || { echo "missing command: $command" >&2; exit 1; }; done
docker info >/dev/null
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
aws sts get-caller-identity --query Arn --output text
# Lambda keeps 100 executions unreserved and new accounts may start with a quota of 10: the pilot
# reserves 25 (API 20, MCP gateway 5), the demo reserves nothing but can throttle under a tiny quota.
LAMBDA_QUOTA=$(aws lambda get-account-settings --region "$REGION" --query AccountLimit.ConcurrentExecutions --output text)
if [ "$ENVIRONMENT" = pilot ] && [ "$LAMBDA_QUOTA" -lt 125 ]; then
  echo "Lambda concurrency quota is $LAMBDA_QUOTA; the pilot needs at least 125. Request 1000 in Service Quotas (L-B99A9384)." >&2
  exit 1
fi
[ "$LAMBDA_QUOTA" -ge 50 ] || echo "warning: Lambda concurrency quota is $LAMBDA_QUOTA; the demo may throttle. Request 1000 in Service Quotas (L-B99A9384)." >&2
PROFILE_MODELS=$(aws bedrock get-inference-profile --region "$REGION" \
  --inference-profile-identifier "$MODEL" --query 'models[].modelArn' --output text)
[ -n "$PROFILE_MODELS" ] || { echo "inference profile has no destination models: $MODEL" >&2; exit 1; }
for model_arn in $PROFILE_MODELS; do
  destination_region=$(printf '%s' "$model_arn" | cut -d: -f4)
  case "$destination_region" in
    eu-*) ;;
    *) echo "inference profile has a non-EU destination: $model_arn" >&2; exit 1 ;;
  esac
done
# Existence is not enough for third-party models: a real minimal invocation catches
# a missing Anthropic first-time-use form or AWS Marketplace entitlement before Terraform runs.
if ! aws bedrock-runtime converse --region "$REGION" --model-id "$MODEL" \
  --messages '[{"role":"user","content":[{"text":"Reply OK"}]}]' \
  --inference-config '{"maxTokens":4,"temperature":0}' >/dev/null; then
  echo "Bedrock model $MODEL is not invocable. Claude needs the Anthropic first-time-use form and, being sold through" >&2
  echo "AWS Marketplace, a payment method on the account. Without one, use an Amazon model (no Marketplace):" >&2
  echo "  SECONDCHANCE_BEDROCK_MODEL=eu.amazon.nova-lite-v1:0   (Windows: -BedrockModel eu.amazon.nova-lite-v1:0)" >&2
  exit 1
fi
BEDROCK_CHECK=$(mktemp)
trap 'rm -f "$BEDROCK_CHECK"' EXIT
aws bedrock-runtime invoke-model --region "$REGION" --model-id amazon.titan-embed-text-v2:0 \
  --content-type application/json --accept application/json --cli-binary-format raw-in-base64-out \
  --body '{"inputText":"SecondChance deployment check","dimensions":1024,"normalize":true}' "$BEDROCK_CHECK" >/dev/null
aws rds describe-orderable-db-instance-options --region "$REGION" --engine aurora-postgresql --engine-version 16.6 --db-instance-class db.serverless --query 'length(OrderableDBInstanceOptions)' --output text | grep -qv '^0$'
STATE_BUCKET=${SECONDCHANCE_STATE_BUCKET:-secondchance-tfstate-$ACCOUNT}
export SECONDCHANCE_STATE_BUCKET="$STATE_BUCKET" AWS_REGION="$REGION" MSYS_NO_PATHCONV=1
host_path() { if command -v cygpath >/dev/null; then cygpath -w "$1"; else echo "$1"; fi; }
tf_bootstrap() {
  if command -v terraform >/dev/null; then terraform -chdir="$ROOT/infra/terraform/bootstrap" "$@"
  else docker run --rm -i -v "$(host_path "$ROOT"):/repo" -v "$(host_path "$HOME/.aws"):/root/.aws:ro" -e AWS_PROFILE -e AWS_REGION="$REGION" -w /repo/infra/terraform/bootstrap hashicorp/terraform:1.16.5 "$@"; fi
}
if ! aws s3api head-bucket --bucket "$STATE_BUCKET" 2>/dev/null; then
  tf_bootstrap init -input=false
  tf_bootstrap apply -input=false -auto-approve -var "github_repository=${SECONDCHANCE_GITHUB_REPOSITORY:-}"
fi
bash "$ROOT/scripts/deploy.sh" "$ENVIRONMENT"
bash "$ROOT/scripts/verify-aws.sh" "$ENVIRONMENT"
