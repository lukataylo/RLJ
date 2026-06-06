"""Shared instance generation + an INDEPENDENT plan re-scorer for the routing benchmark.

The re-scorer deliberately does NOT import any solver's internal scoring. It re-derives the
clinical objective from (a) the emitted ``Plan`` geometry and (b) the request, using the
same public ``traveltime.build_travel_time_matrix`` that every solver consumes. So a solver
cannot win the benchmark by reporting optimistic ETAs or windows_met in its own ``Objective``
— the numbers the benchmark compares are recomputed from first principles, identically for
every solver. This is what makes the head-to-head fair and externally auditable.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from models import OptimizeRequest
from traveltime import build_travel_time_matrix

SERVICE_S = 120.0
PRIORITY_WEIGHT = {"stat": 100.0, "urgent": 10.0, "routine": 1.0}

# Reuse the canonical London geography from the existing backtests.
from scenarios import DEPOTS, LABS, PICKUPS, NOW, _job, _courier, _iso  # noqa: E402


def make_instance(n_jobs: int, n_couriers: int, seed: int,
                  *, cold_frac: float = 0.4, cap: int = 40) -> OptimizeRequest:
    """Deterministic PDPTW instance over real central-London coordinates."""
    rng = np.random.default_rng(seed)
    couriers = [_courier(f"c{k}", DEPOTS[k % len(DEPOTS)], cold=True, cap=cap)
                for k in range(n_couriers)]
    jobs = []
    for j in range(n_jobs):
        o = PICKUPS[int(rng.integers(len(PICKUPS)))]
        d = LABS[int(rng.integers(len(LABS)))]
        prio = ["stat", "urgent", "routine"][int(rng.integers(3))]
        jobs.append(_job(f"j{j}", prio, o, d, NOW, bool(rng.random() < cold_frac)))
    return OptimizeRequest(**{"now": _iso(NOW), "couriers": couriers,
                              "jobs": jobs, "disruptions": []})


def make_instance_mixed(n_jobs: int, n_couriers: int, seed: int) -> OptimizeRequest:
    """Harder instance where cold-chain and capacity ACTUALLY bind: ~1/3 of couriers are
    warm-only and capacities/units vary, so a feasible plan must respect vehicle eligibility.
    Used to stress the feasibility guarantees the basic corpus leaves untested."""
    rng = np.random.default_rng(10_000 + seed)
    couriers = []
    for k in range(n_couriers):
        cold = (k % 3 != 0)            # every 3rd courier is warm-only
        cap = int(rng.integers(2, 6))  # mixed capacities 2..5
        couriers.append(_courier(f"c{k}", DEPOTS[k % len(DEPOTS)], cold=cold, cap=cap))
    jobs = []
    for j in range(n_jobs):
        o = PICKUPS[int(rng.integers(len(PICKUPS)))]
        d = LABS[int(rng.integers(len(LABS)))]
        prio = ["stat", "urgent", "routine"][int(rng.integers(3))]
        units = int(rng.integers(1, 4))           # 1..3 units
        cold = bool(rng.random() < 0.5)
        jobs.append(_job(f"j{j}", prio, o, d, NOW, cold, units=units))
    return OptimizeRequest(**{"now": _iso(NOW), "couriers": couriers,
                              "jobs": jobs, "disruptions": []})


def _job_order(route) -> list[str]:
    """The pairwise job order of a route, taken from its dropoff sequence."""
    seen = []
    for s in route.stops:
        if s.kind == "dropoff" and s.job_id not in seen:
            seen.append(s.job_id)
    return seen


def validate_and_score(req: OptimizeRequest, plan) -> dict:
    """Re-derive the clinical objective from the plan + request, and assert feasibility.

    Returns a dict with stat_met, windows_met, served, unassigned, late_w, total_time, and
    the lexicographic ``clinical_key`` (stat_met, windows_met, -unassigned, -late_w) and the
    ``full_key`` that additionally tie-breaks on -total_time. Raises AssertionError on any
    structural infeasibility (pickup-after-dropoff, cold/capacity violation, double-service).
    """
    now = req.now or NOW
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    couriers = [c for c in req.couriers if c.status != "offline"]
    cour_by_id = {c.id: c for c in couriers}
    jobs = list(req.jobs)
    job_by_id = {j.id: j for j in jobs}

    # node layout identical to the solvers: depots, then pickups, then dropoffs.
    C, J = len(couriers), len(jobs)
    coords = [(c.location.lat, c.location.lng) for c in couriers]
    coords += [(j.origin.lat, j.origin.lng) for j in jobs]
    coords += [(j.destination.lat, j.destination.lng) for j in jobs]
    T = build_travel_time_matrix([c[0] for c in coords], [c[1] for c in coords],
                                 disruptions=req.disruptions)
    depot = {couriers[i].id: i for i in range(C)}
    pick = {jobs[j].id: C + j for j in range(J)}
    drop = {jobs[j].id: C + J + j for j in range(J)}

    def ready_s(job):
        tw = job.time_window
        if not tw or not tw.ready_at:
            return 0.0
        r = tw.ready_at
        r = r.replace(tzinfo=timezone.utc) if r.tzinfo is None else r
        return max(0.0, (r - now).total_seconds())

    def due_s(job):
        tw = job.time_window
        if not tw or not tw.due_by:
            return None
        d = tw.due_by
        d = d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d
        return (d - now).total_seconds()

    served: set[str] = set()
    stat_met = met = 0
    late_w = total = 0.0

    # global structural check: every job is picked up and dropped off at most once across
    # the WHOLE plan (catches within-route double-service, which a per-route dedup hides).
    global_kinds: dict[str, list[str]] = {}
    for route in plan.routes:
        for s in route.stops:
            global_kinds.setdefault(s.job_id, []).append(s.kind)
    for jid, ks in global_kinds.items():
        assert ks.count("pickup") <= 1, f"job {jid} picked up {ks.count('pickup')} times"
        assert ks.count("dropoff") <= 1, f"job {jid} dropped off {ks.count('dropoff')} times"

    for route in plan.routes:
        cid = route.courier_id
        assert cid in cour_by_id, f"route for unknown courier {cid}"
        # structural: every job appears as pickup-before-dropoff, exactly once.
        kinds: dict[str, list[str]] = {}
        for s in route.stops:
            kinds.setdefault(s.job_id, []).append(s.kind)
        order = _job_order(route)
        cold_ok = bool(getattr(cour_by_id[cid], "cold_capable", True))
        cap = float(cour_by_id[cid].capacity)
        node = depot[cid]
        t = 0.0
        for jid in order:
            assert jid not in served, f"job {jid} served by more than one route"
            seq = kinds.get(jid, [])
            assert seq[:2] == ["pickup", "dropoff"], f"job {jid} not pickup-before-dropoff"
            job = job_by_id[jid]
            assert not (job.cold_chain and not cold_ok), f"cold job {jid} on warm van {cid}"
            assert job.capacity_units <= cap, f"job {jid} exceeds {cid} capacity"
            served.add(jid)
            t += T[node, pick[jid]]
            t = max(t, ready_s(job))
            node = pick[jid]
            t += SERVICE_S
            t += T[node, drop[jid]]
            node = drop[jid]
            arrival = t
            due = due_s(job)
            if due is not None:
                if arrival <= due:
                    met += 1
                    if job.priority == "stat":
                        stat_met += 1
                else:
                    late_w += (arrival - due) * PRIORITY_WEIGHT.get(job.priority, 1.0)
            t += SERVICE_S
        total += t

    unassigned = [j.id for j in jobs if j.id not in served]
    clinical_key = (stat_met, met, -len(unassigned), -late_w)
    full_key = (stat_met, met, -len(unassigned), -late_w, -total)
    return {
        "stat_met": stat_met, "windows_met": met, "served": len(served),
        "unassigned": len(unassigned), "late_w": late_w, "total_time": total,
        "clinical_key": clinical_key, "full_key": full_key,
        "windows_total": sum(1 for j in jobs if due_s(j) is not None),
        "stat_total": sum(1 for j in jobs if j.priority == "stat" and due_s(j) is not None),
    }
