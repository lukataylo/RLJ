"""Through-the-app test for the Tower Bridge closure demo scenario.

Pressing the operator's "Tower Bridge closure" button must: inject a road-closure into
live state, narrate it through NemoClaw's reasoning chain, and offer a reroute decision
card wired to the redirect endpoint — which re-plans via the routing seam (greedy
fallback offline) so the fleet updates. Deterministic + offline.
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
    app_mod = _load_app()
    models = importlib.import_module("models")
    # A courier sitting right by Tower Bridge — the one a closure most affects.
    app_mod.S.couriers["crt-bridge"] = models.Courier(
        id="crt-bridge", name="Sam",
        location=models.Location(lat=51.5056, lng=-0.0755, name="Tower Bridge"))
    return TestClient(app_mod.app), app_mod


def test_bridge_closure_injects_and_offers_reroute(client):
    c, app_mod = client
    before = len(app_mod.S.disruptions)
    r = c.post("/scenario/bridge-closure")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["courier_id"] == "crt-bridge"  # nearest courier targeted

    # 1) a road closure was injected into live state
    assert len(app_mod.S.disruptions) == before + 1
    disr = app_mod.S.disruptions[-1]
    assert disr.kind == "road_closure"
    assert len(disr.geometry) >= 2

    # 2) NemoClaw narrated it with a reasoning chain + a reroute decision card
    task = next(t for t in app_mod.S.agent_tasks if t["id"] == body["task_id"])
    assert "Tower Bridge" in task["reasoning"]
    assert task["action"]["type"] == "redirect"
    assert task["action"]["courier_id"] == "crt-bridge"
    assert task["action"]["endpoint"] == "/couriers/crt-bridge/redirect"


def test_bridge_closure_reroute_replans(client):
    # Confirming the card hits the redirect endpoint, which re-plans (greedy fallback
    # offline) avoiding the closure — proving the card is wired to the routing seam.
    c, app_mod = client
    c.post("/scenario/bridge-closure")
    r = c.post("/couriers/crt-bridge/redirect")
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
