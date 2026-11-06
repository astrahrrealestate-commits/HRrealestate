#!/usr/bin/env bash
# Preflight: checks the tools and ports EstateOS needs. Exit 1 when something required is missing.
# Used by `make doctor`, `make all` and `./start.sh`. Safe to run any time; changes nothing.
set -uo pipefail
cd "$(dirname "$0")/.."

fail=0
ok()   { printf '  \033[32mok\033[0m    %s\n' "$1"; }
warn() { printf '  \033[33mwarn\033[0m  %s\n' "$1"; }
bad()  { printf '  \033[31mMISSING\033[0m %s\n' "$1"; fail=1; }

version_ge() { [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]; }  # $1 >= $2

echo "EstateOS preflight"

# --- required: docker (backend runs in containers) -------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  bad "docker: install Docker Desktop (macOS/Windows) or Docker Engine (Linux): https://docs.docker.com/get-docker/"
elif ! docker info >/dev/null 2>&1; then
  bad "docker daemon not running: start Docker Desktop / the docker service and re-run"
elif ! docker compose version >/dev/null 2>&1; then
  bad "docker compose v2 plugin: update Docker (the old 'docker-compose' binary is not supported)"
else
  ok "docker $(docker version --format '{{.Server.Version}}' 2>/dev/null), $(docker compose version --short 2>/dev/null)"
fi

# --- required: make, curl ---------------------------------------------------------------------------------------
command -v make >/dev/null 2>&1 && ok "make" || bad "make: macOS 'xcode-select --install', Debian/Ubuntu 'sudo apt install make'"
command -v curl >/dev/null 2>&1 && ok "curl" || bad "curl"

# --- required for the dashboard: node 20.9+ ---------------------------------------------------------------------
if command -v node >/dev/null 2>&1; then
  node_v="$(node --version | sed 's/^v//')"
  if version_ge "$node_v" "20.9.0"; then ok "node $node_v"; else bad "node $node_v is too old: need 20.9+ (22 LTS recommended), https://nodejs.org"; fi
else
  bad "node: need 20.9+ (22 LTS recommended) for the dashboard, https://nodejs.org (or 'nvm install 22')"
fi
command -v npm >/dev/null 2>&1 && ok "npm $(npm --version)" || bad "npm (ships with node)"

# --- optional: uv (only for tests, lint, migrations, make setup) ------------------------------------------------
if command -v uv >/dev/null 2>&1; then
  uv_v="$(uv --version | awk '{print $2}')"
  if [ "$uv_v" = "0.12.5" ]; then ok "uv $uv_v";
  else warn "uv $uv_v but pyproject pins ==0.12.5: 'curl -LsSf https://astral.sh/uv/0.12.5/install.sh | sh' (only needed for tests/lint)"; fi
else
  warn "uv not found: fine to just run the app; needed for tests/lint (curl -LsSf https://astral.sh/uv/0.12.5/install.sh | sh)"
fi

# --- disk: a full disk makes Docker hang instead of failing -----------------------------------------------------
free_kb="$(df -k . | awk 'NR==2 {print $4}')"
if [ -n "$free_kb" ] && [ "$free_kb" -lt 5242880 ]; then
  warn "under 5 GB free disk: image build and Postgres may hang. Free space first"
else
  ok "disk space"
fi

# --- ports: free, or already ours ------------------------------------------------------------------------------
listening() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
ours() { [ -n "$(docker ps -q --filter "publish=$1" --filter label=com.docker.compose.project=estateos 2>/dev/null)" ]; }  # a running EstateOS container publishes it
if command -v lsof >/dev/null 2>&1; then
  for p in "PG_PORT:${PG_PORT:-5433}:postgres" "API_PORT:${API_PORT:-8000}:api"; do
    var="${p%%:*}"; rest="${p#*:}"; port="${rest%%:*}"; name="${rest##*:}"
    if listening "$port" && ! ours "$port"; then bad "port $port ($name) is taken by another process: stop it, or set $var=<free port> in .env"
    else ok "port $port ($name)"; fi
  done
  if listening 3000; then warn "port 3000 is in use: the dashboard needs exactly 3000 (API CORS allows only that); fine if it is already EstateOS"
  else ok "port 3000 (dashboard)"; fi
else
  warn "lsof not found: skipping port checks"
fi

echo
if [ "$fail" -ne 0 ]; then echo "Fix the MISSING items above, then re-run."; exit 1; fi
echo "All required tools present."
