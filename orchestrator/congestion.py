"""Crowdsourced congestion estimator — the core of the data flywheel.

Driver GPS probes -> a grid congestion field -> derived traffic/closure disruptions that
the dispatcher routes medical couriers around. More probes -> denser, more confident field
-> better routing for everyone. Pure functions on plain dicts (no pydantic) so both the
orchestrator and the backtest can use it without import coupling.

A cell is only allowed to raise a disruption once it has >= MIN_PROBES observations — this
is the network effect made explicit: sparse participation cannot move the model, dense
participation can. That gating is exactly what the flywheel backtest measures.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone

GRID = 0.004          # ~400 m cells
FREEFLOW_MPS = 8.0    # ~29 km/h urban free-flow reference
LONDON_BBOX = (51.28, 51.69, -0.51, 0.33)  # lat_min, lat_max, lng_min, lng_max

MIN_PROBES = 6        # confidence gate: cells below this never raise a disruption
SEVERE = 0.80         # congestion >= this near a crossing => road_closure (effectively blocked)
BUSY = 0.50           # congestion >= this => traffic zone


def _in_bbox(lat, lng):
    a, b, c, d = LONDON_BBOX
    return a <= lat <= b and c <= lng <= d


def validate_pings(pings):
    """Split pings into (accepted, rejected): in-London, sane speed, required fields."""
    accepted, rejected = [], []
    for p in pings:
        try:
            lat, lng = float(p["lat"]), float(p["lng"])
            spd = float(p.get("speed_mps", 0.0))
            ok = _in_bbox(lat, lng) and 0.0 <= spd <= 40.0 and p.get("driver_id")
        except (KeyError, TypeError, ValueError):
            ok = False
        (accepted if ok else rejected).append(p)
    return accepted, rejected


def cell_id(lat, lng):
    return f"{round(lat / GRID) * GRID:.3f}_{round(lng / GRID) * GRID:.3f}"


def estimate_field(pings, now=None):
    """Aggregate validated pings into a CongestionField dict (contracts $defs/CongestionField)."""
    now = now or datetime.now(timezone.utc)
    accepted, _ = validate_pings(pings)
    buckets = defaultdict(list)
    for p in accepted:
        buckets[cell_id(p["lat"], p["lng"])].append(p)
    cells = []
    for cid, ps in buckets.items():
        speeds = [float(p.get("speed_mps", 0.0)) for p in ps]
        mean_speed = sum(speeds) / len(speeds)
        congestion = max(0.0, min(1.0, 1.0 - mean_speed / FREEFLOW_MPS))
        clat = sum(float(p["lat"]) for p in ps) / len(ps)
        clng = sum(float(p["lng"]) for p in ps) / len(ps)
        cells.append({"cell": cid, "lat": clat, "lng": clng, "congestion": round(congestion, 3),
                      "speed_mps": round(mean_speed, 2), "n_probes": len(ps),
                      "updated_at": now.isoformat()})
    return {"cells": cells, "generated_at": now.isoformat()}


def field_to_disruptions(field, min_probes=MIN_PROBES):
    """Project a confident congestion field into DisruptionEvent dicts. Severe, well-observed
    cells become road_closure (impassable); busy cells become traffic. Confidence-gated."""
    out = []
    for c in field.get("cells", []):
        if c["n_probes"] < min_probes:
            continue
        if c["congestion"] >= SEVERE:
            kind = "road_closure"
        elif c["congestion"] >= BUSY:
            kind = "traffic"
        else:
            continue
        out.append({"id": f"cong-{c['cell']}", "kind": kind,
                    "geometry": [{"lat": c["lat"], "lng": c["lng"]}], "source": "manual"})
    return out
