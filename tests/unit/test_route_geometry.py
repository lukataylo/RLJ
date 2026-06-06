"""Offline, hermetic tests for routing/route_geometry.py.

routing/ is on sys.path via tests/conftest.py, so `import route_geometry` works.
No real network: the HTTP client is monkeypatched with a fake that returns a
canned Valhalla `/route` response.
"""
from __future__ import annotations

import route_geometry
from route_geometry import decode_polyline6, valhalla_route_shape


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
