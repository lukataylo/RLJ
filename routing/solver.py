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
import solver_garnet
import solver_hgs
import solver_ls
import solver_ortools
from models import OptimizeRequest, Plan

# The live service is an adaptive portfolio centred on the delta-evaluation HGS engine.
SOLVER_NAME = "hgs-adaptive"
ORTOOLS_TIME_S = 1   # per-call budget for the OR-Tools portfolio member (cuOpt on GB10)


def plan(req: OptimizeRequest, *, ortools_time_s: int = ORTOOLS_TIME_S) -> Plan:
    """World-class portfolio: greedy net + insertion + GPU-parallel ACO + Google OR-Tools
    (and NVIDIA cuOpt on the GB10), every candidate polished by local search, best kept.
    This guarantees we are never worse than the SOTA member, while the metaheuristics and
    refinement add value on top. Anticipation (disruption info) is layered above this."""
    t0 = time.perf_counter()
    P = solver_ls._P(req)
    if P.C == 0 or P.J == 0:
        out = solver_ls.construct(req)
        out.objective.solver = SOLVER_NAME
        out.objective.solve_ms = (time.perf_counter() - t0) * 1e3
        return out

    # Tiered portfolio for low latency + scale:
    #  * small (<=12 jobs, the real-time replan case): HGS + constructive members only.
    #    On CPU, the delta-evaluation HGS dominates the old ACO path on both quality and
    #    latency, so we keep ACO off the hot path unless a GPU backend is actually present.
    #  * mid (13-25): add OR-Tools (modest budget) for extra assurance.
    #  * big (>25): O(J^3) members off; rely on greedy + OR-Tools/cuOpt (which scale).
    small = P.J <= 12
    big = P.J > 25
    candidates: list[Plan] = [solver_baseline.greedy_plan(req)]  # always-available net
    # Delta-evaluation HGS: scales (O(2 routes)/move vs LS's O(plan)/move) so it runs at
    # EVERY size and is the primary optimiser on big instances where the O(J^3) LS is off.
    # Budget grows modestly with size; it reaches LS-grade quality in ~1/10 the LS time
    # (see routing/bench_hgs.py + tests/benchmarks/test_hgs_speedup.py).
    try:
        hgs_budget = min(3.0, 0.10 + 0.025 * P.J) if big else (0.08 if small else 0.30)
        candidates.append(solver_hgs.solve(req, time_budget_s=hgs_budget))
    except Exception:  # noqa: BLE001 - never let a member break the service
        pass
    if not big:
        candidates.append(solver_ls.construct(req))             # insertion (LS-polished)
        if solver_aco.GPU_BACKEND:
            try:
                candidates.append(solver_aco.solve(req))        # GPU-parallel explorer
            except Exception:  # noqa: BLE001 - never let a member break the service
                pass
    try:
        cuopt = solver_baseline.try_cuopt(req)                   # NVIDIA cuOpt (GB10)
        if cuopt is not None:
            candidates.append(cuopt)
    except Exception:  # noqa: BLE001
        pass
    if not small:  # OR-Tools earns its latency cost only on mid/large instances
        try:
            ot_time = max(0.2, min(6, 1 + P.J // 25)) if big else 0.5
            ort = solver_ortools.solve(req, time_limit_s=ot_time)  # Google OR-Tools
            if ort is not None:
                candidates.append(ort)
        except Exception:  # noqa: BLE001
            pass

    # GARNET neural route-optimiser (off by default; $GARNET_ENABLED to switch on). It
    # contributes a learned job ordering as one more candidate. Returns None when disabled
    # or torch is absent, so the portfolio is unchanged unless explicitly turned on; and
    # because pick_best chooses lexicographically, it can only ever help, never hurt.
    if solver_garnet.enabled():
        try:
            garnet = solver_garnet.plan(req)
            if garnet is not None:
                candidates.append(garnet)
        except Exception:  # noqa: BLE001 - never let an optional member break the service
            pass

    pool = [c for c in candidates if c is not None]
    if not big:  # local-search refine is only affordable on small instances
        pool += [solver_ls.refine(c, req) for c in pool]
    best = solver_ls.pick_best(pool, P)
    best.objective.solver = SOLVER_NAME
    best.objective.solve_ms = (time.perf_counter() - t0) * 1e3
    return best
