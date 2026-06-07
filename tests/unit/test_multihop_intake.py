"""Offline tests for capacity- + cold-chain-aware MULTI-HOP /intake.

Exercises the orchestrator's POST /intake through a FastAPI TestClient with the
LLM forced down (deterministic regex parse) and Valhalla patched so the route
preview is hermetic. We assert the ORDERING/response envelope (weights → cold-chain
note; units/capacity → trip splits); the fleet jobs go to the real greedy solver
which already enforces capacity/cold separately.

orchestrator/ is put at the FRONT of sys.path (same import-collision trick as
tests/unit/test_intake_geocode.py) so the bare ``import app`` is the orchestrator's.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]

_COLLIDING = (
    "app", "models", "seed", "greedy", "congestion", "geocode", "nl_intake",
    "route_preview", "solver", "solver_baseline", "solver_ortools",
    "solver_aco", "solver_ls", "traveltime",
)


def _load(modname: str):
    sys.path.insert(0, str(ROOT / "orchestrator"))
    for mod in _COLLIDING:
        sys.modules.pop(mod, None)
    return importlib.import_module(modname)


def _patch_valhalla(monkeypatch):
    """Make route_preview deterministic + offline: a usable duration matrix and a
    fixed 2-point road leg per trip (so polylines are non-empty and concatenable)."""
    rp = sys.modules["route_preview"]
    leg = [{"lat": 51.5074, "lng": -0.1278}, {"lat": 51.5085, "lng": -0.1290}]

    def fake_matrix(lats, lngs, **kwargs):
        n = len(lats)
        # simple, symmetric, strictly-positive off-diagonal matrix
        return [[0.0 if i == j else float(10 * (abs(i - j) + 1))
                 for j in range(n)] for i in range(n)]

    monkeypatch.setattr(rp, "valhalla_matrix_durations", fake_matrix)
    monkeypatch.setattr(rp, "valhalla_route_shape",
                        lambda lats, lngs, **k: list(leg))


@pytest.fixture()
def client(monkeypatch):
    app_mod = _load("app")
    intake = sys.modules["nl_intake"]
    monkeypatch.setattr(intake.llm, "complete_json", lambda *a, **k: None)
    _patch_valhalla(monkeypatch)
    return TestClient(app_mod.app)


def test_intake_coldchain_multidrop_prioritised(client):
    # Cold-chain (blood) multi-drop -> 2 jobs, cold-chain noted in the message.
    r = client.post("/intake", json={
        "text": "cold blood from Guy's to St Thomas' and also Moorfields"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True, body
    assert len(body["jobs"]) == 2
    assert len(body["resolved"]["destinations"]) == 2
    # every created job carries the cold-chain flag
    assert all(j["cold_chain"] is True for j in body["jobs"])
    assert body["order"][0] == "Guy's Hospital"
    assert "cold-chain prioritised" in body["message"]
    # 2 units, default cap 6 -> single trip
    assert body["trips"] == 1
    # patched Valhalla -> a drawable combined polyline
    assert len(body["route"]) >= 2


def test_intake_over_capacity_splits_into_trips(client, monkeypatch):
    # cap 1 unit/trip, 3 unit-1 drops -> at least 3 trips in the response.
    monkeypatch.setenv("TRIP_CAPACITY", "1")
    r = client.post("/intake", json={
        "text": "urgent meds from Guy's to St Thomas' and also Moorfields "
                "and also King's Cross"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True, body
    assert len(body["jobs"]) == 3
    assert body["trips"] >= 3
    assert "trips" in body["message"]  # message reflects the split
    assert body["order"][0] == "Guy's Hospital"
