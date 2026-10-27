#!/usr/bin/env bash
# Removes a SecondChance environment from Azure:  scripts/azure/destroy.sh <demo|pilot>
# The pilot's database and document store carry CanNotDelete locks and its resource group refuses to be
# deleted while it holds resources: remove the locks deliberately first (deletion_protection = false, apply).
set -euo pipefail

ENVIRONMENT=${1:?usage: scripts/azure/destroy.sh <demo|pilot>}
case "$ENVIRONMENT" in demo|pilot) ;; *) echo "unknown environment: $ENVIRONMENT" >&2; exit 2 ;; esac
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
# shellcheck source=scripts/azure/lib.sh
source "$ROOT/scripts/azure/lib.sh"

require_commands az terraform
azure_context

if [ "${SECONDCHANCE_AUTO_APPROVE:-0}" != 1 ]; then
  read -r -p "Type the environment name to destroy it ($ENVIRONMENT): " answer
  [ "$answer" = "$ENVIRONMENT" ] || die "aborted"
fi

tf_init
tf_vars
tf destroy -input=false -auto-approve "${TF_VARS[@]}"
echo "Destroyed. Check for leftovers: az resource list --resource-group rg-secondchance-$ENVIRONMENT"
echo "Entra app registrations created by the environment were removed with it; soft-deleted AI accounts are purged in the demo."
