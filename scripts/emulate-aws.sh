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

for target in api worker gateway; do
  context="$ROOT/api"; build_target="$target"
  if [ "$target" = gateway ]; then context="$ROOT/mcp-gateway"; build_target=worker; fi
  # The same two lines as scripts/deploy.sh; api/tests/test_aws_automation.py keeps them identical.
  tar -c --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache -C "$context" . \
    | docker build --platform linux/amd64 --provenance=false --target "$build_target" -t "secondchance-lambda:$target" -
  docker build --build-arg "BASE=secondchance-lambda:$target" -t "secondchance-lambda-emulator:$target" infra/emulation
done

cd api
uv run --locked pytest tests_emulation -v
