"""Offline, hermetic tests for routing/route_geometry.py.

routing/ is on sys.path via tests/conftest.py, so `import route_geometry` works.
No real network: the HTTP client is monkeypatched with a fake that returns a
canned Valhalla `/route` response.
"""
from __future__ import annotations

import route_geometry
from route_geometry import decode_polyline6, valhalla_route_shape

# The orchestrator's own copy adds the multi-stop matrix + optimiser (module name
# `route_preview` doesn't collide with routing's `route_geometry`).
import route_preview


def _encode_polyline6(coords, precision: int = 6) -> str:
    """Reference Google-polyline encoder (precision 6) — for building test fixtures."""
    factor = 10 ** precision
    out = []
    prev_lat = 0
    prev_lng = 0
    for lat, lng in coords:
        ilat = int(round(lat * factor))
        ilng = int(round(lng * factor))
        for delta in (ilat - prev_lat, ilng - prev_lng):
            v = delta << 1
            if delta < 0:
                v = ~v
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1F)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        prev_lat, prev_lng = ilat, ilng
    return "".join(out)


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


# --- decoder ------------------------------------------------------------------------
def test_decode_polyline6_roundtrip():
    pts = [
        [51.5074, -0.1278],   # London
        [51.5079, -0.1281],
        [51.5085, -0.1290],
    ]
    encoded = _encode_polyline6(pts)
    decoded = decode_polyline6(encoded)
    assert len(decoded) == len(pts)
    for (gla, gln), (la, ln) in zip(pts, decoded):
        assert abs(gla - la) < 1e-5
        assert abs(gln - ln) < 1e-5


def test_decode_polyline6_empty():
    assert decode_polyline6("") == []


# --- valhalla_route_shape: happy path -----------------------------------------------
def test_valhalla_route_shape_decodes_legs(monkeypatch):
    leg1 = [[51.5074, -0.1278], [51.5079, -0.1281], [51.5085, -0.1290]]
    payload = {"trip": {"legs": [{"shape": _encode_polyline6(leg1)}]}}

    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _FakeResp(payload)

    # route_geometry imports httpx lazily inside the function; patch that module.
    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)

    shape = valhalla_route_shape(
        [51.5074, 51.5085], [-0.1278, -0.1290], base_url="http://valhalla:8002"
    )

    assert captured["url"] == "http://valhalla:8002/route"
    assert captured["json"]["costing"] == "auto"
    assert captured["json"]["locations"][0] == {"lat": 51.5074, "lon": -0.1278, "type": "break"}
    assert len(shape) == len(leg1)
    for (gla, gln), p in zip(leg1, shape):
        assert abs(p["lat"] - gla) < 1e-5
        assert abs(p["lng"] - gln) < 1e-5


def test_valhalla_route_shape_concats_and_dedupes_legs(monkeypatch):
    # Two legs that share the boundary point [51.5079, -0.1281].
    leg1 = [[51.5074, -0.1278], [51.5079, -0.1281]]
    leg2 = [[51.5079, -0.1281], [51.5085, -0.1290]]
    payload = {"trip": {"legs": [
        {"shape": _encode_polyline6(leg1)},
        {"shape": _encode_polyline6(leg2)},
    ]}}

    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResp(payload))

    shape = valhalla_route_shape([51.5074, 51.5079, 51.5085], [-0.1278, -0.1281, -0.1290])
    # 2 + 2 points minus the deduped shared boundary = 3 unique points.
    assert len(shape) == 3


# --- robust fallback ----------------------------------------------------------------
def test_valhalla_route_shape_returns_empty_on_client_error(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("valhalla down")

    import httpx
    monkeypatch.setattr(httpx, "post", boom)

    assert valhalla_route_shape([51.5, 51.6], [-0.1, -0.2]) == []


def test_valhalla_route_shape_returns_empty_on_non_200(monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResp({}, status_code=503))
    assert valhalla_route_shape([51.5, 51.6], [-0.1, -0.2]) == []


def test_valhalla_route_shape_returns_empty_on_malformed_body(monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResp({"nope": True}))
    assert valhalla_route_shape([51.5, 51.6], [-0.1, -0.2]) == []


def test_valhalla_route_shape_requires_two_points(monkeypatch):
    # Should not even attempt an HTTP call with <2 points.
    def boom(*a, **k):
        raise AssertionError("should not POST with <2 points")

    import httpx
    monkeypatch.setattr(httpx, "post", boom)
    assert valhalla_route_shape([51.5], [-0.1]) == []


# --- valhalla_matrix_durations (orchestrator route_preview) --------------------------
def _matrix_payload(matrix):
    """Valhalla /sources_to_targets shape: rows of {time, distance} cells."""
    return {"sources_to_targets": [[{"time": t, "distance": t} for t in row]
                                   for row in matrix]}


def test_valhalla_matrix_durations_parses_sources_to_targets(monkeypatch):
    matrix = [[0, 100, 50], [100, 0, 30], [50, 30, 0]]
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _FakeResp(_matrix_payload(matrix))

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)

    out = route_preview.valhalla_matrix_durations(
        [51.50, 51.51, 51.52], [-0.10, -0.11, -0.12], base_url="http://valhalla:8002")

    assert captured["url"] == "http://valhalla:8002/sources_to_targets"
    assert captured["json"]["verbose"] is False
    assert captured["json"]["sources"] == captured["json"]["targets"]
    assert out == [[0.0, 100.0, 50.0], [100.0, 0.0, 30.0], [50.0, 30.0, 0.0]]


def test_valhalla_matrix_durations_none_on_error(monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("down")))
    assert route_preview.valhalla_matrix_durations([51.5, 51.6], [-0.1, -0.2]) is None
    # non-200 too
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResp({}, status_code=503))
    assert route_preview.valhalla_matrix_durations([51.5, 51.6], [-0.1, -0.2]) is None


# --- optimized_route (orchestrator route_preview) -----------------------------------
def _route_dispatch(matrix, route_leg):
    """Fake httpx.post dispatching by URL to matrix vs route responses."""
    def fake_post(url, json=None, timeout=None):
        if url.endswith("/sources_to_targets"):
            return _FakeResp(_matrix_payload(matrix))
        if url.endswith("/route"):
            return _FakeResp({"trip": {"legs": [{"shape": _encode_polyline6(route_leg)}]}})
        raise AssertionError(f"unexpected url {url}")
    return fake_post


def test_optimized_route_nearest_neighbour_orders_by_proximity(monkeypatch):
    # origin=0; from 0, drop 2 (50) is nearer than drop 1 (100) -> order [0, 2, 1].
    matrix = [[0, 100, 50], [100, 0, 30], [50, 30, 0]]
    leg = [[51.5074, -0.1278], [51.5085, -0.1290]]

    import httpx
    monkeypatch.setattr(httpx, "post", _route_dispatch(matrix, leg))

    out = route_preview.optimized_route(
        [51.50, 51.51, 51.52], [-0.10, -0.11, -0.12], base_url="http://valhalla:8002")
    assert out["order"][0] == 0           # origin fixed first
    assert out["order"] == [0, 2, 1]      # nearest-neighbour + 2-opt
    assert len(out["polyline"]) >= 2      # road geometry drawn through the order


def test_optimized_route_falls_back_to_input_order_when_no_matrix(monkeypatch):
    # Matrix unavailable -> keep input order, still draw geometry.
    leg = [[51.5074, -0.1278], [51.5085, -0.1290]]
    monkeypatch.setattr(route_preview, "valhalla_matrix_durations", lambda *a, **k: None)

    import httpx
    monkeypatch.setattr(httpx, "post",
                        lambda *a, **k: _FakeResp({"trip": {"legs": [{"shape": _encode_polyline6(leg)}]}}))

    out = route_preview.optimized_route([51.50, 51.51, 51.52], [-0.10, -0.11, -0.12])
    assert out["order"] == [0, 1, 2]


def test_optimized_route_never_raises(monkeypatch):
    # Valhalla down -> matrix/shape degrade to None/[]; identity order, empty
    # polyline, one (empty) trip. No exception bubbles up.
    def boom(*a, **k):
        raise ConnectionError("valhalla down")

    import httpx
    monkeypatch.setattr(httpx, "post", boom)
    out = route_preview.optimized_route([51.50, 51.51, 51.52], [-0.10, -0.11, -0.12])
    assert out["order"] == [0, 1, 2]
    assert out["polyline"] == []
    assert out["splits"] == 1
    assert out["trips"] == [{"order": [0, 1, 2], "polyline": []}]


# --- optimized_route: capacity + cold-chain/priority awareness -----------------------
def test_optimized_route_backcompat_no_weights_no_capacity(monkeypatch):
    # Without weights/capacity: same shortest-time NN+2-opt order as before, plus
    # the new trips/splits envelope (one trip, no split).
    matrix = [[0, 100, 50], [100, 0, 30], [50, 30, 0]]
    leg = [[51.5074, -0.1278], [51.5085, -0.1290]]
    import httpx
    monkeypatch.setattr(httpx, "post", _route_dispatch(matrix, leg))

    out = route_preview.optimized_route([51.50, 51.51, 51.52], [-0.10, -0.11, -0.12])
    assert out["order"] == [0, 2, 1]      # unchanged shortest-time ordering
    assert out["splits"] == 1
    assert len(out["trips"]) == 1
    assert out["trips"][0]["order"] == [0, 2, 1]
    assert out["polyline"] == out["trips"][0]["polyline"]


def test_optimized_route_weights_pull_urgent_drop_earlier(monkeypatch):
    # Pure distance from origin: drop1(idx1) near (10), drop2(idx2) far (20)
    # -> shortest-time order visits idx1 first => [0, 1, 2].
    # idx2 is the high-weight (cold/STAT) drop; with these distances the weighted
    # objective (Σ wᵢ·tᵢ) is minimised by serving the urgent far drop FIRST.
    matrix = [
        [0,  10, 20],
        [10, 0,  30],
        [20, 30, 0],
    ]
    leg = [[51.5074, -0.1278], [51.5085, -0.1290]]
    import httpx
    monkeypatch.setattr(httpx, "post", _route_dispatch(matrix, leg))

    # sanity: without weights, the near drop (idx1) is visited first
    plain = route_preview.optimized_route(
        [51.50, 51.51, 51.52], [-0.10, -0.11, -0.12])
    assert plain["order"] == [0, 1, 2]

    weighted = route_preview.optimized_route(
        [51.50, 51.51, 51.52], [-0.10, -0.11, -0.12],
        weights=[0, 1, 5])  # idx2 far but most urgent
    assert weighted["order"][0] == 0
    # the urgent far drop is delivered before the cheap near one
    assert weighted["order"].index(2) < weighted["order"].index(1)


def test_optimized_route_capacity_splits_into_trips(monkeypatch):
    # 3 drops, 1 unit each, capacity 2 -> 2 trips: [0,a,b] then [0,c].
    matrix = [
        [0,  10, 20, 30],
        [10, 0,  12, 22],
        [20, 12, 0,  10],
        [30, 22, 10, 0],
    ]
    leg = [[51.5074, -0.1278], [51.5085, -0.1290]]
    import httpx
    monkeypatch.setattr(httpx, "post", _route_dispatch(matrix, leg))

    out = route_preview.optimized_route(
        [51.50, 51.51, 51.52, 51.53], [-0.10, -0.11, -0.12, -0.13],
        units=[1, 1, 1], capacity=2)
    assert out["splits"] == 2
    assert len(out["trips"]) == 2
    # each trip is origin + its chunk, with ≤ capacity drops
    for trip in out["trips"]:
        assert trip["order"][0] == 0
        assert len(trip["order"]) - 1 <= 2
    # all drops covered exactly once across trips, origin per trip
    drops = [i for trip in out["trips"] for i in trip["order"][1:]]
    assert sorted(drops) == [1, 2, 3]
    # combined polyline is the concatenation of the per-trip polylines
    assert out["polyline"] == out["trips"][0]["polyline"] + out["trips"][1]["polyline"]


def test_optimized_route_capacity_respects_per_drop_units(monkeypatch):
    # Heavy drops: units [2,2,2], capacity 3 -> each drop alone => 3 trips.
    matrix = [
        [0,  10, 20, 30],
        [10, 0,  12, 22],
        [20, 12, 0,  10],
        [30, 22, 10, 0],
    ]
    leg = [[51.5074, -0.1278], [51.5085, -0.1290]]
    import httpx
    monkeypatch.setattr(httpx, "post", _route_dispatch(matrix, leg))

    out = route_preview.optimized_route(
        [51.50, 51.51, 51.52, 51.53], [-0.10, -0.11, -0.12, -0.13],
        units=[2, 2, 2], capacity=3)
    assert out["splits"] == 3
    for trip in out["trips"]:
        assert len(trip["order"]) == 2  # origin + a single drop


def test_optimized_route_unlimited_capacity_single_trip(monkeypatch):
    matrix = [[0, 100, 50], [100, 0, 30], [50, 30, 0]]
    leg = [[51.5074, -0.1278], [51.5085, -0.1290]]
    import httpx
    monkeypatch.setattr(httpx, "post", _route_dispatch(matrix, leg))

    out = route_preview.optimized_route(
        [51.50, 51.51, 51.52], [-0.10, -0.11, -0.12],
        units=[5, 5], capacity=None)
    assert out["splits"] == 1


def test_optimized_route_capacity_never_raises(monkeypatch):
    # Valhalla down + capacity: still degrades gracefully (no matrix -> identity
    # order, empty polylines) while honouring the split. Never raises.
    import httpx
    monkeypatch.setattr(httpx, "post",
                        lambda *a, **k: (_ for _ in ()).throw(ConnectionError("down")))
    out = route_preview.optimized_route(
        [51.50, 51.51, 51.52], [-0.10, -0.11, -0.12],
        weights=[0, 1, 2], units=[1, 1], capacity=1)
    assert out["order"] == [0, 1, 2]
    assert out["polyline"] == []
    assert out["splits"] == 2  # 2 units, cap 1 -> two (empty) trips
    assert all(t["polyline"] == [] for t in out["trips"])
