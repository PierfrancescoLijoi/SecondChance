#!/usr/bin/env bash
# Makes an already signed-up Cognito user the first platform admin:
#   scripts/grant-platform-admin.sh <demo|pilot> <email>
# Later admins are approved inside the app; this is only the bootstrap of trust.
set -euo pipefail

# One repository, two clouds (ADR-023): SECONDCHANCE_CLOUD=azure hands over to the Azure scripts.
if [ "${SECONDCHANCE_CLOUD:-aws}" = azure ]; then exec bash "$(dirname "$0")/azure/grant-platform-admin.sh" "$@"; fi

ENVIRONMENT=${1:?usage: scripts/grant-platform-admin.sh <demo|pilot> <email>}
EMAIL=${2:?usage: scripts/grant-platform-admin.sh <demo|pilot> <email>}
REGION=eu-central-1
NAME="secondchance-$ENVIRONMENT"

POOL=$(aws cognito-idp list-user-pools --region "$REGION" --max-results 60 \
  --query "UserPools[?Name=='$NAME'].Id | [0]" --output text)
[ "$POOL" != "None" ] || { echo "user pool $NAME not found" >&2; exit 1; }

SUB=$(aws cognito-idp list-users --region "$REGION" --user-pool-id "$POOL" --filter "email = \"$EMAIL\"" \
  --query "Users[0].Attributes[?Name=='sub'].Value | [0]" --output text)
[ "$SUB" != "None" ] || { echo "no user with email $EMAIL: sign up first" >&2; exit 1; }

OUT=$(mktemp)
aws lambda invoke --cli-read-timeout 900 --region "$REGION" --function-name "$NAME-migrate" --cli-binary-format raw-in-base64-out \
  --payload "{\"platform_admin_sub\": \"$SUB\", \"seed\": false}" "$OUT" >/dev/null
cat "$OUT"; echo
