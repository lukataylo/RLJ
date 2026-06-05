"""Insertion construction + local-search refinement for D-PDPTW.

Solution space (shared with greedy, so comparisons are fair and ETAs are simple):
each courier serves an ordered list of jobs, each job fully pickup→dropoff before the
next (pairwise-sequential). This matches how time-critical medical couriers actually run
(you don't leave a STAT sample sitting in the van) and makes ETA simulation exact.

Pipeline:
  * ``construct``  — priority-ordered cheapest-feasible insertion (STAT first), honouring
    capacity, cold-chain capability, and clinical windows.
  * ``refine``     — relocate + swap local search that strictly improves a plan by the
    clinical objective (maximise STAT-met, then windows-met, then fewer unassigned, then
    less weighted lateness). Used to polish ANY candidate (greedy, ACO, or our construct).
  * ``pick_best``  — lexicographic selection over candidate plans.

This is the workhorse; ``solver_aco`` is the GPU-parallel explorer whose output is also
fed through ``refine``. Everything runs on numpy; deterministic.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np

from models import LatLng, Location, Objective, OptimizeRequest, Plan, Route, Stop
from traveltime import build_travel_time_matrix

SERVICE_S = 120.0
PRIORITY_WEIGHT = {"stat": 100.0, "urgent": 10.0, "routine": 1.0}
PRIORITY_RANK = {"stat": 0, "urgent": 1, "routine": 2}


# --------------------------------------------------------------------------- problem prep
class _P:
    def __init__(self, req: OptimizeRequest):
        now = req.now or datetime.now(timezone.utc)
        self.now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now
        self.couriers = [c for c in req.couriers if c.status != "offline"]
        self.jobs = list(req.jobs)
        self.C, self.J = len(self.couriers), len(self.jobs)

        coords = [(c.location.lat, c.location.lng) for c in self.couriers]
        coords += [(j.origin.lat, j.origin.lng) for j in self.jobs]
        coords += [(j.destination.lat, j.destination.lng) for j in self.jobs]
        lats = [c[0] for c in coords]
        lngs = [c[1] for c in coords]
        self.T = build_travel_time_matrix(lats, lngs, disruptions=req.disruptions)

        self.depot = {c.id: i for i, c in enumerate(self.couriers)}
        self.pick = {self.jobs[j].id: self.C + j for j in range(self.J)}
        self.drop = {self.jobs[j].id: self.C + self.J + j for j in range(self.J)}
        self.job_by_id = {j.id: j for j in self.jobs}
        self.cap = {c.id: float(c.capacity) for c in self.couriers}
        self.cold_ok = {c.id: bool(getattr(c, "cold_capable", True)) for c in self.couriers}

    def ready_s(self, job) -> float:
        tw = job.time_window
        if not tw or not tw.ready_at:
            return 0.0
        r = tw.ready_at
        r = r.replace(tzinfo=timezone.utc) if r.tzinfo is None else r
        return max(0.0, (r - self.now).total_seconds())

    def due_s(self, job) -> Optional[float]:
        tw = job.time_window
        if not tw or not tw.due_by:
            return None
        d = tw.due_by
        d = d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d
        return (d - self.now).total_seconds()


# --------------------------------------------------------------------------- simulation
def _sim_route(P: _P, cid: str, seq: list[str]):
    """Simulate one courier's pairwise route. Returns (stops, met, stat_met, late_w, end)."""
    node = P.depot[cid]
    t = 0.0
    stops, met, stat_met, late_w = [], 0, 0, 0.0
    courier_cold = P.cold_ok[cid]
    for jid in seq:
        job = P.job_by_id[jid]
        if job.cold_chain and not courier_cold:
            late_w += 1e6  # infeasible cold assignment — heavily penalised
        if job.capacity_units > P.cap[cid]:
            late_w += 1e6
        # pickup
        t += P.T[node, P.pick[jid]]
        t = max(t, P.ready_s(job))
        node = P.pick[jid]
        stops.append(("pickup", jid, t))
        t += SERVICE_S
        # dropoff
        t += P.T[node, P.drop[jid]]
        node = P.drop[jid]
        arrival = t
        due = P.due_s(job)
        win = None
        if due is not None:
            win = arrival <= due
            met += int(win)
            if job.priority == "stat":
                stat_met += int(win)
            if not win:
                late_w += (arrival - due) * PRIORITY_WEIGHT.get(job.priority, 1.0)
        stops.append(("dropoff", jid, arrival, win))
        t += SERVICE_S
    return stops, met, stat_met, late_w, t


def _score(P: _P, assign: dict[str, list[str]]):
    """Global lexicographic score for an assignment. Higher is better via the key below."""
    served = {jid for seq in assign.values() for jid in seq}
    unassigned = [j.id for j in P.jobs if j.id not in served]
    met = stat_met = 0
    late_w = total = 0.0
    stat_total = sum(1 for j in P.jobs if j.priority == "stat" and P.due_s(j) is not None)
    for cid, seq in assign.items():
        if not seq:
            continue
        _stops, m, sm, lw, end = _sim_route(P, cid, seq)
        met += m
        stat_met += sm
        late_w += lw
        total += end
    # key: maximise stat_met, then met, then minimise unassigned, lateness, total time
    key = (stat_met, met, -len(unassigned), -late_w, -total)
    return key, unassigned, stat_total


def _feasible_cold(P: _P, cid: str, job) -> bool:
    return (not job.cold_chain or P.cold_ok[cid]) and job.capacity_units <= P.cap[cid]


# --------------------------------------------------------------------------- construction
def construct(req: OptimizeRequest) -> Plan:
    P = _P(req)
    if P.C == 0 or P.J == 0:
        return _to_plan(P, {c.id: [] for c in P.couriers})
    assign: dict[str, list[str]] = {c.id: [] for c in P.couriers}
    order = sorted(P.jobs, key=lambda j: (PRIORITY_RANK.get(j.priority, 3),
                                          P.due_s(j) if P.due_s(j) is not None else 1e9))
    for job in order:
        best = None  # (key, cid, pos)
        for cid in assign:
            if not _feasible_cold(P, cid, job):
                continue
            seq = assign[cid]
            for pos in range(len(seq) + 1):
                trial = {**assign, cid: seq[:pos] + [job.id] + seq[pos:]}
                key, _u, _s = _score(P, trial)
                if best is None or key > best[0]:
                    best = (key, cid, pos)
        if best is not None:
            _k, cid, pos = best
            assign[cid].insert(pos, job.id)
    return _to_plan(P, _refine_assign(P, assign))


# --------------------------------------------------------------------------- local search
def _refine_assign(P: _P, assign: dict[str, list[str]]) -> dict[str, list[str]]:
    """Relocate + swap until no global improvement. Deterministic best-improvement."""
    best_key, _u, _s = _score(P, assign)
    improved = True
    guard = 0
    while improved and guard < 200:
        improved = False
        guard += 1
        # relocate: move one job to another courier / position
        for src in list(assign):
            for ji, jid in enumerate(list(assign[src])):
                job = P.job_by_id[jid]
                for dst in assign:
                    if not _feasible_cold(P, dst, job):
                        continue
                    base_src = assign[src][:ji] + assign[src][ji + 1:]
                    for pos in range(len(assign[dst]) + (0 if dst == src else 1) + 1):
                        if dst == src and pos == ji:
                            continue
                        trial = {**assign, src: base_src}
                        dseq = trial[dst][:]
                        ins = pos if dst != src else (pos if pos < ji else pos)
                        dseq.insert(min(ins, len(dseq)), jid)
                        trial[dst] = dseq
                        if dst == src:
                            trial[src] = dseq
                        key, _u, _s = _score(P, trial)
                        if key > best_key:
                            assign, best_key, improved = trial, key, True
                            break
                    if improved:
                        break
                if improved:
                    break
            if improved:
                break
        if improved:
            continue
        # swap: exchange two jobs between couriers
        ids = [(c, i, j) for c in assign for i, j in enumerate(assign[c])]
        for (c1, i1, j1) in ids:
            for (c2, i2, j2) in ids:
                if c1 == c2 and i1 >= i2:
                    continue
                job1, job2 = P.job_by_id[j1], P.job_by_id[j2]
                if not (_feasible_cold(P, c2, job1) and _feasible_cold(P, c1, job2)):
                    continue
                trial = {c: assign[c][:] for c in assign}
                trial[c1][i1], trial[c2][i2] = j2, j1
                key, _u, _s = _score(P, trial)
                if key > best_key:
                    assign, best_key, improved = trial, key, True
                    break
            if improved:
                break
    return assign


def refine(plan: Plan, req: OptimizeRequest) -> Plan:
    """Polish any candidate Plan via local search (extract assignment, refine, rebuild)."""
    P = _P(req)
    if P.C == 0 or P.J == 0:
        return plan
    assign: dict[str, list[str]] = {c.id: [] for c in P.couriers}
    for route in plan.routes:
        if route.courier_id not in assign:
            continue
        seen = []
        for s in route.stops:
            if s.kind == "dropoff" and s.job_id in P.job_by_id and s.job_id not in seen:
                seen.append(s.job_id)
        assign[route.courier_id] = seen
    return _to_plan(P, _refine_assign(P, assign))


# --------------------------------------------------------------------------- plan assembly
def _to_plan(P: _P, assign: dict[str, list[str]]) -> Plan:
    routes, windows_met, total_time = [], 0, 0.0
    served: set[str] = set()
    windows_total = sum(1 for j in P.jobs if P.due_s(j) is not None)
    for cid, seq in assign.items():
        if not seq:
            continue
        sim, met, _sm, _lw, end = _sim_route(P, cid, seq)
        windows_met += met
        total_time += end
        stops, sequence = [], 0
        for entry in sim:
            kind, jid = entry[0], entry[1]
            eta_s = entry[2]
            job = P.job_by_id[jid]
            loc = job.origin if kind == "pickup" else job.destination
            served.add(jid)
            stops.append(Stop(
                job_id=jid, kind=kind,
                location=Location(lat=loc.lat, lng=loc.lng, name=loc.name, facility_id=loc.facility_id),
                sequence=sequence, eta=P.now + timedelta(seconds=float(eta_s)),
                window_met=(entry[3] if kind == "dropoff" else None),
            ))
            sequence += 1
        dist = sum(_haversine_m(stops[i].location, stops[i + 1].location) for i in range(len(stops) - 1))
        routes.append(Route(courier_id=cid, stops=stops,
                            polyline=[LatLng(lat=s.location.lat, lng=s.location.lng) for s in stops],
                            total_time_s=end, total_distance_m=dist, feasible=True))
    unassigned = [j.id for j in P.jobs if j.id not in served]
    return Plan(routes=routes, unassigned=unassigned,
                objective=Objective(total_time_s=total_time, windows_met=windows_met,
                                    windows_total=windows_total, solver="ls", solve_ms=0.0),
                generated_at=P.now)


def pick_best(plans: list[Plan], P: _P) -> Plan:
    def key(pl: Plan):
        assign = {}
        for r in pl.routes:
            assign[r.courier_id] = []
            seen = []
            for s in r.stops:
                if s.kind == "dropoff" and s.job_id not in seen:
                    seen.append(s.job_id)
            assign[r.courier_id] = seen
        k, _u, _s = _score(P, assign)
        return k
    return max(plans, key=key)


def _haversine_m(a: Location, b: Location) -> float:
    from math import radians, sin, cos, asin, sqrt
    lat1, lng1, lat2, lng2 = map(radians, [a.lat, a.lng, b.lat, b.lng])
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return 2 * 6_371_000 * asin(sqrt(h))
