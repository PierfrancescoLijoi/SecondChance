#!/usr/bin/env bash
# Makes a person the first platform administrator:  scripts/azure/grant-platform-admin.sh <demo|pilot> <email|object id>
# The subject SecondChance knows is the person's Entra object id (the `oid` of their token), so an e-mail is
# resolved to it first. The migrate job runs once more with that id; the id is removed from the job afterwards.
set -euo pipefail

ENVIRONMENT=${1:?usage: scripts/azure/grant-platform-admin.sh <demo|pilot> <email|object id>}
WHO=${2:?usage: scripts/azure/grant-platform-admin.sh <demo|pilot> <email|object id>}
case "$ENVIRONMENT" in demo|pilot) ;; *) echo "unknown environment: $ENVIRONMENT" >&2; exit 2 ;; esac
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
# shellcheck source=scripts/azure/lib.sh
source "$ROOT/scripts/azure/lib.sh"

require_commands az terraform
az extension add --name containerapp --upgrade --yes >/dev/null 2>&1 || true
azure_context
tf_init >/dev/null
RESOURCE_GROUP=$(tf output -raw resource_group)

case "$WHO" in
  *@*) OID=$(az ad user show --id "$WHO" --query id --output tsv) || die "no Entra user for $WHO" ;;
  *) OID=$WHO ;;
esac
printf '%s' "$OID" | grep -Eq '^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$' || die "not an Entra object id: $OID"

JOB="secondchance-$ENVIRONMENT-migrate"
az containerapp job update --name "$JOB" --resource-group "$RESOURCE_GROUP" --set-env-vars "SECONDCHANCE_PLATFORM_ADMIN_SUB=$OID" >/dev/null
trap 'az containerapp job update --name "$JOB" --resource-group "$RESOURCE_GROUP" --remove-env-vars SECONDCHANCE_PLATFORM_ADMIN_SUB >/dev/null' EXIT
job_run "$JOB" 600
echo "$WHO is now a platform administrator of $ENVIRONMENT"
