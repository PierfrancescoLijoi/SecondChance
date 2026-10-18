#!/usr/bin/env bash
# The deployed system on an emulated AWS, with no account (docs/deployment.md): builds the Lambda
# images exactly as scripts/deploy.sh does, adds the AWS Runtime Interface Emulator and runs
# api/tests_emulation against infra/emulation/compose.yaml.
#   scripts/emulate-aws.sh
#   SECONDCHANCE_EMULATION_KEEP=1 scripts/emulate-aws.sh   leave it running; remove it with
#   docker compose -f infra/emulation/compose.yaml down -v
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

# Registries throttle anonymous pulls (HTTP 429), above all when several CI runs start together:
# a failed build is retried after a pause instead of failing the run.
retry() {
  local attempt
  for attempt in 1 2 3; do
    "$@" && return 0
    [ "$attempt" = 3 ] && return 1
    echo "attempt $attempt failed, retrying in $((attempt * 20)) s" >&2
    sleep $((attempt * 20))
  done
}

lambda_image() {
  local context=$1 build_target=$2 target=$3
  # The same two lines as scripts/deploy.sh; api/tests/test_aws_automation.py keeps them identical.
  tar -c --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache -C "$context" . \
    | docker build --platform linux/amd64 --provenance=false --target "$build_target" -t "secondchance-lambda:$target" -
}

for target in api worker gateway; do
  context="$ROOT/api"; build_target="$target"
  if [ "$target" = gateway ]; then context="$ROOT/mcp-gateway"; build_target=worker; fi
  retry lambda_image "$context" "$build_target" "$target"
  retry docker build --build-arg "BASE=secondchance-lambda:$target" -t "secondchance-lambda-emulator:$target" infra/emulation
done

cd api
uv run --locked pytest tests_emulation -v
