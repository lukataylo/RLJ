"""Google OR-Tools PDPTW adapter — a strong third-party baseline for the backtest.

Models the same problem our solver does (pickup-before-delivery, capacity, cold-chain
vehicle eligibility, soft clinical time windows, droppable jobs) using OR-Tools routing,
on the SAME travel-time matrix (traveltime.build_travel_time_matrix, disruption-aware) so
comparisons are fair. Import-guarded: returns None if ortools is absent.

It exists so our research claim is honest: we don't beat OR-Tools by being a worse static
solver — we show that *anticipating scheduled closures* helps regardless of the optimiser,
and that our anticipatory portfolio is competitive with / beats OR-Tools given the same info.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional

from models import LatLng, Location, Objective, OptimizeRequest, Plan, Route, Stop
from traveltime import build_travel_time_matrix, travel_time_matrix

SERVICE_S = 120
PRIORITY_LATE_PENALTY = {"stat": 2000, "urgent": 200, "routine": 20}  # per-second soft cost
DROP_PENALTY = 10_000_000
HORIZON_S = 24 * 3600


def solve(req: OptimizeRequest, *, time_limit_s: int = 2) -> Optional[Plan]:
    try:
        from ortools.constraint_solver import pywrapcp, routing_enums_pb2
    except Exception:  # noqa: BLE001
        return None

    now = req.now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    couriers = [c for c in req.couriers if c.status != "offline"]
    jobs = list(req.jobs)
    C, J = len(couriers), len(jobs)
    if C == 0 or J == 0:
        return _empty(jobs, now)

    # node layout: [0..C-1]=vehicle starts, [C]=dummy end, pickups/drops after
    END = C
    pick = [C + 1 + 2 * j for j in range(J)]
    drop = [C + 2 + 2 * j for j in range(J)]
    N = C + 1 + 2 * J

    coords = [(c.location.lat, c.location.lng) for c in couriers]
    coords.append((couriers[0].location.lat, couriers[0].location.lng))  # dummy end
    for j in jobs:
        coords.append((j.origin.lat, j.origin.lng))
        coords.append((j.destination.lat, j.destination.lng))
    T = travel_time_matrix([c[0] for c in coords], [c[1] for c in coords],
                                 disruptions=req.disruptions)
    # dummy end is free to reach/leave (open routes)
    T[END, :] = 0.0
    T[:, END] = 0.0

    def _s(dt):
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, int((dt - now).total_seconds()))

    mgr = pywrapcp.RoutingIndexManager(N, C, list(range(C)), [END] * C)
    routing = pywrapcp.RoutingModel(mgr)

    def transit(from_idx, to_idx):
        a, b = mgr.IndexToNode(from_idx), mgr.IndexToNode(to_idx)
        return int(T[a, b]) + (SERVICE_S if a >= C + 1 else 0)

    transit_cb = routing.RegisterTransitCallback(transit)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_cb)

    # time dimension
    routing.AddDimension(transit_cb, HORIZON_S, HORIZON_S, True, "Time")
    time_dim = routing.GetDimensionOrDie("Time")

    # capacity dimension
    def demand(idx):
        n = mgr.IndexToNode(idx)
        for j in range(J):
            if n == pick[j]:
                return int(jobs[j].capacity_units)
            if n == drop[j]:
                return -int(jobs[j].capacity_units)
        return 0

    demand_cb = routing.RegisterUnaryTransitCallback(demand)
    routing.AddDimensionWithVehicleCapacity(
        demand_cb, 0, [int(c.capacity) for c in couriers], True, "Cap")

    cold_vehicles = [v for v, c in enumerate(couriers) if bool(getattr(c, "cold_capable", True))]

    for j in range(J):
        pidx, didx = mgr.NodeToIndex(pick[j]), mgr.NodeToIndex(drop[j])
        routing.AddPickupAndDelivery(pidx, didx)
        routing.solver().Add(routing.VehicleVar(pidx) == routing.VehicleVar(didx))
        routing.solver().Add(time_dim.CumulVar(pidx) <= time_dim.CumulVar(didx))
        # pickup ready time
        ready = _s(jobs[j].time_window.ready_at if jobs[j].time_window else None) or 0
        time_dim.CumulVar(pidx).SetMin(ready)
        # soft clinical due date on the delivery
        due = _s(jobs[j].time_window.due_by if jobs[j].time_window else None)
        if due is not None:
            time_dim.SetCumulVarSoftUpperBound(
                didx, due, PRIORITY_LATE_PENALTY.get(jobs[j].priority, 20))
        # cold-chain vehicle eligibility: restrict VehicleVar domain to cold vehicles
        # (plus -1 = "not served", so the job can still be dropped). When NO courier is
        # cold-capable the domain is just [-1], forcing the cold job to be left unassigned
        # rather than put in a fridge-less van. Version-stable.
        if jobs[j].cold_chain and len(cold_vehicles) < C:
            allowed = [-1] + cold_vehicles
            routing.VehicleVar(pidx).SetValues(allowed)
            routing.VehicleVar(didx).SetValues(allowed)
        # droppable as a pair
        routing.AddDisjunction([pidx, didx], DROP_PENALTY, 2)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromSeconds(time_limit_s)

    sol = routing.SolveWithParameters(params)
    if sol is None:
        return None
    return _extract(req, couriers, jobs, mgr, routing, time_dim, sol, pick, drop, now)


def _extract(req, couriers, jobs, mgr, routing, time_dim, sol, pick, drop, now) -> Plan:
    node_job = {}
    for j in range(len(jobs)):
        node_job[pick[j]] = (j, "pickup")
        node_job[drop[j]] = (j, "dropoff")
    routes, served, windows_met, windows_total, total_time = [], set(), 0, 0, 0.0
    windows_total = sum(1 for j in jobs if j.time_window and j.time_window.due_by)

    for v in range(len(couriers)):
        idx = routing.Start(v)
        stops, seq = [], 0
        last_t = 0.0
        while not routing.IsEnd(idx):
            node = mgr.IndexToNode(idx)
            if node in node_job:
                j, kind = node_job[node]
                job = jobs[j]
                tsec = sol.Value(time_dim.CumulVar(idx))
                last_t = max(last_t, tsec)
                loc = job.origin if kind == "pickup" else job.destination
                met = None
                if kind == "dropoff":
                    served.add(j)
                    due = job.time_window.due_by if job.time_window else None
                    if due:
                        d = due if due.tzinfo else due.replace(tzinfo=timezone.utc)
                        met = tsec <= (d - now).total_seconds()
                        windows_met += int(met)
                stops.append(Stop(job_id=job.id, kind=kind,
                                  location=Location(lat=loc.lat, lng=loc.lng, name=loc.name,
                                                    facility_id=loc.facility_id),
                                  sequence=seq, eta=now + timedelta(seconds=int(tsec)),
                                  window_met=met))
                seq += 1
            idx = sol.Value(routing.NextVar(idx))
        if stops:
            total_time += last_t
            routes.append(Route(courier_id=couriers[v].id, stops=stops,
                                polyline=[LatLng(lat=s.location.lat, lng=s.location.lng) for s in stops],
                                total_time_s=last_t, total_distance_m=0.0, feasible=True))
    unassigned = [jobs[j].id for j in range(len(jobs)) if j not in served]
    return Plan(routes=routes, unassigned=unassigned,
                objective=Objective(total_time_s=total_time, windows_met=windows_met,
                                    windows_total=windows_total, solver="ortools", solve_ms=0.0),
                generated_at=now)


def _empty(jobs, now) -> Plan:
    return Plan(routes=[], unassigned=[j.id for j in jobs],
                objective=Objective(windows_total=sum(1 for j in jobs if j.time_window and j.time_window.due_by),
                                    solver="ortools"), generated_at=now)
