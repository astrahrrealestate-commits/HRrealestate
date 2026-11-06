#!/usr/bin/env bash
# One command to run EstateOS locally: backend stack (Docker) + dashboard (Next.js).
#
#   ./start.sh                 backend + seed + dashboard on http://localhost:3000   (Ctrl-C stops the dashboard only)
#   ./start.sh --backend-only  backend + seed, no dashboard
#   ./start.sh --demo          also load the mock portfolio and run one scripted day (every agent runs)
#   ./start.sh --help
#
# Stop the backend with `make stop` (keeps data) or `make reset` (wipes data).
set -euo pipefail
cd "$(dirname "$0")"

backend_only=0
demo=0
for arg in "$@"; do
  case "$arg" in
    --backend-only) backend_only=1 ;;
    --demo)         demo=1 ;;
    -h|--help)      sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

step "Checking prerequisites"
./scripts/doctor.sh

step "Preparing configuration"
make --no-print-directory env

step "Starting backend (postgres, migrations, api, worker). First run builds the image: a few minutes"
make --no-print-directory up

step "Seeding the dev company and owner"
make --no-print-directory seed

if [ "$demo" -eq 1 ]; then
  step "Loading demo portfolio and running one scripted day"
  make --no-print-directory sim-agents
fi

echo
echo "Backend ready: http://localhost:${API_PORT:-8000}  (docs: /docs, health: /health/ready)"

if [ "$backend_only" -eq 1 ]; then
  echo "Dashboard skipped. Start it with: make frontend"
  exit 0
fi

step "Starting dashboard on http://localhost:3000 (Ctrl-C stops it; backend keeps running, 'make stop' ends it)"
make --no-print-directory frontend-install
exec make --no-print-directory frontend
