"""Unit test for the autonomy controller: the closed sense->decide->act loop reacts to
crowdsourced congestion by re-planning around it and dispatching — no server needed."""
from __future__ import annotations
from datetime import datetime, timezone

from autonomy import AutonomyController
from models import OptimizeRequest  # routing/ on sys.path via tests/conftest.py
import solver

NOW = datetime(2026, 6, 6, 9, 0, tzinfo=timezone.utc)
TOWER = (51.5055, -0.0754)


def _solve(jobs, couriers, disruptions, now):
    return solver.plan(OptimizeRequest(jobs=jobs, couriers=couriers, disruptions=disruptions, now=now))


def _job(jid, o, d):
    return {"id": jid, "type": "sample_pickup", "priority": "stat", "cold_chain": True,
            "capacity_units": 1, "status": "new",
            "origin": {"lat": o[0], "lng": o[1]}, "destination": {"lat": d[0], "lng": d[1]},
            "time_window": {"ready_at": NOW.isoformat(), "due_by": NOW.replace(minute=55).isoformat()}}


def _courier(cid, loc):
    return {"id": cid, "name": cid, "capacity": 6, "cold_capable": True, "status": "idle",
            "location": {"lat": loc[0], "lng": loc[1]}, "phone": "x"}


def test_autonomy_loop_reacts_to_congestion():
    ctrl = AutonomyController(_solve)
    couriers = [_courier("s0", (51.498, -0.082)), _courier("n0", (51.5185, -0.061))]
    jobs = [_job("x0", (51.500, -0.078), (51.519, -0.059))]
    # severe jam at Tower revealed by many probes + some invalid pings that must be rejected
    pings = [{"driver_id": f"d{i}", "lat": TOWER[0], "lng": TOWER[1], "speed_mps": 0.4,
              "ts": NOW.isoformat()} for i in range(12)]
    pings += [{"driver_id": "bad", "lat": 0.0, "lng": 0.0, "speed_mps": 99, "ts": NOW.isoformat()}]

    out = ctrl.cycle(jobs=jobs, couriers=couriers, pings=pings, now=NOW)

    assert out["metrics"]["pings_rejected"] >= 1, "out-of-bbox/over-speed ping not rejected"
    assert out["metrics"]["pings_ingested"] == 12
    assert any(d["kind"] == "road_closure" for d in out["disruptions"]), "jam not detected from probes"
    assert out["metrics"]["replans"] == 1
    assert out["metrics"]["dispatches"] >= 1, "no dispatch notification emitted"
    # the served job is in the plan
    assert out["plan"].objective.windows_total >= 1


def test_autonomy_no_pings_no_congestion():
    ctrl = AutonomyController(_solve)
    couriers = [_courier("s0", (51.498, -0.082))]
    jobs = [_job("x0", (51.499, -0.083), (51.497, -0.085))]
    out = ctrl.cycle(jobs=jobs, couriers=couriers, pings=[], now=NOW)
    assert out["metrics"]["congestion_cells"] == 0
    assert out["metrics"]["replans"] == 1
