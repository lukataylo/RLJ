"""Deterministic, now-anchored backtest scenarios for the router.

Self-contained (does not depend on the data stream) so routing can be verified in
isolation. Windows are anchored to the scenario `now`, which is the key correctness
property: a misaligned `now` is exactly the class of bug the eta-plausibility backtest
catches. Coordinates are real central-London points.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import numpy as np

NOW = datetime(2026, 6, 6, 9, 0, 0, tzinfo=timezone.utc)

# Real-ish London locations (lat, lng, name)
DEPOTS = [
    (51.5079, -0.0877, "London Bridge depot"),
    (51.5246, -0.1340, "Euston depot"),
    (51.5155, -0.0922, "Liverpool St depot"),
    (51.4894, -0.1110, "Kennington depot"),
]
LABS = [
    (51.4980, -0.1188, "St Thomas' lab"),
    (51.5030, -0.0884, "Guy's lab"),
    (51.5246, -0.1357, "UCLH lab"),
    (51.5685, -0.0640, "Whittington lab"),
]
PICKUPS = [
    (51.5290, -0.1225, "Somers Town surgery"),
    (51.5185, -0.0731, "Royal London pharmacy"),
    (51.5410, -0.1430, "Camden clinic"),
    (51.4769, -0.1110, "Oval health centre"),
    (51.5141, -0.0590, "Bethnal Green surgery"),
    (51.5331, -0.1050, "Islington clinic"),
    (51.4925, -0.1465, "Pimlico surgery"),
    (51.5203, -0.1050, "Clerkenwell pharmacy"),
]
PRIORITIES = ["stat", "urgent", "routine"]
# clinical window from `now` per priority (minutes)
WINDOW_MIN = {"stat": 70, "urgent": 130, "routine": 190}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _job(jid, prio, origin, dest, now, cold, units=1):
    return {
        "id": jid,
        "type": "sample_pickup" if cold else "med_delivery",
        "priority": prio,
        "cold_chain": cold,
        "capacity_units": units,
        "status": "new",
        "origin": {"lat": origin[0], "lng": origin[1], "name": origin[2]},
        "destination": {"lat": dest[0], "lng": dest[1], "name": dest[2]},
        "time_window": {"ready_at": _iso(now), "due_by": _iso(now + timedelta(minutes=WINDOW_MIN[prio]))},
    }


def _courier(cid, depot, cold=True, cap=6):
    return {"id": cid, "name": cid, "capacity": cap, "cold_capable": cold, "status": "idle",
            "location": {"lat": depot[0], "lng": depot[1], "name": depot[2]},
            "phone": "+44700900000"}


def build_scenarios(now: datetime = NOW):
    """Return [(name, request_dict, mix)] across a spread of sizes/pressures.

    Each scenario is sized so STAT jobs are feasible with the given fleet — the SLA is
    'meet the clinical window', which a correct solver must achieve ≥95% of the time.
    """
    out = []
    for si, (n_jobs, n_couriers) in enumerate([(5, 3), (8, 3), (10, 4), (12, 4), (6, 2)]):
        rng = np.random.default_rng(100 + si)
        couriers = [_courier(f"crt-{k+1}", DEPOTS[k % len(DEPOTS)], cold=(k % 3 != 2))
                    for k in range(n_couriers)]
        jobs = []
        for j in range(n_jobs):
            # ~20% stat, 30% urgent, 50% routine, deterministic
            roll = rng.random()
            prio = "stat" if roll < 0.2 else ("urgent" if roll < 0.5 else "routine")
            cold = bool(rng.random() < 0.7)
            origin = PICKUPS[int(rng.integers(len(PICKUPS)))]
            dest = LABS[int(rng.integers(len(LABS)))]
            jobs.append(_job(f"job-{j+1}", prio, origin, dest, now, cold))
        out.append((f"scn-{si}-{n_jobs}j-{n_couriers}c",
                    {"now": _iso(now), "couriers": couriers, "jobs": jobs},
                    None))
    return out
