"""Live offline-routing check: the Valhalla road-graph tier over real London tiles.

Skips automatically when no Valhalla server is reachable (dev box / CI), so the gate
stays green there; it verifies on the GB10 demo box where `valhalla/serve.sh` is up and
``VALHALLA_URL`` points at it. Proves the router plans over the **real** London road
network (offline), not the haversine baseline.
"""
from __future__ import annotations

import os
import urllib.request

import numpy as np
import pytest

import traveltime  # routing/ is on sys.path via tests/conftest.py

VALHALLA_URL = os.environ.get("VALHALLA_URL", "http://localhost:8002")

# A few real central-London points (Westminster, Euston, Holborn, Waterloo).
LATS = [51.4995, 51.5281, 51.5174, 51.5031]
LNGS = [-0.1248, -0.1337, -0.1180, -0.1132]


def _valhalla_reachable() -> bool:
    try:
        with urllib.request.urlopen(f"{VALHALLA_URL.rstrip('/')}/status", timeout=3) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001 - unreachable -> skip
        return False


pytestmark = pytest.mark.skipif(
    not _valhalla_reachable(), reason="no Valhalla server reachable (offline dev/CI)"
)


def test_valhalla_matrix_is_real_finite_and_plausible():
    """Live matrix over real London roads: finite, zero diagonal, city-scale times."""
    M = traveltime.valhalla_matrix(LATS, LNGS, base_url=VALHALLA_URL)
    n = len(LATS)
    assert M.shape == (n, n)
    assert np.all(np.isfinite(M))
    assert np.allclose(np.diag(M), 0.0)
    off = M[~np.eye(n, dtype=bool)]
    assert np.all(off > 0)
    # central-London hops: seconds, comfortably under an hour.
    assert off.max() < 3600


def test_dispatcher_uses_valhalla_when_env_set(monkeypatch):
    """travel_time_matrix() routes through Valhalla (real roads) when VALHALLA_URL is set,
    and the result differs from the straight-line haversine baseline."""
    monkeypatch.setenv("VALHALLA_URL", VALHALLA_URL)
    real = traveltime.travel_time_matrix(LATS, LNGS)
    haversine = traveltime.build_travel_time_matrix(LATS, LNGS)
    assert real.shape == haversine.shape
    assert np.all(np.isfinite(real))
    # real road-network durations are not identical to the great-circle model.
    assert not np.allclose(real, haversine)
