"""In-process integration tests for the flywheel + solver feasibility logic.

These exercise the pure congestion functions and the routing solvers directly (no sockets,
no subprocesses) so they are fast and complement the cross-process e2e suite. Importing
the orchestrator's FastAPI app in-process is intentionally avoided: `routing/app.py` and
`orchestrator/app.py` (and their `models`/`congestion`/`greedy` siblings) share module
names and collide on sys.path, so the orchestrator HTTP surface is covered cross-process
in tests/e2e/test_unhappy.py instead.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parent.parent.parent
for _p in ("orchestrator", "routing"):
    _sp = str(ROOT / _p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)


# ----------------------------------------------------------------------------- congestion
def test_validate_pings_rejects_out_of_bbox_and_overspeed():
    import congestion as cong  # orchestrator/congestion.py

    pings = [
        {"driver_id": "d1", "lat": 51.5081, "lng": -0.0759, "speed_mps": 1.0},   # ok
        {"driver_id": "d1", "lat": 0.0, "lng": 0.0, "speed_mps": 1.0},           # out of bbox
        {"driver_id": "d1", "lat": 51.51, "lng": -0.10, "speed_mps": 99.0},      # over-speed
        {"driver_id": "", "lat": 51.51, "lng": -0.10, "speed_mps": 1.0},         # no driver_id
    ]
    accepted, rejected = cong.validate_pings(pings)
    assert len(accepted) == 1
    assert len(rejected) == 3


def test_estimate_field_and_disruptions_confidence_gate():
    import congestion as cong

    # 8 jammed probes in one cell -> severe congestion -> a road_closure disruption.
    jammed = [{"driver_id": f"d{i}", "lat": 51.5081, "lng": -0.0759, "speed_mps": 0.3}
              for i in range(8)]
    field = cong.estimate_field(jammed)
    assert len(field["cells"]) == 1
    cell = field["cells"][0]
    assert cell["congestion"] >= cong.BUSY
    assert cell["n_probes"] == 8
    dis = cong.field_to_disruptions(field)
    assert dis and dis[0]["kind"] == "road_closure"

    # A single probe never raises a disruption (confidence gate).
    sparse = cong.estimate_field([{"driver_id": "d1", "lat": 51.5081,
                                   "lng": -0.0759, "speed_mps": 0.3}])
    assert cong.field_to_disruptions(sparse) == []


# ----------------------------------------------------------------------------- solver cold-chain
def _cold_only_warm_courier_request():
    """OptimizeRequest: one cold-chain job, the only courier is NOT cold-capable."""
    from models import OptimizeRequest  # routing/models.py
    return OptimizeRequest(**{
        "couriers": [{"id": "crt-warm", "location": {"lat": 51.50, "lng": -0.12},
                      "status": "idle", "cold_capable": False, "capacity": 6}],
        "jobs": [{"id": "job-cold", "type": "sample_pickup", "priority": "stat",
                  "cold_chain": True, "capacity_units": 1,
                  "origin": {"lat": 51.515, "lng": -0.08},
                  "destination": {"lat": 51.498, "lng": -0.119},
                  "time_window": {"due_by": "2027-01-01T00:00:00Z"}}],
        "now": "2026-06-05T10:00:00Z"})


def test_base_solvers_reject_infeasible_cold():
    """greedy, insertion-construct and ACO all correctly leave an infeasible cold job
    unassigned (the constraint IS honoured by every individual solver)."""
    import solver_baseline, solver_ls, solver_aco
    req = _cold_only_warm_courier_request()
    assert solver_baseline.greedy_plan(req).unassigned == ["job-cold"]
    assert solver_ls.construct(req).unassigned == ["job-cold"]
    assert solver_aco.solve(req).unassigned == ["job-cold"]


def test_portfolio_solver_rejects_infeasible_cold():
    import solver
    req = _cold_only_warm_courier_request()
    plan = solver.plan(req)
    assigned = {s.job_id for r in plan.routes for s in r.stops}
    assert "job-cold" not in assigned, f"cold job assigned to a non-cold courier: {plan}"
    assert "job-cold" in plan.unassigned
