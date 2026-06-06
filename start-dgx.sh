#!/bin/bash
# start-dgx.sh — bring up the RLJ backend services on the DGX Spark.
#
# Run this ON the DGX (over SSH). It starts the two services that have to be
# running for the full (non-fallback) demo:
#   1. Ollama serving the local model, reachable from other machines
#   2. The FastAPI orchestrator (the hub every stream integrates through)
#
# Both bind to 0.0.0.0 so laptops on the same network can connect. If you only
# ever run the demo ON the DGX itself, localhost would also work — but 0.0.0.0
# is harmless and saves re-debugging "connection refused" if the demo machine
# changes at the last minute.
#
# Tip: run this inside tmux or screen so the services survive if your SSH
# session drops:  tmux new -s rlj  ->  ./start-dgx.sh  ->  detach with Ctrl-b d

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UVICORN="${HOME}/.local/bin/uvicorn"   # pip --user installs land here, not on PATH

echo "[start-dgx] Starting Ollama on all interfaces (0.0.0.0:11434)..."
OLLAMA_HOST=0.0.0.0 ollama serve &
sleep 2

# Warm the model so the first real request doesn't time out on a cold load.
# The 42GB model can take a while to load into memory the first time.
echo "[start-dgx] Warming the model (this can take a minute on first load)..."
curl -s http://localhost:11434/api/generate \
  -d '{"model": "nemotron", "prompt": "ok", "stream": false}' > /dev/null || \
  echo "[start-dgx] (warm-up call failed — check 'ollama list' has the model)"

echo "[start-dgx] Starting orchestrator on 0.0.0.0:8000..."
cd "${REPO_ROOT}/orchestrator"
"${UVICORN}" app:app --host 0.0.0.0 --port 8000 &

echo "[start-dgx] Services starting:"
echo "            orchestrator -> http://0.0.0.0:8000"
echo "            ollama       -> http://0.0.0.0:11434"
echo "[start-dgx] Note: the routing service (routing/app.py) is separate — start it"
echo "            too, or the orchestrator falls back to the greedy router (0 routes)."

wait