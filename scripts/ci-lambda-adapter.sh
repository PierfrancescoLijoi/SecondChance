#!/usr/bin/env bash
# CI only. Puts the Lambda Web Adapter image that the lambda-api target of api/Dockerfile copies
# from into the local image store, so image builds never pull it anonymously from ECR Public,
# which answers "429 Data limit exceeded" to the shared GitHub runner addresses. The archive is
# kept in the GitHub Actions cache; ECR is contacted only when the cache is cold.
#   scripts/ci-lambda-adapter.sh --key          cache key, derived from the adapter reference
#   scripts/ci-lambda-adapter.sh <archive.tar>  load the archive, or pull and write it
set -euo pipefail
ARG=${1:?usage: scripts/ci-lambda-adapter.sh --key | <archive.tar>}
ROOT=$(cd "$(dirname "$0")/.." && pwd)

# One source of truth: the reference api/Dockerfile copies the adapter from.
IMAGE=$(sed -n 's|^COPY --from=\([^ ]*aws-lambda-adapter[^ ]*\) .*|\1|p' "$ROOT/api/Dockerfile")
[ -n "$IMAGE" ] || { echo "no Lambda Web Adapter reference in api/Dockerfile" >&2; exit 1; }

if [ "$ARG" = --key ]; then
  echo "lambda-adapter-$IMAGE"
  exit 0
fi

if [ -f "$ARG" ]; then
  docker load -i "$ARG"
  exit 0
fi

for attempt in 1 2 3 4 5; do
  docker pull --platform linux/amd64 "$IMAGE" && break
  [ "$attempt" = 5 ] && exit 1
  echo "pull attempt $attempt failed, retrying in $((attempt * 30)) s" >&2
  sleep $((attempt * 30))
done
mkdir -p "$(dirname "$ARG")"
docker save "$IMAGE" -o "$ARG"
