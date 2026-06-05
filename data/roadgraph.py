"""London road network + buildings for the frontend traffic layer.

If ``osmnx`` is importable AND a place fetch works we build a small central
London drive graph; OTHERWISE (the default on this box) we synthesise a
plausible connected grid+radial network across the London bbox so the demo
always has roads.

Exports (the one allowed write outside data/):
  * frontend/public/data/roads.geojson      LineStrings, props: congestion, speed
  * frontend/public/data/buildings.geojson  Polygons, prop: height
And graph stats to data/cache/roadgraph_stats.json.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import quality

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
FRONTEND_DATA_DIR = ROOT / "frontend" / "public" / "data"

ROADS_PATH = FRONTEND_DATA_DIR / "roads.geojson"
BUILDINGS_PATH = FRONTEND_DATA_DIR / "buildings.geojson"
STATS_PATH = CACHE_DIR / "roadgraph_stats.json"

# grid resolution across the bbox interior
_GRID_ROWS = 16
_GRID_COLS = 18
# keep a margin so every vertex sits strictly inside the bbox
_MARGIN = 0.01


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _speed_from_congestion(congestion: float) -> float:
    # free-flow ~ 48 km/h, dropping to ~ 8 km/h at full congestion
    return round(8.0 + (48.0 - 8.0) * (1.0 - congestion), 1)


def _build_synthetic(seed: int = 11) -> tuple[dict, dict, dict]:
    rng = random.Random(seed)
    b = quality.LONDON_BBOX
    lat0, lat1 = b["lat_min"] + _MARGIN, b["lat_max"] - _MARGIN
    lng0, lng1 = b["lng_min"] + _MARGIN, b["lng_max"] - _MARGIN

    # grid node coordinates
    lats = [round(_lerp(lat0, lat1, r / (_GRID_ROWS - 1)), 6) for r in range(_GRID_ROWS)]
    lngs = [round(_lerp(lng0, lng1, c / (_GRID_COLS - 1)), 6) for c in range(_GRID_COLS)]

    road_features: list[dict] = []

    def add_road(p0, p1, kind):
        congestion = round(rng.random() ** 1.3, 3)  # skew toward lighter traffic
        road_features.append(
            {
                "type": "Feature",
                "properties": {
                    "kind": kind,
                    "congestion": congestion,
                    "speed": _speed_from_congestion(congestion),
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[p0[1], p0[0]], [p1[1], p1[0]]],
                },
            }
        )

    # horizontal + vertical grid edges -> guaranteed connected
    for r in range(_GRID_ROWS):
        for c in range(_GRID_COLS):
            if c + 1 < _GRID_COLS:
                add_road((lats[r], lngs[c]), (lats[r], lngs[c + 1]), "street")
            if r + 1 < _GRID_ROWS:
                add_road((lats[r], lngs[c]), (lats[r + 1], lngs[c]), "street")

    # a few radial / diagonal arterials connecting existing grid nodes
    cr, cc = _GRID_ROWS // 2, _GRID_COLS // 2
    for _ in range(6):
        r = rng.randint(0, _GRID_ROWS - 1)
        c = rng.randint(0, _GRID_COLS - 1)
        # step diagonally toward centre, linking adjacent grid nodes
        rr, ccur = r, c
        while (rr, ccur) != (cr, cc):
            nr = rr + (1 if cr > rr else -1 if cr < rr else 0)
            nc = ccur + (1 if cc > ccur else -1 if cc < ccur else 0)
            add_road((lats[rr], lngs[ccur]), (lats[nr], lngs[nc]), "arterial")
            rr, ccur = nr, nc

    roads = {"type": "FeatureCollection", "features": road_features}
    buildings = _build_buildings(rng, lats, lngs)
    stats = {
        "source": "synthetic-grid",
        "rows": len(road_features),
        "grid": [_GRID_ROWS, _GRID_COLS],
    }
    return roads, buildings, stats


def _build_buildings(rng: random.Random, lats, lngs) -> dict:
    """A few hundred extruded blocks in the central band, with a height prop."""
    feats: list[dict] = []
    # central band of the grid
    r_lo, r_hi = int(_GRID_ROWS * 0.30), int(_GRID_ROWS * 0.70)
    c_lo, c_hi = int(_GRID_COLS * 0.30), int(_GRID_COLS * 0.70)
    for r in range(r_lo, r_hi):
        for c in range(c_lo, c_hi):
            # several small footprints per grid cell
            for _ in range(3):
                clat = _lerp(lats[r], lats[r + 1], rng.uniform(0.15, 0.85))
                clng = _lerp(lngs[c], lngs[c + 1], rng.uniform(0.15, 0.85))
                dlat = rng.uniform(0.0004, 0.0010)
                dlng = rng.uniform(0.0006, 0.0014)
                ring = [
                    [round(clng - dlng, 6), round(clat - dlat, 6)],
                    [round(clng + dlng, 6), round(clat - dlat, 6)],
                    [round(clng + dlng, 6), round(clat + dlat, 6)],
                    [round(clng - dlng, 6), round(clat + dlat, 6)],
                    [round(clng - dlng, 6), round(clat - dlat, 6)],
                ]
                height = round(rng.uniform(8.0, 120.0), 1)
                feats.append(
                    {
                        "type": "Feature",
                        "properties": {"height": height},
                        "geometry": {"type": "Polygon", "coordinates": [ring]},
                    }
                )
    return {"type": "FeatureCollection", "features": feats}


def _try_osmnx() -> tuple[dict, dict, dict] | None:
    """Best-effort OSMnx central-London graph; None if unavailable/unreachable."""
    try:  # pragma: no cover - not exercised offline
        import osmnx as ox  # noqa: F401
    except Exception:
        return None
    try:  # pragma: no cover
        import osmnx as ox

        g = ox.graph_from_place("City of London, London, UK", network_type="drive")
        nodes, edges = ox.graph_to_gdfs(g)
        road_features = []
        for _, row in edges.iterrows():
            geom = row.geometry
            coords = [[x, y] for x, y in geom.coords]
            if not all(quality.point_in_bbox(y, x) for x, y in geom.coords):
                continue
            congestion = round(random.random(), 3)
            road_features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "kind": "osm",
                        "congestion": congestion,
                        "speed": _speed_from_congestion(congestion),
                    },
                    "geometry": {"type": "LineString", "coordinates": coords},
                }
            )
        if not road_features:
            return None
        roads = {"type": "FeatureCollection", "features": road_features}
        # synthetic buildings still (keeps demo light)
        rng = random.Random(11)
        b = quality.LONDON_BBOX
        lats = [b["lat_min"] + 0.01, b["lat_max"] - 0.01]
        lngs = [b["lng_min"] + 0.01, b["lng_max"] - 0.01]
        buildings = _build_buildings(rng, [lats[0], lats[1]], [lngs[0], lngs[1]])
        stats = {"source": "osmnx", "rows": len(road_features)}
        return roads, buildings, stats
    except Exception:
        return None


def build_roadgraph(allow_network: bool = True) -> dict:
    """Build + export roads/buildings GeoJSON; return summary stats dict."""
    result = _try_osmnx() if allow_network else None
    if result is None:
        result = _build_synthetic()
    roads, buildings, stats = result

    # validate before writing — never export an unverified / disconnected graph.
    graph_stats = quality.validate_roads(roads, require_connected=True)
    stats.update(graph_stats)
    stats["buildings"] = len(buildings["features"])

    FRONTEND_DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ROADS_PATH.write_text(json.dumps(roads))
    BUILDINGS_PATH.write_text(json.dumps(buildings))
    STATS_PATH.write_text(json.dumps(stats, indent=2) + "\n")
    return stats


if __name__ == "__main__":
    s = build_roadgraph()
    print(f"roads -> {ROADS_PATH}")
    print(f"buildings -> {BUILDINGS_PATH}")
    print(f"stats: {s}")
