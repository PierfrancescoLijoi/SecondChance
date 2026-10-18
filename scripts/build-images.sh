#!/usr/bin/env sh
# Builds the local images by streaming each context as a tar archive.
# Why: Docker Desktop on Windows refuses OneDrive "cloud files" (reparse points) when it
# reads a build context from disk ("invalid file request Dockerfile"). A tar stream is read
# by the shell instead, so it works anywhere. On Linux/macOS `docker compose build` is fine.
set -eu
cd "$(dirname "$0")/.."
tar -c --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache -C api . | docker build -t secondchance-api:local -
tar -c -C db . | docker build -t secondchance-db:16 -
tar -c --exclude=node_modules --exclude=dist -C web . | docker build -t secondchance-web:local -
