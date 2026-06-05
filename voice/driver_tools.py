"""Typed tool functions for the driver-assistant agent.

Each function is a small, side-effect-free *tool* the conversational agent can call to
answer a delivery-driver's question. They speak only to the orchestrator hub
(`http://localhost:8000`, `ORCHESTRATOR_URL`) through the contracts in
`../contracts/driver-api.md` and `../contracts/api.md` — never the routing service.

Design rules (mirroring the rest of voice/):
- Every call is fully guarded: if the orchestrator is unreachable (or an endpoint is not
  yet implemented) the tool returns a small ``{"error": ...}`` dict instead of raising,
  so the agent loop never crashes and the demo survives "pull the network cable".
- Returns are intentionally *small* dicts shaped for spoken answers, not raw entities.

Endpoints used (driver-api.md / api.md):
  GET /driver/{id}/guidance   -> DriverGuidance
  GET /signals/advice         -> SignalAdvice   (query: driver_id, lat, lng, heading)
  GET /congestion             -> CongestionField
  GET /state                  -> {jobs, couriers, plan, disruptions}
"""
from __future__ import annotations

import math
import os
from typing import Any, Optional

import httpx

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000").rstrip("/")
HTTP_TIMEOUT_S = float(os.getenv("DRIVER_HTTP_TIMEOUT_S", "8"))

# Approximate WGS84 centres of the Thames road bridges, for bridge_status to match
# disruption geometry against. London bbox lat 51.28–51.69, lng −0.51–0.33.
BRIDGES: dict[str, dict[str, float]] = {
    "Tower Bridge":       {"lat": 51.5055, "lng": -0.0754},
    "London Bridge":      {"lat": 51.5079, "lng": -0.0877},
    "Blackfriars Bridge": {"lat": 51.5103, "lng": -0.1037},
    "Waterloo Bridge":    {"lat": 51.5085, "lng": -0.1163},
    "Westminster Bridge": {"lat": 51.5008, "lng": -0.1217},
}
# A disruption point within this many metres of a bridge centre counts as "on the bridge".
BRIDGE_MATCH_M = 400.0


# ----------------------------------------------------------------------------- transport
def _get(path: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """GET ``path`` on the orchestrator. Returns parsed JSON, or ``{"error": ...}``.

    Never raises: connection errors, timeouts and non-2xx (incl. 404 for endpoints not
    yet implemented) all degrade to an error dict the agent can narrate gracefully.
    """
    url = f"{ORCHESTRATOR_URL}{path}"
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT_S) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as e:
        return {"error": f"orchestrator returned {e.response.status_code} for {path}"}
    except Exception as e:  # noqa: BLE001 — graceful degradation is the whole point
        return {"error": f"orchestrator unreachable ({type(e).__name__}): {path}"}


def _haversine_m(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    """Great-circle distance in metres between two WGS84 points."""
    r = 6_371_000.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = math.radians(b_lat - a_lat)
    dl = math.radians(b_lng - a_lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


# ----------------------------------------------------------------------------- tools
def get_guidance(driver_id: str) -> dict[str, Any]:
    """GET /driver/{id}/guidance — current route status, ETA and green-wave advice."""
    data = _get(f"/driver/{driver_id}/guidance")
    if "error" in data:
        return data
    advice = data.get("signal_advice") or {}
    contrib = data.get("contribution") or {}
    return {
        "driver_id": data.get("driver_id", driver_id),
        "status": data.get("status"),
        "eta": data.get("eta"),
        "signal_message": advice.get("message") if isinstance(advice, dict) else None,
        "target_speed_mps": advice.get("target_speed_mps") if isinstance(advice, dict) else None,
        "pings": contrib.get("pings"),
        "couriers_helped": contrib.get("couriers_helped"),
    }


def get_signal_advice(driver_id: str, lat: float, lng: float, heading: float) -> dict[str, Any]:
    """GET /signals/advice — the speed that arrives at the next junction on green."""
    data = _get(
        "/signals/advice",
        params={"driver_id": driver_id, "lat": lat, "lng": lng, "heading": heading},
    )
    if "error" in data:
        return data
    junction = data.get("junction") or {}
    return {
        "message": data.get("message"),
        "target_speed_mps": data.get("target_speed_mps"),
        "seconds_to_green": data.get("seconds_to_green"),
        "junction": junction.get("name") if isinstance(junction, dict) else None,
        "confidence": data.get("confidence"),
    }


def get_congestion() -> dict[str, Any]:
    """GET /congestion — summarise the worst congestion hotspots in the field."""
    data = _get("/congestion")
    if "error" in data:
        return data
    cells = data.get("cells") or []
    ranked = sorted(
        (c for c in cells if isinstance(c, dict)),
        key=lambda c: c.get("congestion", 0.0),
        reverse=True,
    )
    hotspots = [
        {
            "cell": c.get("cell"),
            "lat": c.get("lat"),
            "lng": c.get("lng"),
            "congestion": round(float(c.get("congestion", 0.0)), 2),
            "speed_mps": c.get("speed_mps"),
        }
        for c in ranked[:3]
    ]
    return {
        "n_cells": len(cells),
        "worst_congestion": hotspots[0]["congestion"] if hotspots else 0.0,
        "hotspots": hotspots,
    }


def bridge_status(bridge: str = "Tower Bridge") -> dict[str, Any]:
    """Derive bridge open/closed from GET /state disruptions.

    Matches each ``road_closure`` / ``traffic`` disruption's geometry points against the
    known bridge centres (``BRIDGES``). Reports whether the named bridge (default Tower
    Bridge) is open and lists any bridges currently closed.
    """
    state = _get("/state")
    if "error" in state:
        return state
    disruptions = state.get("disruptions") or []

    closed: set[str] = set()
    for d in disruptions:
        if not isinstance(d, dict):
            continue
        if d.get("kind") not in ("road_closure", "traffic"):
            continue
        for pt in d.get("geometry") or []:
            if not isinstance(pt, dict):
                continue
            try:
                plat, plng = float(pt["lat"]), float(pt["lng"])
            except (KeyError, TypeError, ValueError):
                continue
            for name, c in BRIDGES.items():
                if _haversine_m(plat, plng, c["lat"], c["lng"]) <= BRIDGE_MATCH_M:
                    closed.add(name)

    target = _canonical_bridge(bridge)
    return {
        "bridge": target,
        "open": target not in closed,
        "closed_bridges": sorted(closed),
        "any_bridge_closed": bool(closed),
    }


def next_pickup(driver_id: str) -> dict[str, Any]:
    """Where the driver is headed next — derived from /driver/{id}/guidance."""
    g = get_guidance(driver_id)
    if "error" in g:
        return g
    return {
        "driver_id": g.get("driver_id", driver_id),
        "status": g.get("status"),
        "eta": g.get("eta"),
    }


def reroute_reason(driver_id: str) -> dict[str, Any]:
    """Why the driver was rerouted — from guidance plus active /state disruptions.

    (The orchestrator narrates reroutes as ``agent_log`` events on the WS, which mirror
    the disruptions that caused them; we read the disruptions from /state here.)
    """
    g = get_guidance(driver_id)
    state = _get("/state")
    disruptions = [] if "error" in state else (state.get("disruptions") or [])
    kinds = [d.get("kind") for d in disruptions if isinstance(d, dict) and d.get("kind")]

    if kinds:
        reason = f"rerouted around {len(kinds)} active disruption(s): {', '.join(kinds)}"
    else:
        reason = "no active disruptions — you're on the optimal route"

    out: dict[str, Any] = {"driver_id": driver_id, "reason": reason, "disruptions": kinds}
    if isinstance(g, dict) and "error" not in g and g.get("status"):
        out["status"] = g["status"]
    return out


# ----------------------------------------------------------------------------- helpers
def _canonical_bridge(name: str) -> str:
    """Map a loosely-typed bridge name onto a known bridge, defaulting to Tower Bridge."""
    low = (name or "").lower()
    for known in BRIDGES:
        if known.lower() in low or low in known.lower():
            return known
    if "bridge" in low:
        # Pull the leading word(s) before 'bridge' against the gazetteer.
        for known in BRIDGES:
            if known.split()[0].lower() in low:
                return known
    return "Tower Bridge"


# Registry the agent dispatches against (name -> callable), kept in one place.
TOOLS = {
    "get_guidance": get_guidance,
    "get_signal_advice": get_signal_advice,
    "get_congestion": get_congestion,
    "bridge_status": bridge_status,
    "next_pickup": next_pickup,
    "reroute_reason": reroute_reason,
}
