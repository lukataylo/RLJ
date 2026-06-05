"""Demand DQ — schema conformance + sane, priority-ordered time windows."""
from __future__ import annotations

from datetime import datetime
from statistics import median

import demand as demand_mod
import quality

NOW = demand_mod.SNAPSHOT_NOW


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _window_minutes(job: dict) -> float:
    tw = job["time_window"]
    return (_parse(tw["due_by"]) - _parse(tw["ready_at"])).total_seconds() / 60.0


def test_demand_schema_and_windows(validate_entity):
    jobs = demand_mod.generate_demand(n=40, seed=7, now=NOW)

    # 1. every job validates against $defs/DeliveryJob (shared fixture).
    for job in jobs:
        validate_entity("DeliveryJob", job)

    # also run the pipeline's own validator (same source of truth as build.py).
    quality.validate_demand(jobs, now=NOW, horizon_hours=6)

    now_dt = _parse(NOW)
    horizon = now_dt.timestamp() + 6 * 3600
    for job in jobs:
        tw = job["time_window"]
        ra, db = _parse(tw["ready_at"]), _parse(tw["due_by"])
        # due_by strictly after ready_at
        assert db > ra, f"{job['id']}: due_by not after ready_at"
        # everything inside the next ~6h of the scenario clock
        assert ra.timestamp() >= now_dt.timestamp() - 300
        assert db.timestamp() <= horizon

    # 2. stat windows tighter than urgent tighter than routine (aggregate).
    by_prio: dict[str, list[float]] = {"stat": [], "urgent": [], "routine": []}
    for job in jobs:
        by_prio[job["priority"]].append(_window_minutes(job))
    assert all(by_prio[p] for p in by_prio), f"missing a priority class: {by_prio}"
    assert median(by_prio["stat"]) < median(by_prio["urgent"]) < median(by_prio["routine"])
    # stat windows are genuinely tight
    assert max(by_prio["stat"]) <= 75

    # determinism: same seed -> identical output
    again = demand_mod.generate_demand(n=40, seed=7, now=NOW)
    assert again == jobs
