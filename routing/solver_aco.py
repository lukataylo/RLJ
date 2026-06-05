"""Custom Ant Colony Optimisation solver for the Dynamic Pickup-and-Delivery Problem
with Time Windows and priorities (D-PDPTW) — the routing stream's headline algorithm.

Why ACO for this problem
------------------------
PDPTW is NP-hard and the constraints (pickup-before-dropoff, capacity, cold-chain,
hard-ish time windows weighted by clinical priority) are awkward for exact solvers under
a re-plan-every-few-seconds budget. ACO is a population metaheuristic: ``K`` ants each
stochastically *construct* a full multi-vehicle solution biased by pheromone (learned
edge desirability) and a heuristic (inverse travel time + lateness penalty); the best
solutions reinforce their edges; repeat. It degrades gracefully (any iteration yields a
valid plan) and — crucially for the hardware story — its hot loop is embarrassingly
parallel across ants.

GB10 mapping (the speedup story)
--------------------------------
The expensive per-step work is computed for **all K ants at once** as ``(K, N)`` array
ops through the module-level ``xp`` namespace (CuPy on the GB10, NumPy here):

    * gather pheromone/heuristic rows for every ant's current node      -> (K, N)
    * mask infeasible moves (capacity / pickup-order / cold-chain / TW)  -> (K, N)
    * weight, normalise, and roulette-select a move per ant             -> (K,)

On the GB10 those tensors live in device memory and ``xp is cupy`` makes this a kernel
launch per construction step across thousands of ants — no code change. On this Mac
``xp is numpy`` and it runs on CPU. The only per-ant Python is the O(K) state apply,
which is cheap and is itself a documented candidate for a custom fused CUDA kernel.

The solver returns a fully-formed :class:`~models.Plan` (ETAs, ``window_met``,
``objective.solve_ms``) ready to hand back through ``/optimize``.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np

from models import (
    LatLng,
    Location,
    Objective,
    OptimizeRequest,
    Plan,
    Route,
    Stop,
)
from traveltime import build_travel_time_matrix

# --- array backend: CuPy on the GB10, NumPy on this Mac -----------------------------
try:  # pragma: no cover - GPU only
    import cupy as xp  # type: ignore

    GPU_BACKEND = True
except Exception:  # noqa: BLE001
    import numpy as xp  # type: ignore

    GPU_BACKEND = False

# Reported in Plan.objective.solver and GET /healthz so the UI can show the real engine.
SOLVER_NAME = "gpu-aco" if GPU_BACKEND else "aco-numpy"

SERVICE_S = 120.0  # dwell time per stop (matches greedy)
# Clinical priority -> lateness weight. STAT lateness dominates the objective.
PRIORITY_WEIGHT = {"stat": 100.0, "urgent": 10.0, "routine": 1.0}
PRIORITY_RANK = {"stat": 0, "urgent": 1, "routine": 2}

# Objective composition (minimised). Lateness is paramount; makespan keeps routes tight;
# total_time is a light tie-breaker; an unserved job is catastrophic.
LATE_COST_W = 50.0
MAKESPAN_W = 1.0
TOTAL_TIME_W = 0.001
UNASSIGNED_COST = 1.0e9


@dataclass
class ACOParams:
    n_ants: int = 24
    n_iter: int = 60
    alpha: float = 1.0       # pheromone exponent
    beta: float = 3.0        # heuristic exponent
    rho: float = 0.1         # evaporation rate
    q: float = 1.0           # deposit scale
    tau0: float = 1.0        # initial pheromone
    switch_bias: float = 0.6  # propensity to start the next courier's route
    seed: int = 7


@dataclass
class _Problem:
    """Flattened, index-based view of the request the hot loop operates on."""

    # node layout: depot c -> c ; job j pickup -> C + 2j ; dropoff -> C + 2j + 1
    C: int
    J: int
    N: int
    coords: list[tuple[float, float]]          # per node (lat, lng)
    T: np.ndarray                              # (N, N) travel-time seconds (host)
    veh_cap: np.ndarray                        # (C,)
    veh_cold: np.ndarray                       # (C,) bool, cold-capable
    veh_depot_node: np.ndarray                 # (C,) node index of each depot
    job_pick_node: np.ndarray                  # (J,)
    job_drop_node: np.ndarray                  # (J,)
    job_cap: np.ndarray                        # (J,)
    job_cold: np.ndarray                       # (J,) bool
    job_ready_s: np.ndarray                    # (J,) seconds rel. now (pickup earliest)
    job_due_s: np.ndarray                      # (J,) seconds rel. now; +inf if no window
    job_has_window: np.ndarray                 # (J,) bool
    job_prio_w: np.ndarray                     # (J,) lateness weight
    couriers: list = field(default_factory=list)
    jobs: list = field(default_factory=list)


def _seconds_since(now: datetime, dt: Optional[datetime]) -> Optional[float]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt - now).total_seconds()


def _build_problem(req: OptimizeRequest, now: datetime) -> _Problem:
    couriers = [c for c in req.couriers if c.status != "offline"]
    jobs = list(req.jobs)
    C, J = len(couriers), len(jobs)
    N = C + 2 * J

    coords: list[tuple[float, float]] = [(c.location.lat, c.location.lng) for c in couriers]
    for j in jobs:
        coords.append((j.origin.lat, j.origin.lng))       # pickup
        coords.append((j.destination.lat, j.destination.lng))  # dropoff

    lats = [c[0] for c in coords]
    lngs = [c[1] for c in coords]
    T = build_travel_time_matrix(lats, lngs, disruptions=req.disruptions)

    veh_cap = np.array([float(c.capacity) for c in couriers], dtype=np.float64)
    veh_cold = np.array([bool(getattr(c, "cold_capable", True)) for c in couriers])
    veh_depot_node = np.arange(C, dtype=np.int64)

    job_pick_node = np.array([C + 2 * j for j in range(J)], dtype=np.int64)
    job_drop_node = np.array([C + 2 * j + 1 for j in range(J)], dtype=np.int64)
    job_cap = np.array([float(j.capacity_units) for j in jobs], dtype=np.float64)
    job_cold = np.array([bool(j.cold_chain) for j in jobs])

    ready, due, has_win, prio_w = [], [], [], []
    for j in jobs:
        r = _seconds_since(now, j.time_window.ready_at) if j.time_window else None
        d = _seconds_since(now, j.time_window.due_by) if j.time_window else None
        ready.append(0.0 if r is None else max(0.0, r))
        has_win.append(d is not None)
        due.append(np.inf if d is None else d)
        prio_w.append(PRIORITY_WEIGHT.get(j.priority, 1.0))

    return _Problem(
        C=C, J=J, N=N, coords=coords, T=T,
        veh_cap=veh_cap, veh_cold=veh_cold, veh_depot_node=veh_depot_node,
        job_pick_node=job_pick_node, job_drop_node=job_drop_node,
        job_cap=job_cap, job_cold=job_cold,
        job_ready_s=np.array(ready), job_due_s=np.array(due),
        job_has_window=np.array(has_win), job_prio_w=np.array(prio_w),
        couriers=couriers, jobs=jobs,
    )


class ACOSolver:
    """Ant Colony Optimisation for D-PDPTW. Stateless across calls; ``solve`` is reentrant."""

    def __init__(self, params: ACOParams | None = None) -> None:
        self.p = params or ACOParams()

    # -- public API ------------------------------------------------------------------
    def solve(self, req: OptimizeRequest) -> Plan:
        t0 = time.perf_counter()
        now = req.now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        prob = _build_problem(req, now)
        if prob.J == 0 or prob.C == 0:
            return self._empty_plan(prob, now, (time.perf_counter() - t0) * 1e3)

        best_records, best_cost = self._run_colony(prob)
        plan = self._records_to_plan(prob, best_records, now)
        plan.objective.solve_ms = (time.perf_counter() - t0) * 1e3
        plan.objective.solver = SOLVER_NAME
        return plan

    # -- ACO core --------------------------------------------------------------------
    def _run_colony(self, prob: _Problem):
        p = self.p
        N = prob.N
        # Pheromone & heuristic live on the device (xp). Travel times -> xp once.
        tau = xp.full((N, N), p.tau0, dtype=xp.float64)
        T = xp.asarray(prob.T)
        H = 1.0 / (T + 1.0)  # inverse travel time heuristic, (N, N)

        best_records: list | None = None
        best_cost = np.inf

        for _ in range(p.n_iter):
            records, costs = self._construct_all(prob, tau, H, T)
            it_best = int(np.argmin(costs))
            if costs[it_best] < best_cost:
                best_cost = float(costs[it_best])
                best_records = records[it_best]
            self._update_pheromone(prob, tau, best_records, best_cost)

        return best_records or [], best_cost

    def _construct_all(self, prob: _Problem, tau, H, T):
        """Build one solution per ant. Heavy math is vectorised over the K ants.

        Returns (records, costs) where ``records[k]`` is a list of
        ``(veh_idx, job_idx, kind, eta_seconds)`` tuples and ``costs[k]`` the scalar
        objective. The construction *step* below is the GB10 hot loop.
        """
        p = self.p
        K, C, J, N = p.n_ants, prob.C, prob.J, prob.N
        rng = np.random.default_rng(p.seed)

        # Pull constant problem arrays onto the device once.
        p_idx = xp.asarray(prob.job_pick_node)
        d_idx = xp.asarray(prob.job_drop_node)
        job_cap = xp.asarray(prob.job_cap)
        job_cold = xp.asarray(prob.job_cold)
        job_ready = xp.asarray(prob.job_ready_s)
        job_due = xp.asarray(prob.job_due_s)
        job_prio = xp.asarray(prob.job_prio_w)
        veh_cap = xp.asarray(prob.veh_cap)
        veh_cold = xp.asarray(prob.veh_cold)
        veh_depot = xp.asarray(prob.veh_depot_node)

        # Per-ant state (all (K,) or (K, J)) — resident on device.
        veh = xp.zeros(K, dtype=xp.int64)
        cur_node = veh_depot[veh]
        cur_time = xp.zeros(K, dtype=xp.float64)        # seconds since `now`
        cap_left = veh_cap[veh]
        onboard = xp.zeros((K, J), dtype=bool)
        done_pick = xp.zeros((K, J), dtype=bool)
        done_drop = xp.zeros((K, J), dtype=bool)
        active = xp.ones(K, dtype=bool)

        records: list[list] = [[] for _ in range(K)]
        ant_ids = np.arange(K)

        Lscale = 1800.0  # lateness softening scale (s) for the heuristic
        max_steps = 4 * J + 2 * C + 4  # safety bound

        for _ in range(max_steps):
            if not bool(xp.any(active)):
                break

            # ---- vectorised candidate scoring over all ants: (K, J) -----------------
            tau_cur = tau[cur_node]                       # (K, N)
            H_cur = H[cur_node]                           # (K, N)
            T_cur = T[cur_node]                           # (K, N)
            arr_pick = cur_time[:, None] + T_cur[:, p_idx]   # (K, J)
            arr_drop = cur_time[:, None] + T_cur[:, d_idx]   # (K, J)

            cold_ok = (~job_cold[None, :]) | veh_cold[veh][:, None]      # (K, J)
            feas_pick = (~done_pick) & (cap_left[:, None] >= job_cap[None, :]) & cold_ok
            feas_drop = onboard

            base_pick = (tau_cur[:, p_idx] ** p.alpha) * (H_cur[:, p_idx] ** p.beta)
            wait = xp.maximum(0.0, job_ready[None, :] - arr_pick)
            w_pick = base_pick * xp.exp(-wait / Lscale) * feas_pick

            base_drop = (tau_cur[:, d_idx] ** p.alpha) * (H_cur[:, d_idx] ** p.beta)
            lateness = xp.maximum(0.0, arr_drop - job_due[None, :])
            lateness = xp.where(xp.isfinite(lateness), lateness, 0.0)
            drop_pen = xp.exp(-(lateness * job_prio[None, :]) / Lscale)
            w_drop = base_drop * drop_pen * feas_drop

            # Option to close the current route and start the next courier: only legal
            # with an empty hold, jobs left to serve, and a spare courier.
            remaining = (~done_drop).any(axis=1)
            can_switch = (veh < (C - 1)) & (~onboard.any(axis=1)) & remaining
            w_switch = can_switch.astype(xp.float64) * p.switch_bias

            W = xp.concatenate([w_pick, w_drop, w_switch[:, None]], axis=1)  # (K, 2J+1)
            row = W.sum(axis=1)

            # Ants with no legal move finish (their unserved jobs become unassigned).
            stuck = (row <= 0.0) & active
            active = active & ~stuck

            # Roulette-wheel selection per active ant (fully vectorised).
            safe_row = xp.where(row > 0.0, row, 1.0)
            probs = W / safe_row[:, None]
            cum = xp.cumsum(probs, axis=1)
            r = xp.asarray(rng.random(K))
            choice = (cum < r[:, None]).sum(axis=1)
            choice = xp.minimum(choice, 2 * J)  # guard fp edge case

            # ---- O(K) state apply (host-side scalars; small, GPU-kernel candidate) ---
            act = _to_host(active)
            ch = _to_host(choice)
            for k in ant_ids[act]:
                a = int(ch[k])
                if a == 2 * J:  # switch courier
                    nv = int(_to_host(veh[k])) + 1
                    veh[k] = nv
                    cur_node[k] = veh_depot[nv]
                    cur_time[k] = 0.0
                    cap_left[k] = veh_cap[nv]
                    continue
                vk = int(_to_host(veh[k]))
                if a < J:  # pickup job a
                    j = a
                    arrival = float(_to_host(cur_time[k])) + float(prob.T[int(_to_host(cur_node[k])), prob.job_pick_node[j]])
                    start = max(arrival, float(prob.job_ready_s[j]))
                    cur_time[k] = start + SERVICE_S
                    cur_node[k] = int(prob.job_pick_node[j])
                    cap_left[k] = float(_to_host(cap_left[k])) - float(prob.job_cap[j])
                    onboard[k, j] = True
                    done_pick[k, j] = True
                    records[k].append((vk, j, "pickup", start))
                else:  # dropoff job a-J
                    j = a - J
                    arrival = float(_to_host(cur_time[k])) + float(prob.T[int(_to_host(cur_node[k])), prob.job_drop_node[j]])
                    cur_time[k] = arrival + SERVICE_S
                    cur_node[k] = int(prob.job_drop_node[j])
                    cap_left[k] = float(_to_host(cap_left[k])) + float(prob.job_cap[j])
                    onboard[k, j] = False
                    done_drop[k, j] = True
                    records[k].append((vk, j, "dropoff", arrival))

        costs = np.array([self._cost(prob, records[k]) for k in range(K)])
        return records, costs

    def _cost(self, prob: _Problem, rec: list) -> float:
        veh_end: dict[int, float] = {}
        weighted_late = 0.0
        delivered = 0
        for (v, j, kind, eta_s) in rec:
            veh_end[v] = max(veh_end.get(v, 0.0), eta_s)
            if kind == "dropoff":
                delivered += 1
                if prob.job_has_window[j] and eta_s > prob.job_due_s[j]:
                    weighted_late += (eta_s - prob.job_due_s[j]) * prob.job_prio_w[j]
        makespan = max(veh_end.values()) if veh_end else 0.0
        total = sum(veh_end.values())
        unassigned = prob.J - delivered
        return (
            LATE_COST_W * weighted_late
            + MAKESPAN_W * makespan
            + TOTAL_TIME_W * total
            + UNASSIGNED_COST * unassigned
        )

    def _update_pheromone(self, prob: _Problem, tau, best_records, best_cost) -> None:
        tau *= (1.0 - self.p.rho)  # evaporate everywhere
        if not best_records or not np.isfinite(best_cost) or best_cost <= 0:
            return
        deposit = self.p.q / (best_cost + 1.0)
        # Reinforce the consecutive edges actually travelled per courier in the best ant.
        by_veh: dict[int, list[int]] = {}
        for (v, j, kind, _eta) in best_records:
            node = prob.job_pick_node[j] if kind == "pickup" else prob.job_drop_node[j]
            by_veh.setdefault(v, [int(prob.veh_depot_node[v])]).append(int(node))
        for nodes in by_veh.values():
            for a, b in zip(nodes[:-1], nodes[1:]):
                tau[a, b] += deposit
                tau[b, a] += deposit  # symmetric travel

    # -- Plan assembly ---------------------------------------------------------------
    def _records_to_plan(self, prob: _Problem, rec: list, now: datetime) -> Plan:
        routes: list[Route] = []
        windows_met = 0
        windows_total = int(np.count_nonzero(prob.job_has_window))
        total_time = 0.0
        served: set[int] = set()

        by_veh: dict[int, list] = {}
        for entry in rec:
            by_veh.setdefault(entry[0], []).append(entry)

        for v, entries in sorted(by_veh.items()):
            courier = prob.couriers[v]
            stops: list[Stop] = []
            for seq, (_v, j, kind, eta_s) in enumerate(entries):
                job = prob.jobs[j]
                loc = job.origin if kind == "pickup" else job.destination
                eta_dt = now + timedelta(seconds=float(eta_s))
                met: Optional[bool] = None
                if kind == "dropoff":
                    served.add(j)
                    if prob.job_has_window[j]:
                        met = bool(eta_s <= prob.job_due_s[j])
                        windows_met += int(met)
                stops.append(
                    Stop(
                        job_id=job.id,
                        kind=kind,  # type: ignore[arg-type]
                        location=Location(lat=loc.lat, lng=loc.lng, name=loc.name,
                                          facility_id=loc.facility_id),
                        sequence=seq,
                        eta=eta_dt,
                        window_met=met,
                    )
                )
            if not stops:
                continue
            route_time = float(stops[-1].eta.timestamp() - now.timestamp()) if stops[-1].eta else 0.0
            total_time += route_time
            dist_m = sum(
                _haversine_m(stops[i].location, stops[i + 1].location)
                for i in range(len(stops) - 1)
            )
            routes.append(
                Route(
                    courier_id=courier.id,
                    stops=stops,
                    polyline=[LatLng(lat=s.location.lat, lng=s.location.lng) for s in stops],
                    total_time_s=route_time,
                    total_distance_m=dist_m,
                    feasible=True,
                )
            )

        unassigned = [prob.jobs[j].id for j in range(prob.J) if j not in served]
        return Plan(
            routes=routes,
            unassigned=unassigned,
            objective=Objective(
                total_time_s=total_time,
                windows_met=windows_met,
                windows_total=windows_total,
                solver=SOLVER_NAME,
                solve_ms=0.0,
            ),
            generated_at=now,
        )

    def _empty_plan(self, prob: _Problem, now: datetime, solve_ms: float) -> Plan:
        return Plan(
            routes=[],
            unassigned=[j.id for j in prob.jobs],
            objective=Objective(
                total_time_s=0.0, windows_met=0,
                windows_total=int(np.count_nonzero(prob.job_has_window)),
                solver=SOLVER_NAME, solve_ms=solve_ms,
            ),
            generated_at=now,
        )


def _to_host(a):
    """Return a NumPy view of an xp array (no-op on NumPy, device->host on CuPy)."""
    if GPU_BACKEND:  # pragma: no cover - GPU only
        return xp.asnumpy(a)
    return a


def _haversine_m(a: Location, b: Location) -> float:
    from math import radians, sin, cos, asin, sqrt

    lat1, lng1, lat2, lng2 = map(radians, [a.lat, a.lng, b.lat, b.lng])
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return 2 * 6_371_000 * asin(sqrt(h))


def solve(req: OptimizeRequest, params: ACOParams | None = None) -> Plan:
    """Module-level convenience entry point used by app.py and bench.py."""
    return ACOSolver(params).solve(req)
