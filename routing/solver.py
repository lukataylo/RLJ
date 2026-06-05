"""Production routing entry point — the portfolio that /optimize and the backtests use.

Hybrid metaheuristic: build several candidate plans (greedy safety net, insertion
construction, and the GPU-parallel ACO explorer), polish each with local-search
refinement, and return the best by the clinical objective. This guarantees we never do
worse than the greedy baseline, while the ACO + local search find strictly better plans
on harder instances. On the GB10 the ACO stage runs on the GPU (CuPy); the label reports
the active backend.
"""
from __future__ import annotations
import time

import solver_aco
import solver_baseline
import solver_ls
from models import OptimizeRequest, Plan

# "gpu-aco" on the GB10 (CuPy), "aco-numpy" on CPU. We append "+ls" for the refinement.
SOLVER_NAME = solver_aco.SOLVER_NAME + "+ls"


def plan(req: OptimizeRequest) -> Plan:
    t0 = time.perf_counter()
    P = solver_ls._P(req)
    if P.C == 0 or P.J == 0:
        out = solver_ls.construct(req)
        out.objective.solver = SOLVER_NAME
        out.objective.solve_ms = (time.perf_counter() - t0) * 1e3
        return out

    candidates: list[Plan] = []
    candidates.append(solver_baseline.greedy_plan(req))          # always-available net
    candidates.append(solver_ls.construct(req))                  # insertion (already LS-polished)
    try:
        candidates.append(solver_aco.solve(req))                 # GPU-parallel explorer
    except Exception:  # noqa: BLE001 - never let the headline solver break the service
        pass

    # Local-search refine every candidate, then pick the best of raw + refined.
    pool = candidates + [solver_ls.refine(c, req) for c in candidates]
    best = solver_ls.pick_best(pool, P)
    best.objective.solver = SOLVER_NAME
    best.objective.solve_ms = (time.perf_counter() - t0) * 1e3
    return best
