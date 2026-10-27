#!/usr/bin/env bash
# Shared helpers of the Azure scripts (ADR-023). Sourced, never executed.
# shellcheck shell=bash

: "${ROOT:?the sourcing script sets ROOT}"
: "${ENVIRONMENT:?the sourcing script sets ENVIRONMENT}"

export MSYS_NO_PATHCONV=1   # Git Bash on Windows: keep resource ids and paths as they are
if command -v cygpath >/dev/null; then TMPDIR=$(cygpath -m "${TMPDIR:-/tmp}"); export TMPDIR; fi

# Native Windows programs (terraform.exe, git.exe) do not understand /c/... paths when MSYS conversion is off.
native_path() { if command -v cygpath >/dev/null; then cygpath -m "$1"; else printf '%s' "$1"; fi; }

LOCATION=${SECONDCHANCE_AZURE_LOCATION:-germanywestcentral}
TF_DIR=$(native_path "$ROOT/infra/terraform/azure/envs/$ENVIRONMENT")
ROOT_NATIVE=$(native_path "$ROOT")
export ROOT_NATIVE   # read by deploy.sh

step() { printf '\n== %s\n' "$*"; }
die() { printf '%s\n' "$*" >&2; exit 1; }

require_commands() {
  for command in "$@"; do command -v "$command" >/dev/null || die "missing command: $command"; done
}

# The subscription Terraform and the CLI act on. Credentials are never stored here: locally `az login`,
# in GitHub Actions the OIDC login of azure/login (no secret).
azure_context() {
  SUBSCRIPTION=${AZURE_SUBSCRIPTION_ID:-$(az account show --query id --output tsv 2>/dev/null || true)}
  [ -n "$SUBSCRIPTION" ] || die "not signed in: run 'az login' (or set AZURE_SUBSCRIPTION_ID in CI)"
  az account set --subscription "$SUBSCRIPTION"
  TENANT=$(az account show --query tenantId --output tsv)
  # Must equal the name infra/terraform/azure/bootstrap derives from the subscription id.
  STATE_ACCOUNT=${SECONDCHANCE_STATE_ACCOUNT:-sctfstate$(printf '%s' "$SUBSCRIPTION" | sha256sum | cut -c1-8)}
  STATE_GROUP=${SECONDCHANCE_STATE_GROUP:-rg-secondchance-tfstate}
  export ARM_SUBSCRIPTION_ID="$SUBSCRIPTION" ARM_TENANT_ID="$TENANT"
  # Terraform and its backend use the CLI session: the signed-in user locally, the federated identity that
  # azure/login established in GitHub Actions.
}

tf() {
  command -v terraform >/dev/null || die "terraform is required for Azure deployments (the CLI sign-in cannot be mounted into a container): winget install Hashicorp.Terraform"
  terraform -chdir="$TF_DIR" "$@"
}

tf_init() {
  tf init -input=false -reconfigure \
    -backend-config="resource_group_name=$STATE_GROUP" \
    -backend-config="storage_account_name=$STATE_ACCOUNT" \
    -backend-config="container_name=tfstate"
}

tf_vars() {
  TF_VARS=(-var "subscription_id=$SUBSCRIPTION" -var "location=$LOCATION" -var "image_tag=${TAG:-destroy}" -var "alarm_email=${SECONDCHANCE_ALARM_EMAIL:-destroy@example.invalid}")
  # The models the preflight checked are the models the deployment gets (scripts/azure/connect.sh).
  if [ -n "${SECONDCHANCE_CHAT_MODEL_JSON:-}" ]; then TF_VARS+=(-var "chat_model=$SECONDCHANCE_CHAT_MODEL_JSON"); fi
  if [ -n "${SECONDCHANCE_EMBEDDING_MODEL_JSON:-}" ]; then TF_VARS+=(-var "embedding_model=$SECONDCHANCE_EMBEDDING_MODEL_JSON"); fi
  if [ "$ENVIRONMENT" = demo ] && [ -n "${SECONDCHANCE_WEB_PUBSUB_SKU:-}" ]; then TF_VARS+=(-var "web_pubsub_sku=$SECONDCHANCE_WEB_PUBSUB_SKU"); fi
  if [ "${SECONDCHANCE_CREATE_APP_REGISTRATIONS:-true}" = false ]; then
    TF_VARS+=(-var "create_app_registrations=false" -var "oidc_client_id=${SECONDCHANCE_OIDC_CLIENT_ID:?set SECONDCHANCE_OIDC_CLIENT_ID when app registrations are not created}")
  fi
}

# job_run <job> [--wait-seconds N]: starts a Container Apps job, waits for its execution to finish and fails
# unless it Succeeded. The execution's status is the verdict; its log line (JSON) is printed when available.
job_run() {
  local job=$1 timeout=${2:-900} execution status waited=0
  execution=$(az containerapp job start --name "$job" --resource-group "$RESOURCE_GROUP" --query name --output tsv)
  printf 'job %s: execution %s' "$job" "$execution"
  while :; do
    status=$(az containerapp job execution show --name "$job" --resource-group "$RESOURCE_GROUP" \
      --job-execution-name "$execution" --query properties.status --output tsv)
    case "$status" in
      Succeeded) printf ' -> Succeeded\n'; break ;;
      Failed|Stopped|Degraded) printf ' -> %s\n' "$status"; job_logs "$job" "$execution"; return 1 ;;
    esac
    [ "$waited" -lt "$timeout" ] || { printf ' -> still %s after %ss\n' "$status" "$timeout"; job_logs "$job" "$execution"; return 1; }
    sleep 10; waited=$((waited + 10)); printf '.'
  done
  job_logs "$job" "$execution" || true
}

# Log Analytics ingests a minute or two after the run: best effort, never a verdict.
job_logs() {
  local job=$1 execution=$2
  for _ in 1 2 3; do
    if az containerapp job logs show --name "$job" --resource-group "$RESOURCE_GROUP" --container "$job" \
        --execution "$execution" --format text --tail 40 2>/dev/null | sed 's/^/    /'; then return 0; fi
    sleep 15
  done
  return 0
}

# wait_for_url <url> [seconds]: Front Door takes ten minutes or more to publish a new endpoint worldwide.
wait_for_url() {
  local url=$1 limit=${2:-1500} waited=0
  until curl -fsS -o /dev/null --max-time 20 "$url"; do
    [ "$waited" -lt "$limit" ] || die "$url did not answer after ${limit}s (Front Door can need up to 20 minutes after the first apply)"
    sleep 15; waited=$((waited + 15))
  done
}
