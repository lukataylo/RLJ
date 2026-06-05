#!/usr/bin/env bash
# Bring up the full local stack for development. Each stream can also run standalone.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "▶ orchestrator on :8000 (greedy fallback until routing/ is up)"
( cd "$ROOT/orchestrator" && uvicorn app:app --port 8000 ) &

echo "▶ routing service on :8100 (if implemented)"
( cd "$ROOT/routing" && [ -f app.py ] && uvicorn app:app --port 8100 || echo "  routing/app.py not present yet — orchestrator will use greedy fallback" ) &

echo "▶ frontend on :5173 (if implemented)"
( cd "$ROOT/frontend" && [ -f package.json ] && npm run dev || echo "  frontend not present yet" ) &

wait
