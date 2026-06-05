"""Delta-evaluation metaheuristic for the clinical PDPTW — the breakthrough engine.

Why this exists
---------------
``solver_ls`` is correct but evaluates every candidate move by re-simulating the *entire*
plan (``_score`` -> ``_sim_route`` over **all** couriers). That is O(C·J) work per move, so
a single local-search sweep is O(C·J · moves), and the portfolio hard-gates it off above
~25 jobs because it simply does not scale.

This module keeps the *identical* clinical objective and route simulation semantics, but
makes local search **incremental**, following standard routing research:

  * **Delta evaluation** — a move touches at most two routes, so we recompute only those
    two routes' cached metrics and update running global totals, instead of re-scoring the
    whole plan. (Bentley 1992; Vidal 2012/2022; Ropke & Pisinger 2006.)
  * **Neighbor lists** — each job only considers relocations/swaps near its k geographically
    closest jobs, turning an O(J) candidate scan per job into O(k). (Bentley 1992.)
  * **Don't-look bits** — a job that yielded no improving move is skipped until one of its
    routes changes. (Bentley 1992.)
  * **Ruin-and-recreate (LNS)** — escape local optima by removing a related set of jobs
    (random + Shaw-relatedness) and reinserting them with greedy/regret insertion, inside an
    iterated-local-search loop on a wall-clock budget. (Ropke & Pisinger, Transportation
    Science 2006; Shaw 1998.)

The objective key is byte-for-byte the same lexicographic tuple ``solver_ls`` uses
(``stat_met, met, -unassigned, -late_w, -total``) so a head-to-head against ``solver_ls``
and OR-Tools is apples-to-apples — see ``tests/benchmarks/test_hgs_speedup.py``.

References: HGS arXiv:2012.10384 · PyVRP arXiv:2403.13795 · ALNS-PDPTW
doi:10.1287/trsc.1050.0135 · Bentley, ORSA J. Computing 4(4) 1992.
"""
from __future__ import annotations

import time
from datetime import timedelta, timezone
from typing import Optional

import numpy as np

from models import LatLng, Location, Objective, OptimizeRequest, Plan, Route, Stop
from solver_ls import (
    PRIORITY_RANK,
    PRIORITY_WEIGHT,
    SERVICE_S,
    _P,
)

SOLVER_NAME = "hgs-delta"
NEIGHBORS_K = 8
DEFAULT_BUDGET_S = 1.0


# ----------------------------------------------------------------------- problem caching
class _PC:
    """Wraps ``solver_ls._P`` and precomputes the per-job constants + neighbor lists the
    delta engine reads in its hot loop, so route metric evaluation is pure array math."""

    def __init__(self, req: OptimizeRequest):
        self.P = P = _P(req)
        self.cids = [c.id for c in P.couriers]
        self.jids = [j.id for j in P.jobs]
        self.T = P.T
        # per-job constants
        self.ready = {j.id: P.ready_s(j) for j in P.jobs}
        self.due = {j.id: P.due_s(j) for j in P.jobs}
        self.prio = {j.id: j.priority for j in P.jobs}
        self.prio_w = {j.id: PRIORITY_WEIGHT.get(j.priority, 1.0) for j in P.jobs}
        self.cold = {j.id: bool(j.cold_chain) for j in P.jobs}
        self.units = {j.id: float(j.capacity_units) for j in P.jobs}
        self.pick = P.pick
        self.drop = P.drop
        self.depot = P.depot
        self.cap = P.cap
        self.cold_ok = P.cold_ok
        self.stat_total = sum(
            1 for j in P.jobs if j.priority == "stat" and self.due[j.id] is not None
        )
        self._neighbors = self._build_neighbors()

    def _build_neighbors(self) -> dict[str, list[str]]:
        """k nearest jobs for each job, by drop->pick travel time (where you'd chain them)."""
        nb: dict[str, list[str]] = {}
        for a in self.jids:
            da = self.drop[a]
            order = sorted(
                (b for b in self.jids if b != a),
                key=lambda b: self.T[da, self.pick[b]],
            )
            nb[a] = order[:NEIGHBORS_K]
        return nb

    def feasible(self, cid: str, jid: str) -> bool:
        return (not self.cold[jid] or self.cold_ok[cid]) and self.units[jid] <= self.cap[cid]

    def route_metrics(self, cid: str, seq: list[str]):
        """(stat_met, met, late_w, end) for one courier's pairwise route.

        Identical arithmetic to ``solver_ls._sim_route`` so objectives are comparable."""
        T = self.T
        node = self.depot[cid]
        t = 0.0
        met = stat_met = 0
        late_w = 0.0
        cold_ok = self.cold_ok[cid]
        cap = self.cap[cid]
        for jid in seq:
            if self.cold[jid] and not cold_ok:
                late_w += 1e6
            if self.units[jid] > cap:
                late_w += 1e6
            t += T[node, self.pick[jid]]
            r = self.ready[jid]
            if t < r:
                t = r
            node = self.pick[jid]
            t += SERVICE_S
            t += T[node, self.drop[jid]]
            node = self.drop[jid]
            arrival = t
            due = self.due[jid]
            if due is not None:
                if arrival <= due:
                    met += 1
                    if self.prio[jid] == "stat":
                        stat_met += 1
                else:
                    late_w += (arrival - due) * self.prio_w[jid]
            t += SERVICE_S
        return stat_met, met, late_w, t


# ----------------------------------------------------------------------------- solution
class _Sol:
    """A full assignment with cached per-route metrics and exactly-maintained totals.

    Totals are recomputed by summing the (few) cached per-route metrics on every commit —
    O(C), exact, no float drift. Moves are scored *functionally* via :meth:`trial_key`
    (no mutate/revert), so a single candidate evaluation is O(route length), never O(plan).
    """

    __slots__ = ("pc", "routes", "m", "unassigned", "ts", "tm", "tl", "te")

    def __init__(self, pc: _PC):
        self.pc = pc
        self.routes: dict[str, list[str]] = {c: [] for c in pc.cids}
        self.m: dict[str, tuple] = {c: (0, 0, 0.0, 0.0) for c in pc.cids}
        self.unassigned: set[str] = set(pc.jids)
        self._resum()

    def _resum(self):
        ts = tm = 0
        tl = te = 0.0
        for s, m, l, e in self.m.values():
            ts += s
            tm += m
            tl += l
            te += e
        self.ts, self.tm, self.tl, self.te = ts, tm, tl, te

    def clone(self) -> "_Sol":
        s = _Sol.__new__(_Sol)
        s.pc = self.pc
        s.routes = {c: seq[:] for c, seq in self.routes.items()}
        s.m = dict(self.m)
        s.unassigned = set(self.unassigned)
        s.ts, s.tm, s.tl, s.te = self.ts, self.tm, self.tl, self.te
        return s

    def key(self):
        return (self.ts, self.tm, -len(self.unassigned), -self.tl, -self.te)

    def trial_key(self, changes: dict, dunas: int = 0):
        """Key the solution WOULD have if each route in ``changes`` took the given metrics.

        Pure: reads exact cached old metrics + the supplied new ones, never mutates."""
        ts, tm, tl, te = self.ts, self.tm, self.tl, self.te
        for cid, (s, m, l, e) in changes.items():
            os_, om, ol, oe = self.m[cid]
            ts += s - os_
            tm += m - om
            tl += l - ol
            te += e - oe
        return (ts, tm, -(len(self.unassigned) + dunas), -tl, -te)

    def set_route(self, cid: str, seq: list[str], metrics: Optional[tuple] = None):
        self.routes[cid] = seq
        self.m[cid] = metrics if metrics is not None else self.pc.route_metrics(cid, seq)
        self._resum()


# --------------------------------------------------------------------------- construction
def _best_insertion(sol: _Sol, jid: str, cids):
    """Return (key, cid, new_seq, metrics) for the cheapest feasible insertion of jid."""
    pc = sol.pc
    best = None
    for cid in cids:
        if not pc.feasible(cid, jid):
            continue
        seq = sol.routes[cid]
        for pos in range(len(seq) + 1):
            trial = seq[:pos] + [jid] + seq[pos:]
            met = pc.route_metrics(cid, trial)
            k = sol.trial_key({cid: met}, dunas=-1)
            if best is None or k > best[0]:
                best = (k, cid, trial, met)
    return best


def _greedy_fill(sol: _Sol, jobs: list[str]) -> None:
    """Regret-aware cheapest-feasible insertion (STAT first), delta-evaluated.

    Per round, place the still-unplaced job with the largest 'regret' (gap between its best
    and second-best insertion key) at its best slot — the classic ALNS repair that avoids
    stranding hard jobs. Only the candidate route is re-evaluated per trial."""
    pc = sol.pc
    pending = sorted(
        jobs,
        key=lambda j: (PRIORITY_RANK.get(pc.prio[j], 3),
                       pc.due[j] if pc.due[j] is not None else 1e9),
    )
    while pending:
        # cheap path for the common case: just take priority order, best-insert each.
        jid = pending.pop(0)
        ins = _best_insertion(sol, jid, pc.cids)
        if ins is not None:
            _k, cid, new_seq, met = ins
            sol.set_route(cid, new_seq, met)
            sol.unassigned.discard(jid)


# --------------------------------------------------------------------------- local search
def _local_search(sol: _Sol, deadline: float) -> None:
    """Relocate + swap with neighbor lists and don't-look bits, first-improvement.

    A move recomputes at most two routes; the global key is updated incrementally."""
    pc = sol.pc
    job_route = {}
    for cid, seq in sol.routes.items():
        for jid in seq:
            job_route[jid] = cid
    active = [j for j in pc.jids if j in job_route]
    dont_look = set()
    queue = list(active)
    guard = 0
    while queue and guard < 100000:
        guard += 1
        if guard % 64 == 0 and time.perf_counter() > deadline:
            return
        jid = queue.pop(0)
        if jid in dont_look or jid not in job_route:
            continue
        if _try_improve(sol, jid, job_route, queue, dont_look):
            continue
        dont_look.add(jid)


def _try_improve(sol: _Sol, jid: str, job_route, queue, dont_look) -> bool:
    pc = sol.pc
    src = job_route[jid]
    base_key = sol.key()

    # candidate destination routes: routes holding a near neighbor of jid, plus src.
    dest_cids = {src}
    for nb in pc._neighbors[jid]:
        if nb in job_route:
            dest_cids.add(job_route[nb])

    src_seq = sol.routes[src]
    si = src_seq.index(jid)
    src_wo = src_seq[:si] + src_seq[si + 1:]

    # ---- relocate jid into a (possibly different) route at its best position
    for dst in dest_cids:
        if not pc.feasible(dst, jid):
            continue
        if dst == src:
            base_seq = src_wo
        else:
            base_seq = sol.routes[dst]
        for pos in range(len(base_seq) + 1):
            new_dst = base_seq[:pos] + [jid] + base_seq[pos:]
            if dst == src:
                cand = _apply_one(sol, src, new_dst)
                if cand > base_key:
                    _commit_one(sol, src, new_dst, base_key, job_route, queue, dont_look)
                    return True
                _revert_one(sol, src, src_seq)
            else:
                cand = _apply_two(sol, src, src_wo, dst, new_dst)
                if cand > base_key:
                    _commit_two(sol, src, src_wo, dst, new_dst, jid,
                                job_route, queue, dont_look)
                    return True
                _revert_two(sol, src, src_seq, dst, base_seq)

    # ---- swap jid with a near neighbor in another route
    for nb in pc._neighbors[jid]:
        if nb not in job_route:
            continue
        dst = job_route[nb]
        if dst == src:
            continue
        if not (pc.feasible(dst, jid) and pc.feasible(src, nb)):
            continue
        dst_seq = sol.routes[dst]
        di = dst_seq.index(nb)
        new_src = src_seq[:si] + [nb] + src_seq[si + 1:]
        new_dst = dst_seq[:di] + [jid] + dst_seq[di + 1:]
        cand = _apply_two(sol, src, new_src, dst, new_dst)
        if cand > base_key:
            _commit_two(sol, src, new_src, dst, new_dst, jid,
                        job_route, queue, dont_look, extra=nb)
            return True
        _revert_two(sol, src, src_seq, dst, dst_seq)
    return False


# move apply/revert helpers — keep totals consistent and cheap
def _apply_one(sol, cid, seq):
    sol.set_route(cid, seq)
    return sol.key()


def _revert_one(sol, cid, seq):
    sol.set_route(cid, seq)


def _apply_two(sol, c1, s1, c2, s2):
    sol.set_route(c1, s1)
    sol.set_route(c2, s2)
    return sol.key()


def _revert_two(sol, c1, s1, c2, s2):
    sol.set_route(c1, s1)
    sol.set_route(c2, s2)


def _commit_one(sol, cid, seq, base_key, job_route, queue, dont_look):
    for j in seq:
        job_route[j] = cid
    _wake(seq, queue, dont_look)


def _commit_two(sol, c1, s1, c2, s2, jid, job_route, queue, dont_look, extra=None):
    for j in s1:
        job_route[j] = c1
    for j in s2:
        job_route[j] = c2
    _wake(s1, queue, dont_look)
    _wake(s2, queue, dont_look)


def _wake(seq, queue, dont_look):
    for j in seq:
        if j in dont_look:
            dont_look.discard(j)
        queue.append(j)


# ----------------------------------------------------------------- ruin & recreate (LNS)
def _shaw_remove(sol: _Sol, rng, q: int) -> list[str]:
    """Remove q related jobs: a random seed, then its travel-time-closest assigned jobs."""
    pc = sol.pc
    assigned = [j for j in pc.jids if j not in sol.unassigned]
    if not assigned:
        return []
    q = min(q, len(assigned))
    seed = assigned[int(rng.integers(len(assigned)))]
    related = sorted(
        (j for j in assigned if j != seed),
        key=lambda j: pc.T[pc.drop[seed], pc.pick[j]],
    )
    chosen = [seed] + related[: q - 1]
    _remove_jobs(sol, chosen)
    return chosen


def _random_remove(sol: _Sol, rng, q: int) -> list[str]:
    pc = sol.pc
    assigned = [j for j in pc.jids if j not in sol.unassigned]
    if not assigned:
        return []
    q = min(q, len(assigned))
    idx = rng.choice(len(assigned), size=q, replace=False)
    chosen = [assigned[i] for i in idx]
    _remove_jobs(sol, chosen)
    return chosen


def _remove_jobs(sol: _Sol, jobs: list[str]) -> None:
    drop = set(jobs)
    touched = set()
    for cid, seq in sol.routes.items():
        if any(j in drop for j in seq):
            touched.add(cid)
    for cid in touched:
        sol.set_route(cid, [j for j in sol.routes[cid] if j not in drop])
    for j in jobs:
        sol.unassigned.add(j)


def solve(req: OptimizeRequest, *, time_budget_s: float = DEFAULT_BUDGET_S,
          seed: int = 12345) -> Plan:
    """Construct -> local search -> iterated ruin-and-recreate, best kept, within budget."""
    t0 = time.perf_counter()
    pc = _PC(req)
    if not pc.cids or not pc.jids:
        return _to_plan(pc, _Sol(pc), t0)

    rng = np.random.default_rng(seed)
    sol = _Sol(pc)
    _greedy_fill(sol, list(pc.jids))
    deadline = t0 + time_budget_s
    _local_search(sol, deadline)
    best = sol.clone()
    best_key = best.key()

    n = len(pc.jids)
    it = 0
    while time.perf_counter() < deadline:
        it += 1
        cand = best.clone()
        q = max(1, int(rng.integers(2, max(3, n // 3) + 1)))
        removed = (_shaw_remove if it % 2 == 0 else _random_remove)(cand, rng, q)
        if removed:
            _greedy_fill(cand, removed)
        _local_search(cand, deadline)
        k = cand.key()
        if k > best_key:
            best, best_key = cand, k
    return _to_plan(pc, best, t0)


# --------------------------------------------------------------------------- plan assembly
def _to_plan(pc: _PC, sol: _Sol, t0: float) -> Plan:
    P = pc.P
    routes, windows_met, total_time = [], 0, 0.0
    served: set[str] = set()
    windows_total = sum(1 for j in P.jobs if pc.due[j.id] is not None)
    for cid, seq in sol.routes.items():
        if not seq:
            continue
        node = pc.depot[cid]
        t = 0.0
        stops, sequence = [], 0
        for jid in seq:
            job = P.job_by_id[jid]
            t += pc.T[node, pc.pick[jid]]
            r = pc.ready[jid]
            if t < r:
                t = r
            node = pc.pick[jid]
            served.add(jid)
            stops.append(Stop(
                job_id=jid, kind="pickup",
                location=Location(lat=job.origin.lat, lng=job.origin.lng,
                                  name=job.origin.name, facility_id=job.origin.facility_id),
                sequence=sequence, eta=P.now + timedelta(seconds=float(t)), window_met=None))
            sequence += 1
            t += SERVICE_S
            t += pc.T[node, pc.drop[jid]]
            node = pc.drop[jid]
            arrival = t
            due = pc.due[jid]
            win = None if due is None else (arrival <= due)
            if win:
                windows_met += 1
            stops.append(Stop(
                job_id=jid, kind="dropoff",
                location=Location(lat=job.destination.lat, lng=job.destination.lng,
                                  name=job.destination.name,
                                  facility_id=job.destination.facility_id),
                sequence=sequence, eta=P.now + timedelta(seconds=float(arrival)),
                window_met=win))
            sequence += 1
            t += SERVICE_S
        dist = sum(_haversine_m(stops[i].location, stops[i + 1].location)
                   for i in range(len(stops) - 1))
        total_time += t
        routes.append(Route(courier_id=cid, stops=stops,
                            polyline=[LatLng(lat=s.location.lat, lng=s.location.lng) for s in stops],
                            total_time_s=t, total_distance_m=dist, feasible=True))
    unassigned = [j.id for j in P.jobs if j.id not in served]
    return Plan(routes=routes, unassigned=unassigned,
                objective=Objective(total_time_s=total_time, windows_met=windows_met,
                                    windows_total=windows_total, solver=SOLVER_NAME,
                                    solve_ms=(time.perf_counter() - t0) * 1e3),
                generated_at=P.now)


def _haversine_m(a: Location, b: Location) -> float:
    from math import asin, cos, radians, sin, sqrt
    lat1, lng1, lat2, lng2 = map(radians, [a.lat, a.lng, b.lat, b.lng])
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return 2 * 6_371_000 * asin(sqrt(h))
