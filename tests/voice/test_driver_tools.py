"""Driver-assistant tools — happy + unhappy flows.

The orchestrator HTTP layer (`driver_tools._get`) is monkeypatched so these are fully
deterministic and offline. Happy = orchestrator returns data → tools parse it correctly;
unhappy = orchestrator unreachable → every tool degrades to an `{"error": ...}` dict
(never raises), which is the contract the agent relies on.
"""
from __future__ import annotations

import driver_tools as dt

# Tower Bridge centre (from driver_tools.BRIDGES) for geometry-match tests.
TOWER = dt.BRIDGES["Tower Bridge"]


def _patch(monkeypatch, responses: dict):
    """Patch _get so each path returns a canned payload (or an error dict)."""
    def fake_get(path, params=None):
        for key, val in responses.items():
            if path.startswith(key):
                return val
        return {"error": f"no canned response for {path}"}
    monkeypatch.setattr(dt, "_get", fake_get)


# ------------------------------------------------------------------ happy flows
def test_get_guidance_parsed(monkeypatch):
    _patch(monkeypatch, {"/driver/": {
        "driver_id": "drv-1", "status": "en route", "eta": "2026-06-06T14:25:00Z",
        "signal_advice": {"message": "Ease to 18 mph", "target_speed_mps": 8.0},
        "contribution": {"pings": 412, "couriers_helped": 7},
    }})
    g = dt.get_guidance("drv-1")
    assert g["status"] == "en route" and g["eta"].endswith("Z")
    assert g["signal_message"] == "Ease to 18 mph" and g["target_speed_mps"] == 8.0
    assert g["pings"] == 412 and g["couriers_helped"] == 7


def test_get_congestion_ranks_hotspots(monkeypatch):
    _patch(monkeypatch, {"/congestion": {"cells": [
        {"cell": "a", "lat": 51.5, "lng": -0.1, "congestion": 0.3, "speed_mps": 6},
        {"cell": "b", "lat": 51.51, "lng": -0.09, "congestion": 0.81, "speed_mps": 2},
        {"cell": "c", "lat": 51.52, "lng": -0.08, "congestion": 0.66, "speed_mps": 3},
    ]}})
    c = dt.get_congestion()
    assert c["n_cells"] == 3
    assert c["worst_congestion"] == 0.81  # ranked descending
    assert c["hotspots"][0]["cell"] == "b" and len(c["hotspots"]) == 3


def test_bridge_status_closed_when_disruption_on_bridge(monkeypatch):
    _patch(monkeypatch, {"/state": {"disruptions": [
        {"kind": "road_closure", "geometry": [{"lat": TOWER["lat"], "lng": TOWER["lng"]}]},
    ]}})
    s = dt.bridge_status("Tower Bridge")
    assert s["open"] is False
    assert "Tower Bridge" in s["closed_bridges"] and s["any_bridge_closed"] is True


def test_bridge_status_open_when_no_disruptions(monkeypatch):
    _patch(monkeypatch, {"/state": {"disruptions": []}})
    s = dt.bridge_status("Tower Bridge")
    assert s["open"] is True and s["closed_bridges"] == []


def test_reroute_reason_summarises_disruptions(monkeypatch):
    _patch(monkeypatch, {
        "/driver/": {"driver_id": "drv-1", "status": "en route"},
        "/state": {"disruptions": [{"kind": "road_closure"}, {"kind": "traffic"}]},
    })
    r = dt.reroute_reason("drv-1")
    assert "2 active disruption" in r["reason"]
    assert r["disruptions"] == ["road_closure", "traffic"]


def test_next_pickup_from_guidance(monkeypatch):
    _patch(monkeypatch, {"/driver/": {
        "driver_id": "drv-1", "status": "heading to St Thomas' lab", "eta": "2026-06-06T14:25:00Z",
        "signal_advice": {}, "contribution": {},
    }})
    n = dt.next_pickup("drv-1")
    assert n["status"] == "heading to St Thomas' lab" and n["eta"].endswith("Z")


# ---------------------------------------------------------------- unhappy flows
def test_all_tools_degrade_when_orchestrator_down(monkeypatch):
    monkeypatch.setattr(dt, "_get", lambda path, params=None: {"error": "orchestrator unreachable"})
    assert "error" in dt.get_guidance("drv-1")
    assert "error" in dt.get_signal_advice("drv-1", 51.5, -0.07, 0)
    assert "error" in dt.get_congestion()
    assert "error" in dt.bridge_status("Tower Bridge")
    assert "error" in dt.next_pickup("drv-1")
    # reroute_reason is resilient: still returns a reason even with /state down
    rr = dt.reroute_reason("drv-1")
    assert "reason" in rr


def test_get_never_raises_on_dead_host(monkeypatch):
    # Point at a closed port — real _get must return an error dict, not raise.
    monkeypatch.setattr(dt, "ORCHESTRATOR_URL", "http://127.0.0.1:59231")
    out = dt._get("/state")
    assert isinstance(out, dict) and "error" in out


# --------------------------------------------------------------- pure helpers
def test_canonical_bridge_mapping():
    assert dt._canonical_bridge("is tower bridge open") == "Tower Bridge"
    assert dt._canonical_bridge("waterloo") == "Waterloo Bridge"
    assert dt._canonical_bridge("nonsense") == "Tower Bridge"  # safe default


def test_haversine_zero_and_positive():
    assert dt._haversine_m(51.5, -0.1, 51.5, -0.1) == 0
    assert dt._haversine_m(51.5, -0.1, 51.51, -0.1) > 100
