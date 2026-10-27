#!/usr/bin/env bash
# Acceptance checks of a deployed Azure environment (ADR-023):  scripts/azure/verify.sh <demo|pilot>
# The counterpart of verify-aws.sh: it proves the edge, the origin lock, the queues with live consumers,
# and (through Container Apps jobs, which run inside the private network) the database, the models, the
# guardrail, the router, the solver and, in the demo, the MCP gateway path.
set -euo pipefail

ENVIRONMENT=${1:?usage: scripts/azure/verify.sh <demo|pilot>}
case "$ENVIRONMENT" in demo|pilot) ;; *) echo "unknown environment: $ENVIRONMENT" >&2; exit 2 ;; esac
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
# shellcheck source=scripts/azure/lib.sh
source "$ROOT/scripts/azure/lib.sh"

require_commands az terraform curl python
az extension add --name containerapp --upgrade --yes >/dev/null 2>&1 || true
azure_context
tf_init >/dev/null

WEB_URL=$(tf output -raw web_url)
RESOURCE_GROUP=$(tf output -raw resource_group)
NAMESPACE=$(tf output -raw servicebus_namespace)
NAME="secondchance-$ENVIRONMENT"

step "Edge"
wait_for_url "$WEB_URL/api/health" 300
curl -fsS "$WEB_URL/config.json" | python -c '
import json, sys
config = json.load(sys.stdin)
assert config["authMode"] == "oidc" and config["realtimeMode"] == "negotiate", config
assert config["oidc"]["clientId"] and "access_as_user" in config["oidc"]["scope"], config
print("config.json: Entra sign-in and negotiated real time")'
status=$(curl -s -o /dev/null -w '%{http_code}' "$WEB_URL/api/me")
[ "$status" = 401 ] || die "GET /api/me without a token answered $status, expected 401 from the API behind Front Door"
echo "an unauthenticated API call is refused by the API (401), after the edge rewrote /api"

step "Origin lock"
for app in api web; do
  fqdn=$(az containerapp show --name "$NAME-$app" --resource-group "$RESOURCE_GROUP" --query properties.configuration.ingress.fqdn --output tsv)
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "https://$fqdn/config.json" || true)
  case "$code" in
    403|000) echo "$app: a request that skipped Front Door is refused ($code)" ;;
    *) die "$app answered $code to a request that skipped Front Door: the origin lock is not in force" ;;
  esac
done

step "Queues"
queue_count() { az servicebus queue show --namespace-name "$NAMESPACE" --resource-group "$RESOURCE_GROUP" --name "$1" --query "countDetails.$2" --output tsv; }
for queue in jobs notify agents; do
  [ "$(queue_count "$queue" deadLetterMessageCount)" = 0 ] || die "dead-lettered messages in $queue (runbook RB-01)"
done
echo "no dead letters"
job_run "$NAME-ping" 300
waited=0
until [ "$(queue_count notify activeMessageCount)" = 0 ]; do
  [ "$waited" -lt 300 ] || die "the notify queue still holds the check message after 5 minutes: the notifier did not scale up from zero (KEDA identity or role?)"
  sleep 10; waited=$((waited + 10))
done
[ "$(queue_count notify deadLetterMessageCount)" = 0 ] || die "the check message was dead-lettered instead of dropped"
echo "a message sent by the application identity was consumed by a worker scaled up from zero"

step "Private runtime (database, models, guardrail, router, solver)"
job_run "$NAME-check" 600

if [ "$ENVIRONMENT" = demo ]; then
  step "MCP gateway and RAG"
  job_run "$NAME-tools" 300
fi

step "Malware scanning"
storage=$(az storage account list --resource-group "$RESOURCE_GROUP" --query "[0].id" --output tsv)
if scanning=$(az rest --method get --url "https://management.azure.com$storage/providers/Microsoft.Security/defenderForStorageSettings/current?api-version=2022-12-01-preview" \
    --query properties.malwareScanning.onUpload.isEnabled --output tsv 2>/dev/null) && [ "$scanning" = true ]; then
  echo "Defender for Storage scans every upload"
else
  echo "warning: Defender for Storage on-upload malware scanning is not reported as enabled; uploads are parsed unscanned" >&2
fi

printf '\nAzure verification passed: %s\n' "$WEB_URL"
