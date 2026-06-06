"""Offline, deterministic unit tests for traveltime.valhalla_matrix.

No real network: we monkeypatch the HTTP client's ``post`` (the function prefers
``httpx`` and falls back to ``requests``) so it returns a canned *concise* Valhalla
``/sources_to_targets`` body. We then assert the parser produces the right (N, N)
seconds matrix, zeroes the diagonal, and fills ``null`` durations from the haversine
baseline — and that ANY client failure degrades silently to build_travel_time_matrix.

routing/ is on sys.path via tests/conftest.py, so ``import traveltime`` works directly.
"""
from __future__ import annotations

import numpy as np
import pytest

import traveltime  # routing/traveltime.py (on sys.path from tests/conftest.py)

# Three London-ish stops; exact values don't matter, only determinism.
LATS = [51.5074, 51.5155, 51.4946]
LNGS = [-0.1278, -0.0922, -0.0997]


class _FakeResp:
    """Minimal stand-in for an httpx/requests Response."""

    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code

    def json(self):
        return self._body


def _http_module():
    """The module valhalla_matrix will actually call (httpx preferred, else requests)."""
    try:
        import httpx as mod
    except Exception:  # pragma: no cover - httpx ships with FastAPI in this repo
        import requests as mod
    return mod


def test_parses_concise_durations_and_fills_nulls(monkeypatch):
    # durations[1][2] is None -> must fall back to the haversine baseline value.
    durations = [
        [0.0, 120.0, 300.0],
        [125.0, 0.0, None],
        [310.0, 95.0, 0.0],
    ]
    body = {"sources_to_targets": {"durations": durations}}

    captured: dict = {}

    def fake_post(url, json=None, timeout=None, **kw):
        captured["url"] = url
        captured["payload"] = json
        captured["timeout"] = timeout
        return _FakeResp(body)

    monkeypatch.setattr(_http_module(), "post", fake_post)

    M = traveltime.valhalla_matrix(LATS, LNGS, base_url="http://valhalla.test")

    assert M.shape == (3, 3)
    assert M.dtype == np.float64
    assert np.all(np.isfinite(M))
    # Diagonal is always zero.
    assert np.allclose(np.diag(M), 0.0)
    # Non-null entries parsed straight through (seconds).
    assert M[0, 1] == 120.0
    assert M[2, 0] == 310.0
    # The null entry [1][2] is filled from the haversine baseline.
    baseline = traveltime.build_travel_time_matrix(LATS, LNGS)
    assert M[1, 2] == pytest.approx(baseline[1, 2])
    assert M[1, 2] > 0.0
    # Request went to the matrix endpoint with sources == targets == the N stops.
    assert captured["url"] == "http://valhalla.test/sources_to_targets"
    assert captured["timeout"] == 10.0
    assert len(captured["payload"]["sources"]) == 3
    assert captured["payload"]["sources"] == captured["payload"]["targets"]
    assert captured["payload"]["costing"] == "auto"


def test_road_closure_becomes_exclude_polygon(monkeypatch):
    body = {"sources_to_targets": {"durations": [[0, 1, 1], [1, 0, 1], [1, 1, 0]]}}
    captured: dict = {}

    def fake_post(url, json=None, timeout=None, **kw):
        captured["payload"] = json
        return _FakeResp(body)

    monkeypatch.setattr(_http_module(), "post", fake_post)

    disruptions = [
        {
            "kind": "road_closure",
            "geometry": [
                {"lat": 51.50, "lng": -0.12},
                {"lat": 51.51, "lng": -0.11},
                {"lat": 51.50, "lng": -0.10},
            ],
        },
        # A point closure (<3 pts) must NOT produce a polygon.
        {"kind": "traffic", "geometry": [{"lat": 51.49, "lng": -0.13}]},
    ]

    traveltime.valhalla_matrix(LATS, LNGS, disruptions=disruptions)

    polys = captured["payload"]["exclude_polygons"]
    assert len(polys) == 1
    # Valhalla rings are [lon, lat] pairs.
    assert polys[0] == [[-0.12, 51.50], [-0.11, 51.51], [-0.10, 51.50]]


def test_robust_fallback_on_connection_error(monkeypatch):
    mod = _http_module()

    def boom(*a, **kw):
        raise ConnectionError("valhalla down")

    monkeypatch.setattr(mod, "post", boom)

    M = traveltime.valhalla_matrix(LATS, LNGS)
    expected = traveltime.build_travel_time_matrix(LATS, LNGS)

    assert M.shape == expected.shape
    assert np.all(np.isfinite(M))
    assert np.allclose(M, expected)


def test_robust_fallback_on_non_200(monkeypatch):
    def fake_post(url, json=None, timeout=None, **kw):
        return _FakeResp({"error": "boom"}, status_code=503)

    monkeypatch.setattr(_http_module(), "post", fake_post)

    M = traveltime.valhalla_matrix(LATS, LNGS)
    expected = traveltime.build_travel_time_matrix(LATS, LNGS)
    assert M.shape == expected.shape
    assert np.allclose(M, expected)


def test_robust_fallback_on_malformed_body(monkeypatch):
    def fake_post(url, json=None, timeout=None, **kw):
        return _FakeResp({"unexpected": "shape"})  # missing sources_to_targets

    monkeypatch.setattr(_http_module(), "post", fake_post)

    M = traveltime.valhalla_matrix(LATS, LNGS)
    expected = traveltime.build_travel_time_matrix(LATS, LNGS)
    assert M.shape == expected.shape
    assert np.allclose(M, expected)
