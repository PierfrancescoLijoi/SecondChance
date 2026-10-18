#!/usr/bin/env bash
# Removes an SecondChance environment:  scripts/destroy.sh <demo|pilot>
# The pilot keeps deletion protection on Aurora and Cognito: turn it off deliberately first.
set -euo pipefail

ENVIRONMENT=${1:?usage: scripts/destroy.sh <demo|pilot>}
REGION=eu-central-1
ROOT=$(cd "$(dirname "$0")/.." && pwd)
export MSYS_NO_PATHCONV=1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
STATE_BUCKET=${SECONDCHANCE_STATE_BUCKET:-secondchance-tfstate-$ACCOUNT}

if [ "${SECONDCHANCE_AUTO_APPROVE:-0}" != 1 ]; then
  read -r -p "Type the environment name to destroy it ($ENVIRONMENT): " answer
  [ "$answer" = "$ENVIRONMENT" ] || { echo "aborted"; exit 1; }
fi

host_path() { if command -v cygpath >/dev/null; then cygpath -w "$1"; else echo "$1"; fi; }
tf() {
  if command -v terraform >/dev/null; then
    terraform -chdir="$ROOT/infra/terraform/envs/$ENVIRONMENT" "$@"
  else
    docker run --rm -i -v "$(host_path "$ROOT"):/repo" -v "$(host_path "$HOME/.aws"):/root/.aws:ro" \
      -e AWS_PROFILE -e AWS_REGION="$REGION" -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_SESSION_TOKEN \
      -w "/repo/infra/terraform/envs/$ENVIRONMENT" hashicorp/terraform:1.16.5 "$@"
  fi
}

tf init -input=false -reconfigure -backend-config="bucket=$STATE_BUCKET" -backend-config="region=$REGION"
tf destroy -input=false -auto-approve -var "image_tag=destroy" -var "alarm_email=destroy@example.invalid"
echo "Destroyed. Check for leftovers: aws resourcegroupstaggingapi get-resources --tag-filters Key=project,Values=secondchance --region $REGION"
