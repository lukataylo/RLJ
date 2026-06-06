"""London road network + buildings for the frontend traffic layer.

By default we fetch REAL major central-London roads from OpenStreetMap via the
Overpass API (plain HTTP, no heavy deps): motorway/trunk/primary/secondary ways
inside a central-London bbox, converted to GeoJSON LineStrings. Each road starts
with ``congestion = 0.0`` (the live congestion flywheel fills it in) and a
``speed`` derived from that congestion.

If Overpass is unreachable we FALL BACK to a synthesised, connected grid+radial
network across the London bbox (clearly labelled ``synthetic-grid-fallback``) so
the demo / build / tests always have roads, even fully offline.

Exports (the one allowed write outside data/):
  * frontend/public/data/roads.geojson      LineStrings, props: congestion, speed
  * frontend/public/data/buildings.geojson  Polygons, prop: height
The raw Overpass response is cached to data/cache/overpass_roads.json and graph
stats to data/cache/roadgraph_stats.json.
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
OVERPASS_CACHE_PATH = CACHE_DIR / "overpass_roads.json"

# ---- Overpass (real OpenStreetMap roads) ---------------------------------- #
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "RLJ-PulseGo-data-build/1.0 (central-London traffic demo)"
# Central-London query bbox (south, west, north, east). Comfortably inside the
# Greater-London quality.LONDON_BBOX so every retained vertex passes bbox DQ.
CENTRAL_BBOX = (51.490, -0.165, 51.540, -0.070)
# Major roads only — the arterial network the map renders.
HIGHWAY_KINDS = ("motorway", "trunk", "primary", "secondary")
_OVERPASS_TIMEOUT_S = 60

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


def _grid_coords() -> tuple[list[float], list[float]]:
    b = quality.LONDON_BBOX
    lat0, lat1 = b["lat_min"] + _MARGIN, b["lat_max"] - _MARGIN
    lng0, lng1 = b["lng_min"] + _MARGIN, b["lng_max"] - _MARGIN
    lats = [round(_lerp(lat0, lat1, r / (_GRID_ROWS - 1)), 6) for r in range(_GRID_ROWS)]
    lngs = [round(_lerp(lng0, lng1, c / (_GRID_COLS - 1)), 6) for c in range(_GRID_COLS)]
    return lats, lngs


def _synthetic_buildings(seed: int = 11) -> dict:
    rng = random.Random(seed)
    lats, lngs = _grid_coords()
    return _build_buildings(rng, lats, lngs)


def _build_synthetic(seed: int = 11) -> tuple[dict, dict, dict]:
    rng = random.Random(seed)
    lats, lngs = _grid_coords()

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
        "source": "synthetic-grid-fallback",
        "live": False,
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


def _overpass_query() -> str:
    """Overpass QL: major roads (motorway/trunk/primary/secondary) in CENTRAL_BBOX."""
    s, w, n, e = CENTRAL_BBOX
    bbox = f"{s},{w},{n},{e}"
    highway_re = "|".join(HIGHWAY_KINDS)
    return (
        "[out:json][timeout:50];"
        f'(way["highway"~"^({highway_re})$"]({bbox}););'
        "out geom;"
    )


def _overpass_fetch_raw(query: str) -> dict:
    """POST a query to Overpass and return the parsed JSON. Network seam — tests
    monkeypatch this to a canned response. Raises on any HTTP/parse error."""
    import requests

    resp = requests.post(
        OVERPASS_URL,
        data={"data": query},
        headers={"User-Agent": USER_AGENT},
        timeout=_OVERPASS_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json()


def _parse_overpass(raw: dict) -> list[dict]:
    """Convert an Overpass ``out geom`` response into GeoJSON LineString features.

    Each way -> one LineString with properties:
      * kind       — the OSM highway class (primary/secondary/...)
      * name       — the OSM road name (may be empty)
      * congestion — 0.0 (the live flywheel fills this in)
      * speed      — derived from congestion (free-flow at 0.0)
    Ways with any vertex outside the Greater-London bbox are dropped so the
    exported collection always passes the bbox data-quality gate.
    """
    feats: list[dict] = []
    congestion = 0.0
    speed = _speed_from_congestion(congestion)
    for el in raw.get("elements", []):
        if el.get("type") != "way":
            continue
        geom = el.get("geometry") or []
        coords = [[round(p["lon"], 6), round(p["lat"], 6)] for p in geom if "lat" in p and "lon" in p]
        if len(coords) < 2:
            continue
        if not all(quality.point_in_bbox(lat, lng) for lng, lat in coords):
            continue
        tags = el.get("tags") or {}
        feats.append(
            {
                "type": "Feature",
                "properties": {
                    "kind": tags.get("highway", "road"),
                    "name": tags.get("name", ""),
                    "osm_id": el.get("id"),
                    "congestion": congestion,
                    "speed": speed,
                },
                "geometry": {"type": "LineString", "coordinates": coords},
            }
        )
    return feats


def _node(coord: list[float]) -> tuple[float, float]:
    return (round(coord[1], 6), round(coord[0], 6))


def _connected_subfeatures(features: list[dict]) -> list[dict]:
    """Return features restricted to the largest connected component.

    Real arterial roads clipped to a bbox form several components; the frontend
    and ``validate_roads(require_connected=True)`` want a single connected graph.
    We keep the largest component and re-emit each road as the maximal runs of
    vertices that lie inside it, so every exported edge is within one connected
    sub-graph.
    """
    import networkx as nx

    g = quality.roads_graph({"type": "FeatureCollection", "features": features})
    if g.number_of_nodes() == 0:
        return []
    largest = max(nx.connected_components(g), key=len)

    out: list[dict] = []
    for f in features:
        coords = f["geometry"]["coordinates"]
        run: list[list[float]] = []
        for c in coords:
            if _node(c) in largest:
                run.append(c)
            else:
                if len(run) >= 2:
                    out.append(_feature_with_coords(f, run))
                run = []
        if len(run) >= 2:
            out.append(_feature_with_coords(f, run))
    return out


def _feature_with_coords(template: dict, coords: list[list[float]]) -> dict:
    return {
        "type": "Feature",
        "properties": dict(template["properties"]),
        "geometry": {"type": "LineString", "coordinates": coords},
    }


def _try_overpass() -> tuple[dict, dict, dict] | None:
    """Best-effort REAL central-London roads from Overpass; None on any failure."""
    try:
        raw = _overpass_fetch_raw(_overpass_query())
    except Exception as exc:  # noqa: BLE001
        print(f"[roadgraph] Overpass fetch failed ({exc!r}); falling back to synthetic")
        return None
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        OVERPASS_CACHE_PATH.write_text(json.dumps(raw))
    except Exception:  # noqa: BLE001 - caching is best-effort
        pass

    features = _parse_overpass(raw)
    features = _connected_subfeatures(features)
    if len(features) < 2:
        print("[roadgraph] Overpass returned too few connected roads; falling back")
        return None

    roads = {"type": "FeatureCollection", "features": features}
    buildings = _synthetic_buildings()
    stats = {
        "source": "overpass-osm",
        "live": True,
        "rows": len(features),
        "bbox": list(CENTRAL_BBOX),
        "highway_kinds": list(HIGHWAY_KINDS),
    }
    return roads, buildings, stats


def build_roadgraph(allow_network: bool = True) -> dict:
    """Build + export roads/buildings GeoJSON; return summary stats dict.

    Tries REAL Overpass/OpenStreetMap roads first (when ``allow_network``); on
    any failure falls back to the synthetic connected grid so the build never
    breaks offline.
    """
    result = _try_overpass() if allow_network else None
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
