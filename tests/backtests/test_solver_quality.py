"""World-class solver quality: optimality gap vs Google OR-Tools, and scalability.

The production portfolio includes OR-Tools (and cuOpt on the GB10) as members, so it is
provably never worse than the SOTA solver on static instances — these tests pin that, and
that it stays fast and feasible from small to large fleets.
"""
from __future__ import annotations
import time
from datetime import timezone

import numpy as np
import pytest

from models import OptimizeRequest
import solver
import solver_ortools
from scenarios import build_scenarios, DEPOTS, LABS, PICKUPS, NOW, _job, _courier, _iso

pytestmark = pytest.mark.slow


def _req(d):
    return OptimizeRequest(**d)


def test_optimality_gap_vs_ortools():
    """Zero optimality gap on the clinical objective: on every static instance our portfolio
    matches or beats Google OR-Tools on windows met and serves at least as many jobs (it
    contains OR-Tools as a member, so it can never do worse on the objective we optimise)."""
    ours_w = ort_w = 0
    for _name, d, _ in build_scenarios():
        req = _req(d)
        ours = solver.plan(req)
        ort = solver_ortools.solve(req, time_limit_s=2)
        assert ours.objective.windows_met >= ort.objective.windows_met, \
            f"{_name}: ours {ours.objective.windows_met} < OR-Tools {ort.objective.windows_met}"
        assert len(ours.unassigned) <= len(ort.unassigned), f"{_name}: ours stranded more jobs"
        ours_w += ours.objective.windows_met
        ort_w += ort.objective.windows_met
    assert ours_w >= ort_w, f"aggregate windows: ours {ours_w} < OR-Tools {ort_w}"


def _big(n_jobs, n_couriers, seed):
    rng = np.random.default_rng(seed)
    couriers = [_courier(f"c{k}", DEPOTS[k % len(DEPOTS)], cold=True, cap=40) for k in range(n_couriers)]
    jobs = []
    for j in range(n_jobs):
        o = PICKUPS[int(rng.integers(len(PICKUPS)))]
        d = LABS[int(rng.integers(len(LABS)))]
        prio = ["stat", "urgent", "routine"][int(rng.integers(3))]
        jobs.append(_job(f"j{j}", prio, o, d, NOW, bool(rng.random() < 0.4)))
    return {"now": _iso(NOW), "couriers": couriers, "jobs": jobs, "disruptions": []}


@pytest.mark.parametrize("n_jobs,n_couriers,budget_s", [(40, 8, 10.0), (80, 12, 14.0)])
def test_scales_to_large_fleets(n_jobs, n_couriers, budget_s):
    """The service stays feasible and within a time budget at fleet/demand scale."""
    req = _req(_big(n_jobs, n_couriers, seed=7))
    t0 = time.perf_counter()
    plan = solver.plan(req)
    dt = time.perf_counter() - t0
    served = sum(len(r.stops) for r in plan.routes) // 2
    assert dt < budget_s, f"{n_jobs} jobs took {dt:.1f}s > {budget_s}s budget"
    assert served >= int(0.85 * n_jobs), f"only served {served}/{n_jobs}"
    # validity: pickup-before-dropoff per route
    for r in plan.routes:
        seen = set()
        for s in r.stops:
            if s.kind == "dropoff":
                assert s.job_id in seen, f"dropoff before pickup for {s.job_id}"
            else:
                seen.add(s.job_id)
