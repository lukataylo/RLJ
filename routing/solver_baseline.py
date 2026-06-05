"""Fallback solvers for the routing service.

The ladder (best -> safest), mirroring ARCHITECTURE.md:

    custom GPU ACO (solver_aco)  ->  NVIDIA cuOpt  ->  OR-Tools  ->  greedy

This module owns the lower three rungs. ``greedy_plan`` is a self-contained port of
``orchestrator/greedy.py`` (re-implemented here on purpose — no cross-folder import — so
the routing service has a guaranteed, dependency-free safety net). ``try_ortools`` and
``try_cuopt`` are import-guarded and return ``None`` when their dependency is absent, so
everything still runs on this Mac with numpy only.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import asin, cos, radians, sin, sqrt
from typing import Optional

from models import (
    LatLng,
    Location,
    Objective,
    OptimizeRequest,
    Plan,
    Route,
    Stop,
)

AVG_SPEED_MPS = 6.5   # keep identical to orchestrator/greedy.py for fair comparison
SERVICE_S = 120
PRIORITY_RANK = {"stat": 0, "urgent": 1, "routine": 2}


def _haversine_m(a, b) -> float:
    lat1, lng1, lat2, lng2 = map(radians, [a.lat, a.lng, b.lat, b.lng])
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return 2 * 6_371_000 * asin(sqrt(h))


# =====================================================================================
# Rung 4 — greedy (always available). Port of orchestrator/greedy.py.
# =====================================================================================
def greedy_plan(req: OptimizeRequest, *, solver_name: str = "greedy-fallback") -> Plan:
    now = req.now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    couriers = [c for c in req.couriers if c.status != "offline"]

    def _due(j):
        return (j.time_window.due_by if j.time_window else None) or now

    jobs = sorted(req.jobs, key=lambda j: (PRIORITY_RANK.get(j.priority, 3), _due(j)))

    # mutable courier cursors: [current_location, current_time, capacity_left, stops]
    state = {c.id: [c.location, now, c.capacity, []] for c in couriers}
    routes_idx = {c.id: Route(courier_id=c.id) for c in couriers}
    unassigned: list[str] = []
    windows_total = sum(1 for j in jobs if j.time_window and j.time_window.due_by)
    windows_met = 0

    for job in jobs:
        candidates = [c for c in couriers if state[c.id][2] >= job.capacity_units]
        if not candidates:
            unassigned.append(job.id)
            continue
        best = min(candidates, key=lambda c: _haversine_m(state[c.id][0], job.origin))

        loc, t, cap, stops = state[best.id]
        # leg to pickup
        t = t + timedelta(seconds=_haversine_m(loc, job.origin) / AVG_SPEED_MPS + SERVICE_S)
        stops.append(Stop(job_id=job.id, kind="pickup", location=job.origin,
                          sequence=len(stops), eta=t))
        # leg to dropoff
        t = t + timedelta(
            seconds=_haversine_m(job.origin, job.destination) / AVG_SPEED_MPS + SERVICE_S
        )
        due = job.time_window.due_by if job.time_window else None
        met = bool(due and t <= due)
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
            _haversine_m(stops[i].location, stops[i + 1].location)
            for i in range(len(stops) - 1)
        )
        total_time += r.total_time_s
        routes.append(r)

    return Plan(
        routes=routes,
        unassigned=unassigned,
        objective=Objective(total_time_s=total_time, windows_met=windows_met,
                            windows_total=windows_total, solver=solver_name),
        generated_at=now,
    )


# =====================================================================================
# Rung 3 — OR-Tools (optional). Returns None if ortools is not importable.
# =====================================================================================
def try_ortools(req: OptimizeRequest) -> Optional[Plan]:
    """Solve with Google OR-Tools routing (PDPTW) if the package is installed.

    Import-guarded so the service runs on a numpy-only box. This is a deliberately
    light wiring point: full pickup-delivery + time-window constraints would be added
    here for production. On this dev machine ortools is absent, so it returns ``None``
    and the caller drops to greedy.
    """
    try:
        from ortools.constraint_solver import pywrapcp  # type: ignore  # noqa: F401
    except Exception:  # noqa: BLE001
        return None
    # Wiring point: build the index manager + routing model, add capacity / pickup-
    # delivery / time-window dimensions, then translate assignment -> Plan. Not fleshed
    # out for the hackathon dev box; ACO is the headline path.
    return None


# =====================================================================================
# Rung 2 — NVIDIA cuOpt (optional, GPU). Returns None if cuopt is not importable.
# =====================================================================================
def try_cuopt(req: OptimizeRequest) -> Optional[Plan]:
    """Solve with NVIDIA cuOpt on the GB10 if available.

    cuOpt is the vendor fallback below our custom ACO: a managed GPU PDPTW solver. On
    the DGX Spark this would build a cuOpt DataModel (cost/time matrices from
    traveltime, vehicle capacities, task time windows + pickup-delivery pairs) and call
    the solver. Import-guarded; absent on this Mac, so returns ``None``.
    """
    try:
        import cuopt  # type: ignore  # noqa: F401
    except Exception:  # noqa: BLE001
        return None
    return None
