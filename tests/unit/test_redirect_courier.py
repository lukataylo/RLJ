"""Through-the-app tests for the targeted per-courier mid-delivery redirect.

Redirecting one courier must genuinely re-route *that* courier — we inject a localized
avoidance just ahead of them (on the leg to their next stop) so the re-plan bends their
route around it — and must notify that driver. Unknown couriers 404. Offline + deterministic
(routing service down → greedy fallback still returns a plan).
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
    c = TestClient(app_mod.app)
    c.post("/demo/seed")  # couriers + jobs + a plan (greedy fallback offline)
    return c, app_mod


def test_redirect_specific_courier_injects_targeted_avoidance(client):
    c, app_mod = client
    cid = next(iter(app_mod.S.couriers))  # a real seeded courier (scooter/van)
    before = len(app_mod.S.disruptions)
    r = c.post(f"/couriers/{cid}/redirect", params={"reason": "incident on the bridge approach"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["courier_id"] == cid
    assert body["vehicle_type"] in ("van", "scooter", "bike")
    assert body["targeted"] is True
    # a courier-scoped avoidance was injected ahead of this courier
    assert len(app_mod.S.disruptions) == before + 1
    injected = app_mod.S.disruptions[-1]
    assert injected.courier_id == cid
    assert len(injected.geometry) >= 2


def test_redirect_unknown_courier_404(client):
    c, _ = client
    r = c.post("/couriers/does-not-exist/redirect")
    assert r.status_code == 404


def test_redirect_without_plan_still_ok(client):
    # No plan/route → can't target, but the redirect must still succeed (re-optimise).
    c, app_mod = client
    cid = next(iter(app_mod.S.couriers))
    app_mod.S.plan = None
    r = c.post(f"/couriers/{cid}/redirect")
    assert r.status_code == 200, r.text
    assert r.json()["targeted"] is False
