"""Unit tests for the travel-time matrix cache (traveltime.travel_time_matrix).

The cache is what lets one /optimize make a single Valhalla call instead of one per solver
candidate. We assert: identical calls recompute only once, different coords/disruptions/
backend miss, returned arrays are private copies, and clear_matrix_cache() resets it.

routing/ is on sys.path via tests/conftest.py.
"""
from __future__ import annotations

import numpy as np
import pytest

import traveltime

LATS = [51.5074, 51.5155, 51.4946]
LNGS = [-0.1278, -0.0922, -0.0997]


@pytest.fixture(autouse=True)
def _clean_cache(monkeypatch):
    # No Valhalla in tests → haversine path; start each test with an empty cache.
    monkeypatch.delenv("VALHALLA_URL", raising=False)
    traveltime.clear_matrix_cache()
    yield
    traveltime.clear_matrix_cache()


def _count_builds(monkeypatch):
    calls = {"n": 0}
    real = traveltime.build_travel_time_matrix

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(traveltime, "build_travel_time_matrix", counting)
    return calls


def test_identical_calls_compute_once(monkeypatch):
    calls = _count_builds(monkeypatch)
    m1 = traveltime.travel_time_matrix(LATS, LNGS)
    m2 = traveltime.travel_time_matrix(LATS, LNGS)
    assert calls["n"] == 1                      # second call served from cache
    assert np.allclose(m1, m2)


def test_different_coords_miss(monkeypatch):
    calls = _count_builds(monkeypatch)
    traveltime.travel_time_matrix(LATS, LNGS)
    traveltime.travel_time_matrix(LATS, [l + 0.01 for l in LNGS])
    assert calls["n"] == 2                      # different coords -> recompute


def test_disruptions_change_key(monkeypatch):
    calls = _count_builds(monkeypatch)
    closure = {"kind": "road_closure", "geometry": [{"lat": 51.50, "lng": -0.10}]}
    traveltime.travel_time_matrix(LATS, LNGS)                       # no disruption
    traveltime.travel_time_matrix(LATS, LNGS, disruptions=[closure])  # with closure
    assert calls["n"] == 2
    # courier_down does NOT affect the matrix → same key → cached
    down = {"kind": "courier_down", "geometry": []}
    traveltime.travel_time_matrix(LATS, LNGS, disruptions=[down])
    assert calls["n"] == 2                      # still 2: courier_down ignored in the key


def test_returned_array_is_a_copy(monkeypatch):
    _count_builds(monkeypatch)
    m1 = traveltime.travel_time_matrix(LATS, LNGS)
    m1[0, 1] = 999999.0                         # mutate the caller's copy
    m2 = traveltime.travel_time_matrix(LATS, LNGS)
    assert m2[0, 1] != 999999.0                 # cache untouched


def test_backend_keyed(monkeypatch):
    """A haversine result must never be reused once VALHALLA_URL is set."""
    calls = _count_builds(monkeypatch)
    traveltime.travel_time_matrix(LATS, LNGS)   # haversine, backend=""
    assert calls["n"] == 1
    # Point at a (down) Valhalla; valhalla_matrix degrades to haversine internally, but the
    # cache key differs by backend, so it must NOT serve the prior haversine entry blindly.
    monkeypatch.setenv("VALHALLA_URL", "http://localhost:9/unreachable")
    traveltime.travel_time_matrix(LATS, LNGS)
    # valhalla_matrix's fallback calls build_travel_time_matrix again → recompute happened.
    assert calls["n"] == 2


def test_clear_cache(monkeypatch):
    calls = _count_builds(monkeypatch)
    traveltime.travel_time_matrix(LATS, LNGS)
    traveltime.clear_matrix_cache()
    traveltime.travel_time_matrix(LATS, LNGS)
    assert calls["n"] == 2
