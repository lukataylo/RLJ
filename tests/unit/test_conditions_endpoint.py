"""Through-the-app tests for the upcoming-conditions endpoint (GET /conditions/upcoming).

The endpoint serves the merged forward-looking pipeline (data/conditions.json) so the
operator and driver can see planned works, bridge lifts, events, floods and major
developments ahead of time, optionally filtered to a courier's location. Offline +
deterministic: it reads the committed artifact and uses its scenario_now.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]

_COLLIDING = (
    "app", "models", "seed", "greedy", "congestion", "geocode", "intake", "nl_intake",
    "agent_actions", "solver", "solver_baseline", "solver_ortools", "solver_aco",
    "solver_ls", "traveltime",
)


def _load_app():
    sys.path.insert(0, str(ROOT / "orchestrator"))
    for mod in _COLLIDING:
        sys.modules.pop(mod, None)
    return importlib.import_module("app")


@pytest.fixture()
def client():
    return TestClient(_load_app().app)


def test_conditions_upcoming_returns_feed(client):
    r = client.get("/conditions/upcoming", params={"within_hours": 24})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] > 0
    cats = {c["category"] for c in body["conditions"]}
    assert cats & {"works", "bridge", "event", "flood", "development"}
    for c in body["conditions"]:
        assert "starts_in_min" in c
        assert {"id", "category", "title", "severity", "lat", "lng"} <= set(c)


def test_conditions_upcoming_horizon_narrows(client):
    wide = client.get("/conditions/upcoming", params={"within_hours": 24}).json()
    narrow = client.get("/conditions/upcoming", params={"within_hours": 1}).json()
    wide_timed = [c for c in wide["conditions"] if c["starts_in_min"] is not None]
    narrow_timed = [c for c in narrow["conditions"] if c["starts_in_min"] is not None]
    assert len(narrow_timed) <= len(wide_timed)


def test_conditions_upcoming_proximity_filter(client):
    full = client.get("/conditions/upcoming", params={"within_hours": 24}).json()
    assert full["count"] > 0
    # Filter tightly around the first condition's own coordinate → at least itself,
    # and never more than the unfiltered feed.
    first = full["conditions"][0]
    near = client.get(
        "/conditions/upcoming",
        params={"within_hours": 24, "lat": first["lat"], "lng": first["lng"], "radius_km": 0.5},
    ).json()
    assert 1 <= near["count"] <= full["count"]


def test_conditions_upcoming_never_5xx_without_args(client):
    r = client.get("/conditions/upcoming")
    assert r.status_code == 200
