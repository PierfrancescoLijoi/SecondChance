#!/usr/bin/env bash
# Runs the Azure scripts end to end against stand-ins for az, terraform, docker and curl (scripts/azure/tests/fake-bin).
# It proves the control flow, the order of the steps, the flags and variables handed to each tool, the failure
# paths, and that no script uses a command the stand-ins (checked against the real CLI's help) do not model.
# It does not prove what Azure answers: that is the preflight's and verify.sh's job on a real subscription.
#   scripts/azure/tests/run.sh
# shellcheck disable=SC2015  # `cmd && ok || bad` is intended: ok and bad never fail
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
export PATH="$HERE/fake-bin:$PATH"
chmod +x "$HERE"/fake-bin/* 2>/dev/null || true
export SECONDCHANCE_ALARM_EMAIL=ops@example.org

PASSED=0; FAILED=0
FAKE_VARS=(FAKE_JOB_STATUS FAKE_DEAD_LETTERS FAKE_BACKLOG_POLLS FAKE_ORIGIN_CODE FAKE_API_ME_CODE FAKE_DEFENDER FAKE_IMAGE_PRESENT
  FAKE_MODELS FAKE_USAGE FAKE_STATE_ACCOUNT FAKE_NAME_FREE FAKE_PROVIDER_STATE FAKE_GROUP_EXISTS FAKE_NO_USER FAKE_GRAPH
  FAKE_OTHER_FREE_PUBSUB SECONDCHANCE_CLOUD SECONDCHANCE_CHAT_MODEL SECONDCHANCE_CHAT_MODEL_JSON SECONDCHANCE_EMBEDDING_MODEL_JSON
  SECONDCHANCE_AUTO_APPROVE SECONDCHANCE_CREATE_APP_REGISTRATIONS SECONDCHANCE_OIDC_CLIENT_ID SECONDCHANCE_WEB_PUBSUB_SKU)

# case <name>  -- starts a clean scenario: empty log, state, and no FAKE_* left over from the previous one
case_start() {
  CASE=$1
  for variable in "${FAKE_VARS[@]}"; do unset "$variable"; done
  export FAKE_LOG="$WORK/$CASE.log" FAKE_STATE="$WORK/$CASE.state" FAKE_ENV=demo
  rm -rf "$FAKE_STATE"; mkdir -p "$FAKE_STATE"; : >"$FAKE_LOG"
}
run() {   # run <script> [args...]: output in $OUT, exit status in $STATUS
  OUT="$WORK/$CASE.out"
  bash "$ROOT/scripts/$1" "${@:2}" >"$OUT" 2>&1 </dev/null
  STATUS=$?
}
ok() { PASSED=$((PASSED + 1)); printf '  ok   %s\n' "$1"; }
bad() { FAILED=$((FAILED + 1)); printf '  FAIL %s\n' "$1"; [ -z "${2:-}" ] || printf '       %s\n' "$2"; }
expect_status() {   # expect_status <0|nonzero> <label>
  if [ "$1" = 0 ]; then [ "$STATUS" = 0 ] && ok "$2" || { bad "$2" "exit $STATUS: $(tail -3 "$OUT" | tr '\n' ' ')"; }
  else [ "$STATUS" != 0 ] && ok "$2" || bad "$2" "expected a failure, got exit 0"; fi
}
log_has() { grep -Eq -- "$1" "$FAKE_LOG" && ok "$2" || bad "$2" "no log line matches: $1"; }
log_lacks() { grep -Eq -- "$1" "$FAKE_LOG" && bad "$2" "unexpected log line matches: $1" || ok "$2"; }
out_has() { grep -Eq -- "$1" "$OUT" && ok "$2" || bad "$2" "output lacks: $1 -- $(tail -2 "$OUT" | tr '\n' ' ')"; }
line_of() { grep -En -- "$1" "$FAKE_LOG" | head -1 | cut -d: -f1; }
in_order() {   # in_order <label> <regex>...: each regex first matches on a later log line than the previous one
  local label=$1 previous=0 current regex; shift
  for regex in "$@"; do
    current=$(grep -En -- "$regex" "$FAKE_LOG" | cut -d: -f1 | awk -v p="$previous" '$1 > p { print; exit }')
    [ -n "$current" ] || { bad "$label" "no match after line $previous for: $regex"; return; }
    previous=$current
  done
  ok "$label"
}
no_unmodelled() { grep -q "FAKE-" "$OUT" && bad "$1" "a script used a command the stand-ins do not model: $(grep FAKE- "$OUT" | head -1)" || ok "$1"; }

echo "deploy.sh demo"
case_start deploy_demo
run azure/deploy.sh demo
expect_status 0 "deploys the demo"
no_unmodelled "only modelled commands were used"
in_order "registry first, then images, then the infrastructure, then the database jobs, then the smoke test" \
  'terraform .* init ' 'apply .*-target=module.secondchance.azurerm_container_registry.main' 'az acr login --name acrmock' \
  'docker build .*--target api ' 'docker push acrmock.azurecr.io/app:' 'docker push acrmock.azurecr.io/gateway:' 'docker push acrmock.azurecr.io/web:' \
  'apply -input=false -var subscription_id' 'job start --name secondchance-demo-bootstrap' 'job start --name secondchance-demo-migrate' \
  'job start --name secondchance-demo-seed' 'curl .*/api/health'
log_has 'docker build .*--target service ' "the gateway image is built from the mcp-gateway service target"
log_has 'docker build .*--target azure ' "the web image is built from the azure target"
log_has 'subscription_id=99999999-8888-7777-6666-555555555555' "the subscription id reaches Terraform"
log_has 'location=germanywestcentral' "the region reaches Terraform"
log_has 'alarm_email=ops@example.org' "the alarm address reaches Terraform"
log_has 'image_tag=[0-9a-f]{12}-dirty-' "an uncommitted tree is tagged dirty"
log_has 'backend-config=storage_account_name=sctfstate' "the state account name is derived from the subscription"
log_has 'backend-config=container_name=tfstate' "the state container is set"
out_has 'grant-platform-admin.sh demo' "the next step is printed"

echo "deploy.sh pilot refuses an uncommitted tree"
case_start deploy_pilot_dirty
if [ -n "$(git -C "$(cygpath -m "$ROOT" 2>/dev/null || echo "$ROOT")" status --porcelain)" ]; then
  FAKE_ENV=pilot run azure/deploy.sh pilot
  expect_status nonzero "refuses to deploy uncommitted changes to the pilot"
  log_lacks 'docker push' "nothing was pushed"
else
  ok "(clean tree: the refusal path does not apply)"
fi

echo "deploy.sh skips images that are already pushed"
case_start deploy_images_present
FAKE_IMAGE_PRESENT=yes run azure/deploy.sh demo
expect_status 0 "deploys without rebuilding"
log_lacks 'docker (build|push)' "no image is built or pushed twice"

echo "deploy.sh stops when a database job fails"
case_start deploy_job_fails
FAKE_JOB_STATUS=Failed run azure/deploy.sh demo
expect_status nonzero "a failed bootstrap fails the deployment"
log_lacks 'job start --name secondchance-demo-migrate' "the migration is not attempted after a failed bootstrap"
out_has 'Failed' "the failure is reported"

echo "deploy.sh via the cloud switch of scripts/deploy.sh"
case_start deploy_switch
SECONDCHANCE_CLOUD=azure run deploy.sh demo
expect_status 0 "SECONDCHANCE_CLOUD=azure hands over to the Azure script"
log_has 'az acr login' "it ran the Azure flow"

echo "deploy.sh with app registrations created elsewhere"
case_start deploy_byo
SECONDCHANCE_CREATE_APP_REGISTRATIONS=false SECONDCHANCE_OIDC_CLIENT_ID=12345678-1234-1234-1234-123456789012 run azure/deploy.sh demo
expect_status 0 "deploys with a supplied app registration"
log_has 'create_app_registrations=false' "Terraform is told not to create them"
log_has 'oidc_client_id=12345678-1234-1234-1234-123456789012' "and which one to use"
case_start deploy_byo_missing
SECONDCHANCE_CREATE_APP_REGISTRATIONS=false run azure/deploy.sh demo
expect_status nonzero "refuses to continue without the client id"

echo "verify.sh demo"
case_start verify_ok
run azure/verify.sh demo
expect_status 0 "a healthy demo verifies"
no_unmodelled "only modelled commands were used"
in_order "edge, origin lock, queues, ping, runtime check, gateway path" \
  'curl .*/api/health' 'curl .*/config.json' 'containerapp show .*--name secondchance-demo-api' 'servicebus queue show .*deadLetterMessageCount' \
  'job start --name secondchance-demo-ping' 'activeMessageCount' 'job start --name secondchance-demo-check' 'job start --name secondchance-demo-tools'
out_has 'Defender for Storage scans every upload' "malware scanning is reported"

case_start verify_backlog_drains
FAKE_BACKLOG_POLLS=3 run azure/verify.sh demo
expect_status 0 "waits for the worker to consume the check message"
log_has 'sleep 10' "and polls with a delay"

case_start verify_dead_letters
FAKE_DEAD_LETTERS=3 run azure/verify.sh demo
expect_status nonzero "dead letters fail the verification"
out_has 'dead-lettered' "naming the runbook"

case_start verify_origin_open
FAKE_ORIGIN_CODE=200 run azure/verify.sh demo
expect_status nonzero "an open origin fails the verification"
out_has 'origin lock' "naming the origin lock"

case_start verify_api_me
FAKE_API_ME_CODE=502 run azure/verify.sh demo
expect_status nonzero "a broken /api rewrite fails the verification"

case_start verify_no_consumer
FAKE_BACKLOG_POLLS=100000 run azure/verify.sh demo
expect_status nonzero "a worker that never scales up fails the verification"
out_has 'did not scale up from zero' "naming the likely cause"

case_start verify_check_fails
FAKE_JOB_STATUS=Failed run azure/verify.sh demo
expect_status nonzero "a failing job fails the verification"

case_start verify_defender_off
FAKE_DEFENDER=false run azure/verify.sh demo
expect_status 0 "disabled malware scanning is a warning, not a failure"
out_has 'warning: Defender' "the warning is printed"

echo "connect.sh demo"
case_start connect_ok
run azure/connect.sh demo
expect_status 0 "preflight, deployment and verification pass"
no_unmodelled "only modelled commands were used"
in_order "the preflight runs before Terraform, then deploy, then verify" \
  'cognitiveservices model list' 'postgres flexible-server list-skus' 'acr check-name' 'terraform .* init ' 'job start --name secondchance-demo-bootstrap' 'job start --name secondchance-demo-check'
log_has 'chat_model=\{"name": "gpt-4.1-mini", "version": "2025-04-14", "sku": "DataZoneStandard", "capacity": 30\}' "the chosen chat model reaches Terraform as a JSON object"
log_has 'embedding_model=\{"name": "text-embedding-3-large"' "and so does the embedding model"

case_start connect_model_missing
FAKE_MODELS=models-missing.json run azure/connect.sh demo
expect_status nonzero "a model the region does not offer stops the preflight"
out_has 'not offered with the DataZoneStandard SKU' "saying which SKU and what is offered"
log_lacks 'terraform' "before Terraform ran"

case_start connect_quota
SECONDCHANCE_MODEL_CAPACITY=95 run azure/connect.sh demo
expect_status nonzero "not enough free quota stops the preflight"
out_has 'quota for OpenAI.DataZoneStandard' "naming the quota"

case_start connect_names_taken
FAKE_NAME_FREE=false run azure/connect.sh demo
expect_status nonzero "a taken global name stops the preflight"
log_lacks 'terraform' "before Terraform ran"

case_start connect_redeploy_skips_name_checks
FAKE_GROUP_EXISTS=true run azure/connect.sh demo
expect_status 0 "a re-deploy does not fail on its own names"
log_lacks 'acr check-name' "the names are not re-checked"

case_start connect_registers_providers
FAKE_PROVIDER_STATE=NotRegistered run azure/connect.sh demo
expect_status 0 "unregistered providers are registered"
log_has 'provider register --namespace Microsoft.App --wait' "with --wait"

case_start connect_bootstraps_state
FAKE_STATE_ACCOUNT=missing run azure/connect.sh demo
expect_status 0 "a missing state account triggers the bootstrap"
log_has 'bootstrap apply .*subscription_id=99999999-8888-7777-6666-555555555555' "which receives the subscription"

case_start connect_free_pubsub_taken
FAKE_OTHER_FREE_PUBSUB=1 run azure/connect.sh demo
expect_status nonzero "a second Free Web PubSub instance is caught"
out_has 'SECONDCHANCE_WEB_PUBSUB_SKU=Standard_S1' "with the way out"

case_start connect_pubsub_standard
SECONDCHANCE_WEB_PUBSUB_SKU=Standard_S1 FAKE_OTHER_FREE_PUBSUB=1 run azure/connect.sh demo
expect_status 0 "choosing Standard skips the Free check"
log_has 'web_pubsub_sku=Standard_S1' "and passes the choice to Terraform"

case_start connect_via_switch
run connect.sh azure demo
expect_status 0 "scripts/connect.sh azure demo"

echo "destroy.sh"
case_start destroy_confirmed
SECONDCHANCE_AUTO_APPROVE=1 run azure/destroy.sh demo
expect_status 0 "destroys with auto approval"
log_has 'terraform .* destroy .*image_tag=destroy' "with placeholder inputs, as the AWS script does"

case_start destroy_aborted
OUT="$WORK/$CASE.out"; printf 'wrong\n' | bash "$ROOT/scripts/azure/destroy.sh" demo >"$OUT" 2>&1; STATUS=$?
expect_status nonzero "a wrong confirmation aborts"
log_lacks 'destroy' "nothing was destroyed"

echo "grant-platform-admin.sh"
case_start grant_email
run azure/grant-platform-admin.sh demo someone@example.org
expect_status 0 "grants a platform admin by e-mail"
in_order "set the id, run the migrate job, take the id away again" \
  'ad user show --id someone@example.org' 'job update --name secondchance-demo-migrate .*--set-env-vars SECONDCHANCE_PLATFORM_ADMIN_SUB=7e6c8c0e' \
  'job start --name secondchance-demo-migrate' 'job update --name secondchance-demo-migrate .*--remove-env-vars SECONDCHANCE_PLATFORM_ADMIN_SUB'

case_start grant_oid
run azure/grant-platform-admin.sh demo 7e6c8c0e-0000-4000-8000-000000000001
expect_status 0 "grants by object id"
log_lacks 'ad user show' "without a directory lookup"

case_start grant_bad_input
run azure/grant-platform-admin.sh demo "not a guid; rm -rf /"
expect_status nonzero "rejects anything that is not an object id"
log_lacks 'job update' "and touches nothing"

case_start grant_unknown_user
FAKE_NO_USER=yes run azure/grant-platform-admin.sh demo ghost@example.org
expect_status nonzero "an unknown user is reported"

echo
printf 'Azure scripts: %s passed, %s failed\n' "$PASSED" "$FAILED"
[ "$FAILED" = 0 ]
