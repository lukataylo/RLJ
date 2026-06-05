"""A realistic-enough London river-barrier network for the backtest.

Straight-line travel can't represent the thing that makes anticipation valuable: a closed
bridge forces a *detour*. So we model the Thames as a hard barrier crossed only at named
road bridges. Cross-river trips route via the cheapest OPEN bridge; closing Tower Bridge
pushes traffic to London Bridge (a real, measurable detour). Same-side trips are direct.

This is a deliberate, documented simplification (bridge-set model, not a full OSM graph —
see RESEARCH.md limitations). It is sufficient to study the *information* question:
does knowing a bridge will be shut let the planner assign/sequence to avoid the detour?

The function `graph_travel_matrix` is signature-compatible with
`traveltime.build_travel_time_matrix`, so it can be monkeypatched into the solvers, and
`travel_time` is reused by the ground-truth evaluator with time-dependent closures.
"""
from __future__ import annotations
from math import radians, sin, cos, asin, sqrt
import numpy as np

EARTH_M = 6_371_000.0
SPEED_MPS = 6.5
CIRCUITY = 1.4

# Road bridges across the Thames in central/east London (name, lat, lng).
BRIDGES = [
    ("vauxhall", 51.4861, -0.1253), ("lambeth", 51.4943, -0.1219),
    ("westminster", 51.5010, -0.1246), ("waterloo", 51.5066, -0.1145),
    ("blackfriars", 51.5110, -0.1037), ("southwark", 51.5074, -0.0959),
    ("london", 51.5079, -0.0877), ("tower", 51.5055, -0.0754),
    ("rotherhithe", 51.5012, -0.0520),  # tunnel, counts as a crossing
]
# Approx Thames centreline through London, west -> east (lat, lng).
THAMES = [(51.4860, -0.1320), (51.4880, -0.1240), (51.5010, -0.1230), (51.5070, -0.1170),
          (51.5085, -0.1020), (51.5045, -0.0980), (51.5050, -0.0850), (51.5070, -0.0760),
          (51.5045, -0.0600), (51.5020, -0.0400), (51.5050, -0.0150)]


def _hav(a, b) -> float:
    lat1, lng1, lat2, lng2 = map(radians, [a[0], a[1], b[0], b[1]])
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return 2 * EARTH_M * asin(sqrt(h))


def _pt_seg_dist(q, p1, p2):
    """Approx planar distance (deg-space) from q to segment p1-p2, plus cross-sign."""
    ax, ay = p1[1], p1[0]
    bx, by = p2[1], p2[0]
    qx, qy = q[1], q[0]
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy or 1e-12
    t = max(0.0, min(1.0, ((qx - ax) * dx + (qy - ay) * dy) / seg2))
    cx, cy = ax + t * dx, ay + t * dy
    dist = sqrt((qx - cx) ** 2 + (qy - cy) ** 2)
    cross = dx * (qy - ay) - dy * (qx - ax)  # >0 => left of west->east travel => north
    return dist, cross


def side(pt) -> str:
    """'N' or 'S' of the Thames. Uses the nearest centreline segment's orientation."""
    best_d, best_cross = 1e9, 0.0
    for i in range(len(THAMES) - 1):
        d, cross = _pt_seg_dist(pt, THAMES[i], THAMES[i + 1])
        if d < best_d:
            best_d, best_cross = d, cross
    return "N" if best_cross >= 0 else "S"


def _seg_near(pts, a, b, radius_m=350.0, samples=6) -> bool:
    for s in range(samples + 1):
        f = s / samples
        p = (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
        for c in pts:
            if _hav(p, c) < radius_m:
                return True
    return False


def travel_time(a, b, closed_bridges=frozenset(), traffic_zones=(), speed=SPEED_MPS) -> float:
    """Seconds from a to b. Cross-river trips route via the cheapest open bridge; traffic
    zones multiply any leg that passes near them."""
    if side(a) == side(b):
        legs = [(a, b)]
        dist = _hav(a, b) * CIRCUITY
    else:
        best, legs = float("inf"), None
        for nm, blat, blng in BRIDGES:
            if nm in closed_bridges:
                continue
            d = _hav(a, (blat, blng)) + _hav((blat, blng), b)
            if d < best:
                best, legs = d, [(a, (blat, blng)), ((blat, blng), b)]
        if legs is None:
            return 6 * 3600.0  # no open crossing — effectively unreachable in window
        dist = best * CIRCUITY
    t = dist / speed
    for z in traffic_zones:
        if any(_seg_near(z["pts"], p, q) for (p, q) in legs):
            t *= z["factor"]
    return t


BRIDGE_POS = {nm: (la, ln) for nm, la, ln in BRIDGES}


def chosen_bridge(a, b, closed=frozenset()):
    """Which bridge a planner would pick for a->b given its belief about closures
    (None if same side)."""
    if side(a) == side(b):
        return None
    best, name = float("inf"), None
    for nm, bl, bn in BRIDGES:
        if nm in closed:
            continue
        d = _hav(a, (bl, bn)) + _hav((bl, bn), b)
        if d < best:
            best, name = d, nm
    return name


def nearest_open_bridge_pos(pos, closed):
    cand = [(nm, bl, bn) for nm, bl, bn in BRIDGES if nm not in closed]
    if not cand:
        return pos
    nm, bl, bn = min(cand, key=lambda x: _hav(pos, (x[1], x[2])))
    return (bl, bn)


def closed_bridges_from(disruptions) -> frozenset:
    closed = set()
    for d in disruptions or []:
        kind = d.get("kind") if isinstance(d, dict) else getattr(d, "kind", None)
        if kind != "road_closure":
            continue
        geom = d.get("geometry") if isinstance(d, dict) else getattr(d, "geometry", None)
        for g in (geom or []):
            gl = (g["lat"], g["lng"]) if isinstance(g, dict) else (g.lat, g.lng)
            for nm, blat, blng in BRIDGES:
                if _hav((blat, blng), gl) < 500:
                    closed.add(nm)
    return frozenset(closed)


def traffic_zones_from(disruptions):
    """Non-bridge closures become traffic zones (road_closure far from any bridge => heavy)."""
    zones = []
    closed = closed_bridges_from(disruptions)
    for d in disruptions or []:
        kind = d.get("kind") if isinstance(d, dict) else getattr(d, "kind", None)
        geom = d.get("geometry") if isinstance(d, dict) else getattr(d, "geometry", None)
        pts = [((g["lat"], g["lng"]) if isinstance(g, dict) else (g.lat, g.lng)) for g in (geom or [])]
        if not pts:
            continue
        on_bridge = any(_hav((bl, bn), p) < 500 for _n, bl, bn in BRIDGES for p in pts)
        if kind == "road_closure" and on_bridge:
            continue  # already handled as a bridge closure
        zones.append({"pts": pts, "factor": 6.0 if kind == "road_closure" else 2.5})
    return zones


def graph_travel_matrix(lats, lngs, *, speed_mps=SPEED_MPS, disruptions=None):
    """Signature-compatible drop-in for traveltime.build_travel_time_matrix."""
    closed = closed_bridges_from(disruptions)
    zones = traffic_zones_from(disruptions)
    n = len(lats)
    pts = list(zip(lats, lngs))
    M = np.zeros((n, n), dtype=np.float64)
    for i in range(n):
        for j in range(n):
            if i != j:
                M[i, j] = travel_time(pts[i], pts[j], closed, zones, speed_mps)
    return M
