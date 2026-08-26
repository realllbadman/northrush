#!/usr/bin/env bash
# Start the NorthRush dev server. Frees port 8007 first so a leftover
# process never causes "address already in use".
set -e
cd "$(dirname "$0")"

PORT="${PORT:-8007}"

# Kill anything still holding the port (old uvicorn, crashed reload, etc.)
if command -v fuser >/dev/null 2>&1; then
    fuser -k "${PORT}/tcp" 2>/dev/null && sleep 1 || true
else
    lsof -ti tcp:"$PORT" 2>/dev/null | xargs -r kill && sleep 1 || true
fi

exec python3 -m uvicorn backend.main:app --reload --port "$PORT"
