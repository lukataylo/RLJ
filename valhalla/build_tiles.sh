#!/usr/bin/env bash
# Build Greater-London Valhalla tiles in-process via pyvalhalla (no Docker/sudo).
# Idempotent-ish: regenerates config + tiles from the local OSM extract.
#
# Usage:  valhalla/build_tiles.sh [path/to/greater-london-latest.osm.pbf]
# Tiles land in valhalla/tiles/ (+ valhalla/tiles.tar for mmap serving). Both are
# git-ignored Spark-resident artifacts. Run on the GB10 box inside the uv venv.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="$HERE/../.venv/bin"
PBF="${1:-$HERE/../data/cache/osm/greater-london-latest.osm.pbf}"
# pyvalhalla's CLI wrappers resolve their bundled binary via `which <name>`, so the
# venv bin dir must be on PATH and we must invoke by bare name (not absolute path).
export PATH="$VENV:$PATH"

if [[ ! -f "$PBF" ]]; then
  echo "OSM extract not found: $PBF — run: .venv/bin/python data/osm_fetch.py" >&2
  exit 1
fi

echo "[valhalla] generating config -> $HERE/valhalla.json"
valhalla_build_config \
  --mjolnir-tile-dir "$HERE/tiles" \
  --mjolnir-tile-extract "$HERE/tiles.tar" \
  > "$HERE/valhalla.json"

mkdir -p "$HERE/tiles"
echo "[valhalla] building tiles from $PBF (minutes)…"
valhalla_build_tiles -c "$HERE/valhalla.json" "$PBF"

echo "[valhalla] packing mmap extract (tiles.tar)…"
valhalla_build_extract -c "$HERE/valhalla.json" -v || true

echo "[valhalla] done. tiles at $HERE/tiles"
