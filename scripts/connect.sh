#!/usr/bin/env bash
# Preflight, bootstrap, deployment and verification on the cloud you choose (ADR-023):
#   scripts/connect.sh aws   <demo|pilot>     (= scripts/connect-aws.sh)
#   scripts/connect.sh azure <demo|pilot>     (= scripts/azure/connect.sh)
set -euo pipefail

case "${1:-}" in
  aws) shift; exec bash "$(dirname "$0")/connect-aws.sh" "$@" ;;
  azure) shift; exec bash "$(dirname "$0")/azure/connect.sh" "$@" ;;
  *) echo "usage: scripts/connect.sh <aws|azure> <demo|pilot>" >&2; exit 2 ;;
esac
