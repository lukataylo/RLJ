"""Built-in fallback router. Deliberately simple: nearest-courier assignment with
priority ordering and straight-line ETAs. This is the safety net that keeps the whole
system demoable before the real GPU solver (routing/) is ready.

The routing stream replaces this by implementing POST /optimize; the orchestrator
prefers that service whenever ROUTING_URL is reachable.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from math import radians, sin, cos, asin, sqrt

from models import OptimizeRequest, Plan, Route, Stop, LatLng, Objective

AVG_SPEED_MPS = 6.5  # ~23 km/h urban average incl. stops; tune for demo realism
SERVICE_S = 120      # dwell time per stop
PRIORITY_RANK = {"stat": 0, "urgent": 1, "routine": 2}


def haversine_m(a, b) -> float:
    lat1, lng1, lat2, lng2 = map(radians, [a.lat, a.lng, b.lat, b.lng])
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return 2 * 6371000 * asin(sqrt(h))


def greedy_plan(req: OptimizeRequest) -> Plan:
    now = req.now or datetime.now(timezone.utc)
    couriers = [c for c in req.couriers if c.status != "offline"]
    jobs = sorted(req.jobs, key=lambda j: (PRIORITY_RANK.get(j.priority, 3),
                                           (j.time_window.due_by or now)))
    # mutable courier cursors: (current_location, current_time, capacity_left, stops)
    state = {c.id: [c.location, now, c.capacity, []] for c in couriers}
    routes_idx = {c.id: Route(courier_id=c.id) for c in couriers}
    unassigned: list[str] = []
    windows_total = sum(1 for j in jobs if j.time_window.due_by)
    windows_met = 0

    for job in jobs:
        if not couriers:
            unassigned.append(job.id)
            continue
        # pick courier whose current position is closest to this job's origin and has room
        best = min(
            (c for c in couriers if state[c.id][2] >= job.capacity_units),
            key=lambda c: haversine_m(state[c.id][0], job.origin),
            default=None,
        )
        if best is None:
            unassigned.append(job.id)
            continue

        loc, t, cap, stops = state[best.id]
        # leg to pickup
        t = t + timedelta(seconds=haversine_m(loc, job.origin) / AVG_SPEED_MPS + SERVICE_S)
        stops.append(Stop(job_id=job.id, kind="pickup", location=job.origin,
                          sequence=len(stops), eta=t))
        # leg to dropoff
        t = t + timedelta(seconds=haversine_m(job.origin, job.destination) / AVG_SPEED_MPS + SERVICE_S)
        met = bool(job.time_window.due_by and t <= job.time_window.due_by)
        windows_met += int(met)
        stops.append(Stop(job_id=job.id, kind="dropoff", location=job.destination,
                          sequence=len(stops), eta=t, window_met=met))
        state[best.id] = [job.destination, t, cap - job.capacity_units, stops]

    routes = []
    total_time = 0.0
    for cid, (loc, t, cap, stops) in state.items():
        if not stops:
            continue
        r = routes_idx[cid]
        r.stops = stops
        r.polyline = [LatLng(lat=s.location.lat, lng=s.location.lng) for s in stops]
        r.total_time_s = (stops[-1].eta - now).total_seconds() if stops[-1].eta else 0
        r.total_distance_m = sum(
            haversine_m(stops[i].location, stops[i + 1].location) for i in range(len(stops) - 1)
        )
        total_time += r.total_time_s
        routes.append(r)

    return Plan(
        routes=routes,
        unassigned=unassigned,
        objective=Objective(total_time_s=total_time, windows_met=windows_met,
                            windows_total=windows_total, solver="greedy-fallback"),
        generated_at=now,
    )
