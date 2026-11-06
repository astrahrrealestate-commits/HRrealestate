#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "========================================================"
echo "Starting EstateOS QA Testing Stack..."
echo "========================================================"
echo

# 1. If offline bundle tar exists in the same folder, load it automatically
if [ -f "estateos-bundle.tar" ]; then
  echo "[1/2] Loading offline Docker images from estateos-bundle.tar..."
  docker load -i estateos-bundle.tar
  echo "Done loading images."
  echo
fi

# 2. Resolve compose file path
COMPOSE_FILE="compose.test.yml"
if [ ! -f "$COMPOSE_FILE" ] && [ -f "docker/compose.test.yml" ]; then
  COMPOSE_FILE="docker/compose.test.yml"
fi

echo "[2/2] Launching EstateOS containers..."
docker compose -f "$COMPOSE_FILE" up --force-recreate

