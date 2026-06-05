"""Counterfactual policy study: does anticipating scheduled closures help?

2x2 factorial (solver: ours-portfolio vs OR-Tools x information: reactive vs anticipatory)
plus a naive greedy floor and a disruption-blind control. Every policy plans under its
information set; all are scored on the same realised timeline (groundtruth.py) over the
shared river-barrier network (network.py). Scenarios include a *currently-active* traffic
zone (reactive can use it) and an *imminent Tower Bridge lift* (only anticipatory sees it),
with STAT samples that must cross the river at Tower Bridge.
"""
from __future__ import annotations
import contextlib
from datetime import datetime, timedelta, timezone

import numpy as np

import network
import groundtruth
from models import OptimizeRequest
import solver
import solver_aco
import solver_baseline
import solver_ls
import solver_ortools

NOW = datetime(2026, 6, 6, 9, 0, tzinfo=timezone.utc)
HORIZON_MIN = 120

NDEPOTS = [(51.5185, -0.0610, "Whitechapel depot"), (51.5246, -0.1340, "Euston depot")]
SDEPOTS = [(51.4980, -0.0820, "Bermondsey depot"), (51.4894, -0.1110, "Kennington depot")]
NLABS = [(51.5190, -0.0590, "Royal London lab"), (51.5246, -0.1357, "UCLH lab")]
SLABS = [(51.4980, -0.1188, "St Thomas' lab"), (51.5030, -0.0884, "Guy's lab")]
NPICK = [(51.5140, -0.0750, "Aldgate surgery"), (51.5260, -0.0780, "Shoreditch clinic")]
SPICK = [(51.5000, -0.0780, "Tower-south surgery"), (51.4990, -0.0700, "Bermondsey clinic"),
         (51.4870, -0.0900, "Walworth surgery")]
TOWER = (51.5055, -0.0754)
EUSTON_ZONE = (51.5246, -0.1340)
WINS = {"stat": 55, "urgent": 110, "routine": 170}

POLICIES = ["greedy", "ours_blind", "ours_reactive", "ours_anticipatory",
            "ortools_reactive", "ortools_anticipatory"]


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def _job(jid, prio, origin, dest, cold, now):
    return {"id": jid, "type": "sample_pickup" if cold else "med_delivery", "priority": prio,
            "cold_chain": cold, "capacity_units": 1, "status": "new",
            "origin": {"lat": origin[0], "lng": origin[1], "name": origin[2]},
            "destination": {"lat": dest[0], "lng": dest[1], "name": dest[2]},
            "time_window": {"ready_at": _iso(now), "due_by": _iso(now + timedelta(minutes=WINS[prio]))}}


def _courier(cid, depot, cold=True, cap=6):
    return {"id": cid, "name": cid, "capacity": cap, "cold_capable": cold, "status": "idle",
            "location": {"lat": depot[0], "lng": depot[1], "name": depot[2]}, "phone": "+44700900000"}


def _jit(p, rng, d=0.004):
    return (p[0] + float(rng.uniform(-d, d)), p[1] + float(rng.uniform(-d, d)), p[2])


def build_scenarios(n: int, now: datetime = NOW):
    out = []
    for s in range(n):
        rng = np.random.default_rng(2000 + s)
        couriers = ([_courier(f"n{i}", _jit(NDEPOTS[i], rng), cold=True) for i in range(2)]
                    + [_courier(f"s{i}", _jit(SDEPOTS[i], rng), cold=(i == 0)) for i in range(2)])
        jobs = []
        # cross-river STAT/urgent jobs that naturally use Tower Bridge (south -> north)
        n_cross = int(rng.integers(2, 4))
        for k in range(n_cross):
            prio = "stat" if k < 2 else "urgent"
            origin = _jit(SPICK[0] if k % 2 == 0 else SPICK[1], rng)
            dest = _jit(NLABS[0], rng)  # Royal London (north, near Tower)
            jobs.append(_job(f"x{k}", prio, origin, dest, True, now))
        # same-side filler jobs
        n_same = int(rng.integers(3, 5))
        for k in range(n_same):
            north = rng.random() < 0.5
            prio = ["urgent", "routine", "routine"][int(rng.integers(3))]
            if north:
                origin, dest = _jit(NPICK[int(rng.integers(len(NPICK)))], rng), _jit(NLABS[int(rng.integers(2))], rng)
            else:
                origin, dest = _jit(SPICK[int(rng.integers(len(SPICK)))], rng), _jit(SLABS[int(rng.integers(2))], rng)
            jobs.append(_job(f"f{k}", prio, origin, dest, bool(rng.random() < 0.6), now))

        lift_start = int(rng.integers(2, 6)) * 60  # imminent: starts in 2-6 min
        timeline = [
            {"kind": "traffic", "geometry": [{"lat": EUSTON_ZONE[0], "lng": EUSTON_ZONE[1]}],
             "start_s": -600, "end_s": 2400},                          # currently active
            {"kind": "road_closure", "geometry": [{"lat": TOWER[0], "lng": TOWER[1]}],
             "start_s": lift_start, "end_s": lift_start + 3600},       # scheduled Tower closure (~1h)
        ]
        out.append({"name": f"scn{s}", "now": now, "couriers": couriers, "jobs": jobs, "timeline": timeline})
    return out


def _disrupt(c):
    cid = f"dis-{c['kind']}-{int(c['start_s'])}"
    return {"id": cid, "kind": c["kind"], "geometry": c["geometry"], "source": "manual"}


def _active(timeline):
    return [_disrupt(c) for c in timeline if c["start_s"] <= 0 < c["end_s"]]


def _horizon(timeline, h_min=HORIZON_MIN):
    H = h_min * 60
    return [_disrupt(c) for c in timeline if c["start_s"] < H and c["end_s"] > 0]


def _req(scn, disrupts):
    return OptimizeRequest(now=scn["now"], couriers=scn["couriers"], jobs=scn["jobs"], disruptions=disrupts)


@contextlib.contextmanager
def graph_network():
    """Make the solvers plan on the river-barrier network (so detours are real)."""
    orig = {}
    for mod in (solver_ls, solver_aco, solver_ortools):
        orig[mod] = mod.build_travel_time_matrix
        mod.build_travel_time_matrix = network.graph_travel_matrix
    try:
        yield
    finally:
        for mod, fn in orig.items():
            mod.build_travel_time_matrix = fn


def policy_disrupts(policy, scn):
    """What disruptions the policy's planner sees (its information set)."""
    if policy in ("greedy", "ours_blind"):
        return []
    if policy in ("ours_reactive", "ortools_reactive"):
        return _active(scn["timeline"])          # live feed: only currently-active
    if policy in ("ours_anticipatory", "ortools_anticipatory"):
        return _horizon(scn["timeline"])         # schedule feed: active + imminent
    raise ValueError(policy)


def _plan_for(policy, scn, disrupts, ortools_time_s=1):
    if policy == "greedy":
        return solver_baseline.greedy_plan(_req(scn, disrupts))
    if policy.startswith("ours"):
        return solver.plan(_req(scn, disrupts))
    if policy.startswith("ortools"):
        return solver_ortools.solve(_req(scn, disrupts), time_limit_s=ortools_time_s)
    raise ValueError(policy)


def run_study(n: int, ortools_time_s: int = 1) -> dict:
    """Return {policy: {metric: [per-scenario values]}} for stat_on_time, window_rate, weighted_late."""
    scenarios = build_scenarios(n)
    results = {p: {"stat_on_time": [], "window_rate": [], "weighted_late": []} for p in POLICIES}
    with graph_network():
        for scn in scenarios:
            cby = {c["id"]: c for c in scn["couriers"]}
            jby = {j["id"]: j for j in scn["jobs"]}
            for p in POLICIES:
                disrupts = policy_disrupts(p, scn)
                plan = _plan_for(p, scn, disrupts, ortools_time_s)
                if plan is None:
                    continue
                believed = network.closed_bridges_from(disrupts)
                m = groundtruth.realized_eval(plan, cby, jby, scn["timeline"], scn["now"],
                                              believed_closed=believed)
                results[p]["stat_on_time"].append(m["stat_on_time"])
                results[p]["window_rate"].append(m["window_rate"])
                results[p]["weighted_late"].append(m["weighted_late_s"])
    return results


if __name__ == "__main__":
    import sys
    N = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    r = run_study(N)
    print(f"\n{'policy':<22}{'STAT on-time':>14}{'window rate':>14}{'wtd late (s)':>14}")
    for p in POLICIES:
        so = np.mean(r[p]["stat_on_time"]); wr = np.mean(r[p]["window_rate"]); wl = np.mean(r[p]["weighted_late"])
        print(f"{p:<22}{so:>14.3f}{wr:>14.3f}{wl:>14.0f}")
