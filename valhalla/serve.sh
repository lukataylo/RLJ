#!/usr/bin/env bash
# Serve the built Greater-London tiles over HTTP via pyvalhalla's valhalla_service
# (no Docker/sudo). Listens on the httpd.service.listen address in valhalla.json
# (default tcp://*:8002). Point the router at it with VALHALLA_URL=http://localhost:8002.
#
# Usage:  valhalla/serve.sh [num_threads]   (foreground; use nohup/systemd to daemonize)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="$HERE/../.venv/bin"
THREADS="${1:-2}"
# pyvalhalla CLI wrappers need the venv bin on PATH and invocation by bare name.
export PATH="$VENV:$PATH"

if [[ ! -f "$HERE/valhalla.json" ]]; then
  echo "valhalla.json missing — run valhalla/build_tiles.sh first" >&2
  exit 1
fi

echo "[valhalla] serving on :8002 (threads=$THREADS) — Ctrl-C to stop"
exec valhalla_service "$HERE/valhalla.json" "$THREADS"
