#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  cp .env.example .env
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
export CELERY_BROKER_URL="${CELERY_BROKER_URL:-redis://localhost:6379/0}"
export CELERY_RESULT_BACKEND="${CELERY_RESULT_BACKEND:-redis://localhost:6379/0}"

if ! command -v redis-cli >/dev/null 2>&1; then
  echo "redis-cli not found. Install Redis (e.g. brew install redis) and start it:"
  echo "  brew services start redis"
  exit 1
fi

if ! redis-cli ping >/dev/null 2>&1; then
  echo "Redis is not running. Start it with:"
  echo "  brew services start redis"
  exit 1
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

# shellcheck disable=SC1091
source .venv/bin/activate

trap 'kill 0' EXIT

uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload &
celery -A backend.worker.celery_app worker --loglevel=info &

wait
