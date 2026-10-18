#!/usr/bin/env bash
set -euo pipefail
ENVIRONMENT=${1:?usage: scripts/verify-aws.sh <demo|pilot>}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
REGION=${AWS_REGION:-eu-central-1}
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
STATE_BUCKET=${SECONDCHANCE_STATE_BUCKET:-secondchance-tfstate-$ACCOUNT}
export MSYS_NO_PATHCONV=1
# Native Windows tools (aws.exe, python.exe) cannot open MSYS /tmp paths: use C:/... temp files.
if command -v cygpath >/dev/null; then TMPDIR=$(cygpath -m "${TMPDIR:-/tmp}"); export TMPDIR; fi
host_path() { if command -v cygpath >/dev/null; then cygpath -w "$1"; else echo "$1"; fi; }
tf() {
  if command -v terraform >/dev/null; then terraform -chdir="$ROOT/infra/terraform/envs/$ENVIRONMENT" "$@"
  else docker run --rm -i -v "$(host_path "$ROOT"):/repo" -v "$(host_path "$HOME/.aws"):/root/.aws:ro" -e AWS_PROFILE -e AWS_REGION="$REGION" -w "/repo/infra/terraform/envs/$ENVIRONMENT" hashicorp/terraform:1.16.5 "$@"; fi
}
tf init -input=false -reconfigure -backend-config="bucket=$STATE_BUCKET" -backend-config="region=$REGION" >/dev/null
URL=$(tf output -raw web_url)
curl -fsS --retry 10 --retry-delay 6 --retry-all-errors "$URL/api/health" >/dev/null
aws lambda get-function --region "$REGION" --function-name "secondchance-$ENVIRONMENT-agents" >/dev/null
aws sqs get-queue-url --region "$REGION" --queue-name "secondchance-$ENVIRONMENT-agents" >/dev/null
aws bedrock get-inference-profile --region "$REGION" --inference-profile-identifier "${SECONDCHANCE_BEDROCK_MODEL:-eu.anthropic.claude-haiku-5-5}" >/dev/null
aws lambda get-function --region "$REGION" --function-name "secondchance-$ENVIRONMENT-mcp-gateway" >/dev/null
RUNTIME_RESPONSE=$(mktemp)
trap 'rm -f "$RUNTIME_RESPONSE"' EXIT
aws lambda invoke --cli-read-timeout 300 --region "$REGION" --function-name "secondchance-$ENVIRONMENT-runtime-check" \
  --cli-binary-format raw-in-base64-out --payload '{}' "$RUNTIME_RESPONSE" >/dev/null
python - "$RUNTIME_RESPONSE" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
required = {"database", "model", "guardrail", "embedding_model", "embedding_dimensions", "router", "router_intent"}
if payload.get("errorMessage"):
    raise SystemExit(f"private AWS runtime check failed: {payload['errorMessage']}")
if not required.issubset(payload):
    raise SystemExit(f"private AWS runtime check returned an invalid payload: {payload}")
if payload["database"] != "ok" or payload["guardrail"] != "ok" or payload["embedding_dimensions"] != 1024:
    raise SystemExit(f"private AWS runtime check failed: {payload}")
if payload["router"] not in {"hybrid", "bedrock"} or payload["router_intent"] != "MULTI_AGENT_TASK":
    raise SystemExit(f"router AWS runtime check failed: {payload}")
print(f"Private AWS runtime check passed: {payload}")
PY
if [ "$ENVIRONMENT" = demo ]; then
  REQUEST=$(mktemp); RESPONSE=$(mktemp)
  trap 'rm -f "$RUNTIME_RESPONSE" "$REQUEST" "$RESPONSE"' EXIT
  cat >"$REQUEST" <<'JSON'
{"name":"knowledge_search","arguments":{"query":"temperatura alimenti refrigerati","language":"it","top_k":3},"context":{"tenant_id":"bcaadc41-1e24-5e6c-9617-50747ad59737","subject":"demo-it-coordinator","role":"coordinator","agent":"mcp_client","correlation_id":"aws-deploy-smoke"}}
JSON
  aws lambda invoke --region "$REGION" --function-name secondchance-demo-mcp-gateway \
    --cli-binary-format raw-in-base64-out --payload "fileb://$REQUEST" "$RESPONSE" >/dev/null
  python - "$RESPONSE" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
if payload.get("error"):
    raise SystemExit(f"MCP gateway returned an error: {payload['error']}")
hits = payload.get("result", {}).get("hits", [])
if not hits:
    raise SystemExit("MCP/RAG smoke test returned no authorised evidence")
print(f"MCP/RAG smoke test passed with {len(hits)} authorised hit(s)")
PY
fi
printf 'AWS verification passed: %s\n' "$URL"
