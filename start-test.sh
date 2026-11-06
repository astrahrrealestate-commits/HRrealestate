#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "========================================================"
echo "Starting EstateOS QA Testing Stack..."
echo "========================================================"
echo

docker compose -f docker/compose.test.yml up --build
