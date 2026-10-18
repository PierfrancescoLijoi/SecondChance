#!/usr/bin/env bash
# Deploys SecondChance to AWS in one command (ADR-018):  scripts/deploy.sh <demo|pilot>
#
# Credentials are never stored here. Locally: an IAM Identity Center session
#   aws configure sso --profile secondchance-admin   (once)
#   aws sso login --profile secondchance-admin && export AWS_PROFILE=secondchance-admin
# In GitHub Actions: the OIDC role from infra/terraform/bootstrap (no secrets).
#
# Required: SECONDCHANCE_ALARM_EMAIL. Optional: SECONDCHANCE_STATE_BUCKET (default secondchance-tfstate-<account>),
# SECONDCHANCE_AUTO_APPROVE=1 (CI). Needs aws CLI v2 and docker; terraform and node are used from
# docker images when not installed.
set -euo pipefail

ENVIRONMENT=${1:?usage: scripts/deploy.sh <demo|pilot>}
case "$ENVIRONMENT" in demo|pilot) ;; *) echo "unknown environment: $ENVIRONMENT" >&2; exit 2 ;; esac
: "${SECONDCHANCE_ALARM_EMAIL:?set SECONDCHANCE_ALARM_EMAIL (alarms and budget alerts)}"
REGION=eu-central-1
ROOT=$(cd "$(dirname "$0")/.." && pwd)
export MSYS_NO_PATHCONV=1   # Git Bash on Windows: keep container paths as they are
# Native Windows tools (aws.exe, python.exe) cannot open MSYS /tmp paths: use C:/... temp files.
if command -v cygpath >/dev/null; then TMPDIR=$(cygpath -m "${TMPDIR:-/tmp}"); export TMPDIR; fi

step() { printf '\n== %s\n' "$*"; }

# --- 0. Who am I? Fails fast without valid, temporary credentials ---
step "AWS identity"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
aws sts get-caller-identity --query Arn --output text
STATE_BUCKET=${SECONDCHANCE_STATE_BUCKET:-secondchance-tfstate-$ACCOUNT}

TAG=$(git -C "$ROOT" rev-parse --short=12 HEAD)
if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then
  [ "$ENVIRONMENT" = pilot ] && { echo "refusing to deploy uncommitted changes to the pilot" >&2; exit 1; }
  TAG="$TAG-dirty-$(date +%s)"
fi

host_path() { if command -v cygpath >/dev/null; then cygpath -w "$1"; else echo "$1"; fi; }

tf() {
  if command -v terraform >/dev/null; then
    terraform -chdir="$ROOT/infra/terraform/envs/$ENVIRONMENT" "$@"
  else
    docker run --rm -i \
      -v "$(host_path "$ROOT"):/repo" -v "$(host_path "$HOME/.aws"):/root/.aws:ro" \
      -e AWS_PROFILE -e AWS_REGION="$REGION" -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_SESSION_TOKEN \
      -w "/repo/infra/terraform/envs/$ENVIRONMENT" hashicorp/terraform:1.16.5 "$@"
  fi
}

VARS=(-var "image_tag=$TAG" -var "alarm_email=$SECONDCHANCE_ALARM_EMAIL")
# The model the preflight checked is the model the functions get.
[ -n "${SECONDCHANCE_BEDROCK_MODEL:-}" ] && VARS+=(-var "bedrock_model_id=$SECONDCHANCE_BEDROCK_MODEL")
APPROVE=(); [ "${SECONDCHANCE_AUTO_APPROVE:-0}" = 1 ] && APPROVE=(-auto-approve)

step "Terraform init (state in s3://$STATE_BUCKET)"
tf init -input=false -reconfigure -backend-config="bucket=$STATE_BUCKET" -backend-config="region=$REGION"

# --- 1. The registry must exist before the functions that use its images ---
step "Image registry"
tf apply -input=false -auto-approve -target=module.secondchance.aws_ecr_repository.app "${VARS[@]}"
ECR=$(tf output -raw ecr_repository_url)
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${ECR%%/*}"

step "Images $TAG (api, worker, gateway)"
for target in api worker gateway; do
  if aws ecr describe-images --region "$REGION" --repository-name "${ECR##*/}" --image-ids "imageTag=$TAG-$target" >/dev/null 2>&1; then
    echo "$TAG-$target already pushed"; continue
  fi
  # tar stream: works with OneDrive folders on Windows too (scripts/build-images.sh)
  # --provenance=false: Lambda rejects the OCI image index that buildx attestations produce.
  context="$ROOT/api"; build_target="$target"
  if [ "$target" = gateway ]; then context="$ROOT/mcp-gateway"; build_target=worker; fi
  tar -c --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache -C "$context" . \
    | docker build --platform linux/amd64 --provenance=false --target "$build_target" -t "$ECR:$TAG-$target" -
  docker push "$ECR:$TAG-$target"
done

# --- 2. Everything else ---
step "Infrastructure"
tf apply -input=false "${APPROVE[@]}" "${VARS[@]}"
WEB_URL=$(tf output -raw web_url)
WEB_BUCKET=$(tf output -raw web_bucket)
DISTRIBUTION=$(tf output -raw distribution_id)
MIGRATE=$(tf output -raw migrate_function)

# --- 3. Database: roles (idempotent), migrations, synthetic seed in demo ---
step "Database"
OUT=$(mktemp)
aws lambda invoke --cli-read-timeout 900 --region "$REGION" --function-name "$MIGRATE" --cli-binary-format raw-in-base64-out \
  --payload '{"bootstrap": true}' "$OUT" --query FunctionError --output text | grep -qv Unhandled \
  || { cat "$OUT"; echo; echo "migration failed" >&2; exit 1; }
cat "$OUT"; echo

if [ "$ENVIRONMENT" = demo ]; then
  step "Synthetic RAG knowledge"
  aws lambda invoke --cli-read-timeout 900 --region "$REGION" --function-name "secondchance-demo-demo-seed" \
    --cli-binary-format raw-in-base64-out --payload '{}' "$OUT" --query FunctionError --output text | grep -qv Unhandled \
    || { cat "$OUT"; echo; echo "demo RAG seed failed" >&2; exit 1; }
  cat "$OUT"; echo
fi

# --- 4. Web app: same build everywhere, config.json comes from Terraform ---
step "Web app"
if command -v npm >/dev/null; then
  (cd "$ROOT/web" && npm ci --no-audit --no-fund && npm run build)
else
  docker run --rm -v "$(host_path "$ROOT/web"):/app" -w /app node:24.21.0-alpine sh -c "npm ci --no-audit --no-fund && npm run build"
fi
aws s3 sync "$ROOT/web/dist/assets" "s3://$WEB_BUCKET/assets" --delete --cache-control "public, max-age=31536000, immutable"
aws s3 sync "$ROOT/web/dist" "s3://$WEB_BUCKET" --delete --exclude "assets/*" --exclude "config.json" --cache-control "no-cache"
aws cloudfront create-invalidation --distribution-id "$DISTRIBUTION" --paths "/index.html" "/config.json" >/dev/null

# --- 5. Smoke test ---
step "Smoke test"
curl -fsS --retry 10 --retry-delay 6 --retry-all-errors "$WEB_URL/api/health"; echo

cat <<EOF

SecondChance $ENVIRONMENT is up: $WEB_URL
Next: sign up in the web app, then make yourself the first platform admin:
  scripts/grant-platform-admin.sh $ENVIRONMENT <your sign-up email>
EOF
