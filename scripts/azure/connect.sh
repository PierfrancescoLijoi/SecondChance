#!/usr/bin/env bash
# One entrypoint for Azure (ADR-023):  scripts/azure/connect.sh <demo|pilot>
# preflight against the real subscription -> idempotent bootstrap -> deployment -> verification.
#
# The offline tests (terraform test, pytest) prove the code and the plan; this preflight proves what only
# the subscription knows: registered providers, the models and SKUs the region really offers, free quota,
# names that are still free, and whether the signed-in identity may write to Entra. It changes nothing
# except registering resource providers, and stops before Terraform when something would fail later.
set -euo pipefail

ENVIRONMENT=${1:-demo}
case "$ENVIRONMENT" in demo|pilot) ;; *) echo "usage: scripts/azure/connect.sh <demo|pilot>" >&2; exit 2 ;; esac
: "${SECONDCHANCE_ALARM_EMAIL:?set SECONDCHANCE_ALARM_EMAIL}"
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
# shellcheck source=scripts/azure/lib.sh
source "$ROOT/scripts/azure/lib.sh"

require_commands az terraform docker git curl python
docker info >/dev/null 2>&1 || die "docker is not running (the images are built locally)"
az extension add --name containerapp --upgrade --yes >/dev/null 2>&1 || true

step "Azure identity"
azure_context
az account show --query "{subscription:name, id:id, user:user.name}" --output tsv
NAME="secondchance-$ENVIRONMENT"

step "Resource providers"
for provider in Microsoft.App Microsoft.Authorization Microsoft.Cdn Microsoft.CognitiveServices Microsoft.Communication \
    Microsoft.Consumption Microsoft.ContainerRegistry Microsoft.DBforPostgreSQL Microsoft.EventGrid Microsoft.Insights Microsoft.ManagedIdentity \
    Microsoft.Network Microsoft.OperationalInsights Microsoft.Security Microsoft.ServiceBus Microsoft.SignalRService Microsoft.Storage; do
  state=$(az provider show --namespace "$provider" --query registrationState --output tsv 2>/dev/null || echo NotRegistered)
  if [ "$state" != Registered ]; then echo "registering $provider"; az provider register --namespace "$provider" --wait >/dev/null; fi
done
echo "all providers registered"

step "Models in $LOCATION"
# A model name and version the region offers, as a deployment in the EU data zone. Both are variables of the
# module, so a different model is a one-line choice, not a code change.
CHAT_MODEL=${SECONDCHANCE_CHAT_MODEL:-gpt-4.1-mini}
CHAT_VERSION=${SECONDCHANCE_CHAT_MODEL_VERSION:-2025-04-14}
EMBEDDING_MODEL=${SECONDCHANCE_EMBEDDING_MODEL:-text-embedding-3-large}
EMBEDDING_VERSION=${SECONDCHANCE_EMBEDDING_MODEL_VERSION:-1}
MODEL_SKU=${SECONDCHANCE_MODEL_SKU:-DataZoneStandard}
CAPACITY=${SECONDCHANCE_MODEL_CAPACITY:-30}
MODELS_JSON=$(mktemp); USAGE_JSON=$(mktemp)
trap 'rm -f "$MODELS_JSON" "$USAGE_JSON"' EXIT
az cognitiveservices model list --location "$LOCATION" --output json >"$MODELS_JSON"
az cognitiveservices usage list --location "$LOCATION" --output json >"$USAGE_JSON" 2>/dev/null || echo '[]' >"$USAGE_JSON"
pick_model() {   # <name> <version> -> {"name":..,"version":..,"sku":..,"capacity":..} on stdout, or exit 1
  python - "$MODELS_JSON" "$USAGE_JSON" "$1" "$2" "$MODEL_SKU" "$CAPACITY" <<'PY'
import json, sys
models_file, usage_file, name, version, sku, capacity = sys.argv[1:7]
capacity = int(capacity)
items = [m["model"] for m in json.load(open(models_file, encoding="utf-8")) if m.get("kind") == "OpenAI" and m["model"].get("name") == name]
offered = [m for m in items if any(s.get("name") == sku for s in m.get("skus", []))]
if not offered:
    others = sorted({m["model"]["name"] for m in json.load(open(models_file, encoding="utf-8"))
                     if m.get("kind") == "OpenAI" and any(s.get("name") == sku for s in m["model"].get("skus", []))})
    sys.exit(f"{name} is not offered with the {sku} SKU in this region. Offered with {sku}: {', '.join(others) or 'none'}. "
             "Pick one with SECONDCHANCE_CHAT_MODEL / SECONDCHANCE_EMBEDDING_MODEL (and the _VERSION variable), or another region.")
chosen = next((m for m in offered if m.get("version") == version), None)
if chosen is None:
    chosen = sorted(offered, key=lambda m: m.get("version", ""))[-1]
    print(f"note: {name} {version} is not offered; using {chosen['version']}", file=sys.stderr)
usage = {u["name"]["value"]: u for u in json.load(open(usage_file, encoding="utf-8"))}
key = f"OpenAI.{sku}.{name}"
if key in usage:
    free = float(usage[key]["limit"]) - float(usage[key]["currentValue"])
    if free < capacity:
        sys.exit(f"quota for {key}: {free:g} free, {capacity} needed. Request more in the portal (Quotas) or lower SECONDCHANCE_MODEL_CAPACITY.")
print(json.dumps({"name": name, "version": chosen["version"], "sku": sku, "capacity": capacity}))
PY
}
SECONDCHANCE_CHAT_MODEL_JSON=$(pick_model "$CHAT_MODEL" "$CHAT_VERSION")
SECONDCHANCE_EMBEDDING_MODEL_JSON=$(pick_model "$EMBEDDING_MODEL" "$EMBEDDING_VERSION")
export SECONDCHANCE_CHAT_MODEL_JSON SECONDCHANCE_EMBEDDING_MODEL_JSON
echo "chat:      $SECONDCHANCE_CHAT_MODEL_JSON"
echo "embedding: $SECONDCHANCE_EMBEDDING_MODEL_JSON"

step "Database tier in $LOCATION"
if [ "$ENVIRONMENT" = pilot ]; then POSTGRES_SKU=Standard_D2ds_v5; else POSTGRES_SKU=Standard_B1ms; fi
az postgres flexible-server list-skus --location "$LOCATION" --output json | python -c '
import json, sys
wanted = sys.argv[1]
def names(node):
    if isinstance(node, dict):
        if node.get("name"): yield node["name"]
        for value in node.values(): yield from names(value)
    elif isinstance(node, list):
        for value in node: yield from names(value)
if wanted not in set(names(json.load(sys.stdin))):
    sys.exit(f"PostgreSQL flexible server {wanted} is not offered in this region/subscription")
print(f"{wanted} is offered")' "$POSTGRES_SKU"

step "Names that must be free"
if [ "$(az group exists --name "rg-$NAME")" = true ]; then
  echo "rg-$NAME exists: this is a re-deploy, the names are ours"
else
  suffix=$(printf '%s' "$SUBSCRIPTION/$NAME" | sha256sum | cut -c1-6)
  compact=${NAME//-/}
  acr="$compact$suffix"
  storage="${compact:0:12}$suffix"
  [ "$(az acr check-name --name "$acr" --query nameAvailable --output tsv)" = true ] || die "container registry name $acr is taken"
  [ "$(az storage account check-name --name "$storage" --query nameAvailable --output tsv)" = true ] || die "storage account name $storage is taken"
  echo "$acr and $storage are free"
fi

step "Free-tier limits"
if [ "${SECONDCHANCE_WEB_PUBSUB_SKU:-Free_F1}" = Free_F1 ] && [ "$ENVIRONMENT" = demo ]; then
  others=$(az resource list --resource-type Microsoft.SignalRService/webPubSub --query "[?sku.name=='Free_F1' && resourceGroup!='rg-$NAME'] | length(@)" --output tsv 2>/dev/null || echo 0)
  [ "${others:-0}" = 0 ] || die "this subscription already has a Free Web PubSub instance (one is allowed): set SECONDCHANCE_WEB_PUBSUB_SKU=Standard_S1"
fi
echo "ok"

step "Microsoft Entra"
# shellcheck disable=SC2016  # $top is Graph's query option, not a shell variable
if ! az rest --method get --url 'https://graph.microsoft.com/v1.0/applications?$top=1' --output none 2>/dev/null; then
  echo "warning: this identity cannot read app registrations. Without Entra rights set SECONDCHANCE_CREATE_APP_REGISTRATIONS=false" >&2
  echo "         and SECONDCHANCE_OIDC_CLIENT_ID=<an app registration you created>; see docs/deployment-azure.md." >&2
fi

step "Terraform state"
if ! az storage account show --name "$STATE_ACCOUNT" --resource-group "$STATE_GROUP" --output none 2>/dev/null; then
  echo "state account $STATE_ACCOUNT does not exist: running the bootstrap (needs Entra and subscription owner rights)"
  BOOTSTRAP_DIR=$(native_path "$ROOT/infra/terraform/azure/bootstrap")
  terraform -chdir="$BOOTSTRAP_DIR" init -input=false
  terraform -chdir="$BOOTSTRAP_DIR" apply -input=false -auto-approve \
    -var "subscription_id=$SUBSCRIPTION" -var "location=$LOCATION" -var "github_repository=${SECONDCHANCE_GITHUB_REPOSITORY:-}"
else
  echo "state account $STATE_ACCOUNT exists"
fi

export SECONDCHANCE_AZURE_LOCATION="$LOCATION"
bash "$ROOT/scripts/azure/deploy.sh" "$ENVIRONMENT"
bash "$ROOT/scripts/azure/verify.sh" "$ENVIRONMENT"
