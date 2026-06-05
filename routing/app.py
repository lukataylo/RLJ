"""Routing service — implements the `/optimize` contract (contracts/api.md).

FastAPI app on :8100 with:
    GET  /healthz  -> {status, solver}
    POST /optimize -> OptimizeResponse {plan: Plan}

At startup it picks the best available solver and reports it on /healthz and in
every Plan.objective.solver. Solve uses the fallback ladder (custom GPU ACO -> cuOpt ->
OR-Tools -> greedy): the primary is tried first and any failure drops to the next rung,
so a Plan is *always* returned. Runs on this Mac with numpy only (no GPU).

Run:
    uvicorn app:app --reload --port 8100
Test:
    curl -s -X POST http://localhost:8100/optimize \
      -H 'content-type: application/json' \
      -d @../contracts/samples/optimize_request.json | jq .plan.objective
"""
from __future__ import annotations

import logging

from fastapi import FastAPI

import solver_aco
import solver_baseline
from models import OptimizeRequest, OptimizeResponse, Plan

log = logging.getLogger("routing")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="RLJ Routing Service", version="0.1.0")


def _select_solver() -> str:
    """Decide the headline solver for /healthz. ACO is always available; its label
    reflects whether the CuPy GPU backend is active (gpu-aco) or numpy (aco-numpy)."""
    return solver_aco.SOLVER_NAME


SELECTED_SOLVER = _select_solver()


def _solve(req: OptimizeRequest) -> Plan:
    """Run the fallback ladder. Always returns a valid Plan."""
    # Rung 1 — custom GPU/numpy ACO (headline).
    try:
        return solver_aco.solve(req)
    except Exception:  # noqa: BLE001
        log.exception("ACO solver failed; descending the fallback ladder")

    # Rung 2 — NVIDIA cuOpt (GPU, optional).
    try:
        plan = solver_baseline.try_cuopt(req)
        if plan is not None:
            return plan
    except Exception:  # noqa: BLE001
        log.exception("cuOpt fallback failed")

    # Rung 3 — OR-Tools (optional).
    try:
        plan = solver_baseline.try_ortools(req)
        if plan is not None:
            return plan
    except Exception:  # noqa: BLE001
        log.exception("OR-Tools fallback failed")

    # Rung 4 — greedy (always available safety net).
    return solver_baseline.greedy_plan(req)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "solver": SELECTED_SOLVER}


@app.post("/optimize", response_model=OptimizeResponse, response_model_exclude_none=True)
def optimize(req: OptimizeRequest) -> OptimizeResponse:
    # exclude_none: optional fields we don't set (e.g. a pickup's window_met, which has
    # no clinical-window meaning) are omitted rather than emitted as null. The schema
    # types those fields as non-nullable-when-present, so omission keeps us valid while
    # still "strict in what we emit".
    plan = _solve(req)
    return OptimizeResponse(plan=plan)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8100)
