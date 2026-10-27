#!/usr/bin/env bash
# Deploys SecondChance to Azure in one command (ADR-023):  scripts/azure/deploy.sh <demo|pilot>
# (scripts/deploy.sh <env> does the same when SECONDCHANCE_CLOUD=azure.)
#
# Credentials are never stored here. Locally:  az login   (Terraform and the CLI use that session).
# In GitHub Actions: the OIDC identity from infra/terraform/azure/bootstrap (no secrets).
#
# Required: SECONDCHANCE_ALARM_EMAIL. Optional: SECONDCHANCE_AZURE_LOCATION (default germanywestcentral),
# SECONDCHANCE_STATE_ACCOUNT, SECONDCHANCE_AUTO_APPROVE=1 (CI), SECONDCHANCE_CREATE_APP_REGISTRATIONS=false
# with SECONDCHANCE_OIDC_CLIENT_ID. Needs az (with the containerapp extension), terraform, docker, git, curl.
set -euo pipefail

ENVIRONMENT=${1:?usage: scripts/azure/deploy.sh <demo|pilot>}
case "$ENVIRONMENT" in demo|pilot) ;; *) echo "unknown environment: $ENVIRONMENT" >&2; exit 2 ;; esac
: "${SECONDCHANCE_ALARM_EMAIL:?set SECONDCHANCE_ALARM_EMAIL (alarms and budget alerts)}"
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
# shellcheck source=scripts/azure/lib.sh
source "$ROOT/scripts/azure/lib.sh"

require_commands az terraform docker git curl python
az extension add --name containerapp --upgrade --yes >/dev/null 2>&1 || true

step "Azure identity"
azure_context
az account show --query "{subscription:name, user:user.name}" --output tsv

TAG=$(git -C "$ROOT_NATIVE" rev-parse --short=12 HEAD)
if [ -n "$(git -C "$ROOT_NATIVE" status --porcelain)" ]; then
  [ "$ENVIRONMENT" = pilot ] && die "refusing to deploy uncommitted changes to the pilot"
  TAG="$TAG-dirty-$(date +%s)"
fi
tf_vars
APPROVE=(); [ "${SECONDCHANCE_AUTO_APPROVE:-0}" = 1 ] && APPROVE=(-auto-approve)

step "Terraform init (state in $STATE_ACCOUNT/tfstate)"
tf_init

# --- 1. The registry must exist before the apps that pull from it ---
step "Image registry"
tf apply -input=false -auto-approve -target=module.secondchance.azurerm_container_registry.main "${TF_VARS[@]}"
REGISTRY=$(tf output -raw registry_name)
LOGIN_SERVER=$(tf output -raw registry_login_server)
az acr login --name "$REGISTRY" >/dev/null

step "Images $TAG (app, gateway, web)"
build_push() {   # <repository> <context dir> <dockerfile target>
  local repository=$1 context=$2 target=$3
  if az acr repository show --name "$REGISTRY" --image "$repository:$TAG" >/dev/null 2>&1; then
    echo "$repository:$TAG already pushed"; return
  fi
  # tar stream: works with OneDrive folders on Windows too (scripts/build-images.sh).
  # --provenance=false: one plain image manifest per tag, which Container Apps and the scanner both handle.
  tar -c --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache --exclude=node_modules --exclude=dist -C "$context" . \
    | docker build --platform linux/amd64 --provenance=false --target "$target" -t "$LOGIN_SERVER/$repository:$TAG" -
  docker push "$LOGIN_SERVER/$repository:$TAG"
}
build_push app "$ROOT/api" api
build_push gateway "$ROOT/mcp-gateway" service
build_push web "$ROOT/web" azure

# --- 2. Everything else ---
step "Infrastructure"
tf apply -input=false "${APPROVE[@]}" "${TF_VARS[@]}"
WEB_URL=$(tf output -raw web_url)
RESOURCE_GROUP=$(tf output -raw resource_group)
export RESOURCE_GROUP   # read by job_run in lib.sh

# --- 3. Database: roles (idempotent), migrations, synthetic seed in the demo ---
step "Database"
job_run "secondchance-$ENVIRONMENT-bootstrap" 600
job_run "secondchance-$ENVIRONMENT-migrate" 900
if [ "$ENVIRONMENT" = demo ]; then
  step "Synthetic RAG knowledge"
  job_run "secondchance-$ENVIRONMENT-seed" 1200
fi

# --- 4. Smoke test through the edge ---
step "Smoke test"
wait_for_url "$WEB_URL/api/health"
curl -fsS "$WEB_URL/api/health"; echo

cat <<EOF

SecondChance $ENVIRONMENT is up: $WEB_URL
Next: sign in once in the web app (so Entra creates your account), then make yourself the first platform admin:
  scripts/azure/grant-platform-admin.sh $ENVIRONMENT <your sign-in email or Entra object id>
Check the whole stack with:  scripts/azure/verify.sh $ENVIRONMENT
Mission emails leave from $(tf output -raw notification_sender) (Azure-managed domain: nothing to verify).
EOF
