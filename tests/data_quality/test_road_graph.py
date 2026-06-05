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
