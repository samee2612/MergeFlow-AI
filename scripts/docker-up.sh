#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running."
  echo ""
  echo "Start Docker Desktop, wait until it shows \"Docker Desktop is running\", then run:"
  echo "  ./scripts/docker-up.sh"
  echo ""
  echo "Or use the local (non-Docker) stack:"
  echo "  ./scripts/local-up.sh"
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "No .env file found. Creating one from .env.example..."
  cp .env.example .env
  echo "Edit .env and set GITHUB_TOKEN and GEMINI_API_KEY before testing PR automation."
fi

exec docker compose up --build "$@"
