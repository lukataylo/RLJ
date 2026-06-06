"""Road graph DQ — exported network is non-empty, in-bbox and connected."""
from __future__ import annotations

import json

import networkx as nx
import quality
import roadgraph as roadgraph_mod


def test_graph_connected_and_bbox():
    # build (offline -> synthetic) and load the exported GeoJSON
    roadgraph_mod.build_roadgraph(allow_network=False)
    roads = json.loads(roadgraph_mod.ROADS_PATH.read_text())

    # non-empty
    assert roads["features"], "no road features exported"

    # every vertex inside the London bbox + every road has congestion/speed
    quality.validate_geojson_bbox(roads)
    for f in roads["features"]:
        c = f["properties"]["congestion"]
        assert 0.0 <= c <= 1.0, f"congestion out of range: {c}"
        assert f["properties"]["speed"] > 0

    # connected graph
    g = quality.roads_graph(roads)
    assert g.number_of_edges() > 0
    assert nx.is_connected(g), (
        f"road graph not connected: {nx.number_connected_components(g)} components"
    )

    # buildings exported with height
    buildings = json.loads(roadgraph_mod.BUILDINGS_PATH.read_text())
    assert buildings["features"], "no buildings exported"
    assert all(f["properties"]["height"] > 0 for f in buildings["features"])
    quality.validate_geojson_bbox(buildings)


# --------------------------------------------------------------------------- #
# LIVE Overpass / OpenStreetMap path — HTTP mocked (deterministic + offline).
# --------------------------------------------------------------------------- #
def _canned_overpass() -> dict:
    """Three connected ways (shared junction nodes) inside CENTRAL_BBOX, plus one
    way outside the London bbox that must be dropped on parse."""
    A = {"lat": 51.5100, "lon": -0.1200}
    B = {"lat": 51.5110, "lon": -0.1180}
    C = {"lat": 51.5120, "lon": -0.1160}
    D = {"lat": 51.5130, "lon": -0.1150}
    E = {"lat": 51.5140, "lon": -0.1130}
    out_of_bbox = [{"lat": 52.5000, "lon": -1.5000}, {"lat": 52.5010, "lon": -1.5010}]
    return {
        "elements": [
            {"type": "way", "id": 1, "tags": {"highway": "primary", "name": "Test Primary"},
             "geometry": [A, B, C]},
            {"type": "way", "id": 2, "tags": {"highway": "secondary", "name": "Test Secondary"},
             "geometry": [C, D]},
            {"type": "way", "id": 3, "tags": {"highway": "trunk", "name": "Test Trunk"},
             "geometry": [D, E]},
            {"type": "way", "id": 4, "tags": {"highway": "primary", "name": "Out Of Bounds"},
             "geometry": out_of_bbox},
            {"type": "node", "id": 99, "lat": A["lat"], "lon": A["lon"]},  # ignored
        ]
    }


def test_overpass_live_roads_parsed_and_connected(monkeypatch, tmp_path):
    monkeypatch.setattr(roadgraph_mod, "_overpass_fetch_raw", lambda q: _canned_overpass())
    monkeypatch.setattr(roadgraph_mod, "OVERPASS_CACHE_PATH", tmp_path / "overpass_roads.json")

    stats = roadgraph_mod.build_roadgraph(allow_network=True)
    assert stats["live"] is True
    assert stats["source"] == "overpass-osm"

    # the raw response was cached
    assert (tmp_path / "overpass_roads.json").exists()

    roads = json.loads(roadgraph_mod.ROADS_PATH.read_text())
    feats = roads["features"]
    assert feats, "no live roads exported"

    # the out-of-bbox way was dropped; everything left is in-bbox.
    quality.validate_geojson_bbox(roads)
    names = {f["properties"].get("name") for f in feats}
    assert "Out Of Bounds" not in names

    # congestion starts at 0.0 (flywheel fills it); speed is positive free-flow.
    for f in feats:
        assert f["properties"]["congestion"] == 0.0
        assert f["properties"]["speed"] > 0
        assert f["properties"]["kind"] in roadgraph_mod.HIGHWAY_KINDS

    # the exported network is a single connected component.
    g = quality.roads_graph(roads)
    assert g.number_of_edges() > 0
    assert nx.is_connected(g)


def test_overpass_failure_falls_back_to_synthetic(monkeypatch):
    def _boom(_q):
        raise RuntimeError("overpass unreachable")

    monkeypatch.setattr(roadgraph_mod, "_overpass_fetch_raw", _boom)

    stats = roadgraph_mod.build_roadgraph(allow_network=True)
    assert stats["live"] is False
    assert stats["source"] == "synthetic-grid-fallback"

    roads = json.loads(roadgraph_mod.ROADS_PATH.read_text())
    quality.validate_geojson_bbox(roads)
    g = quality.roads_graph(roads)
    assert nx.is_connected(g)
