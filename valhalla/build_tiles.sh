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

if [[ ! -f "$PBF" ]]; then
  echo "OSM extract not found: $PBF — run: .venv/bin/python data/osm_fetch.py" >&2
  exit 1
fi

echo "[valhalla] generating config -> $HERE/valhalla.json"
"$VENV/valhalla_build_config" \
  --mjolnir-tile-dir "$HERE/tiles" \
  --mjolnir-tile-extract "$HERE/tiles.tar" \
  > "$HERE/valhalla.json"

mkdir -p "$HERE/tiles"
echo "[valhalla] building tiles from $PBF (minutes)…"
"$VENV/valhalla_build_tiles" -c "$HERE/valhalla.json" "$PBF"

echo "[valhalla] packing mmap extract (tiles.tar)…"
"$VENV/valhalla_build_extract" -c "$HERE/valhalla.json" -v || true

echo "[valhalla] done. tiles at $HERE/tiles"
