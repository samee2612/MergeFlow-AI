#!/bin/sh
set -e

PORT="${PORT:-8000}"
echo "Starting Uvicorn on port $PORT..."
exec uvicorn backend.main:app --host 0.0.0.0 --port "$PORT"
