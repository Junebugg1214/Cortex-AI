#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/Junebugg1214/Cortex-AI.git"
INSTALL_DIR="${CORTEX_INSTALL_DIR:-$HOME/cortex-ai-self-host}"
PORT="${CORTEX_PORT:-8421}"
PINNED_REF="1a73473f628f34bf9fd5eca5f68b5cb6c16029bf"
REF="${CORTEX_REF:-$PINNED_REF}"

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1"
    exit 1
  fi
}

need_cmd git
need_cmd docker

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose is required (docker compose)."
  exit 1
fi

echo "Installing Cortex ref: $REF"

if [ ! -d "$INSTALL_DIR/.git" ]; then
  echo "Cloning Cortex into $INSTALL_DIR"
  git clone "$REPO_URL" "$INSTALL_DIR"
  git -C "$INSTALL_DIR" fetch --tags origin
  git -C "$INSTALL_DIR" checkout --detach "$REF"
else
  echo "Updating existing Cortex install in $INSTALL_DIR"
  git -C "$INSTALL_DIR" fetch --tags origin
  if [ "$REF" = "main" ]; then
    git -C "$INSTALL_DIR" checkout main
    git -C "$INSTALL_DIR" pull --ff-only origin main
  else
    git -C "$INSTALL_DIR" checkout --detach "$REF"
  fi
fi

cd "$INSTALL_DIR"
if [ ! -f deploy/cortex.ini ]; then
  cat > deploy/cortex.ini <<INI
[server]
host = 0.0.0.0
port = $PORT

[storage]
backend = sqlite
db_path = /data/cortex.db

[users]
enabled = true
registration_open = true
default_storage_mode = byos
storage_modes = byos,self_host
INI
fi

echo "Starting Cortex with Docker Compose..."
docker compose up -d --build

echo
IP_ADDR=$(hostname -I 2>/dev/null | awk '{print $1}') || true
if [ -n "${IP_ADDR:-}" ]; then
  echo "Cortex is starting at: http://$IP_ADDR:$PORT/app"
else
  echo "Cortex is starting at: http://localhost:$PORT/app"
fi

echo "Next step: open /app and create your account."
