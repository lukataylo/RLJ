"""Ground-truth temporal evaluator for the counterfactual backtest.

Methodology: each policy plans under its own information set (which disruptions it can
see), but EVERY plan is replayed against the same realised timeline on the shared
river-barrier network (network.py). When a courier reaches a bridge that is shut at that
moment, it detours to the nearest open crossing — so a plan that routed over a bridge it
didn't know would close pays the unbudgeted detour, and cascades. This is what makes the
comparison fair: plans are scored by reality, not by their own optimistic ETAs.

A timeline closure is {kind, geometry:[{lat,lng}], start_s, end_s} in seconds relative to
`now`. Bridge closures (road_closure on a bridge) remove that crossing while active;
other closures act as traffic zones.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional

import network

SERVICE_S = 120.0
PRIORITY_WEIGHT = {"stat": 100.0, "urgent": 10.0, "routine": 1.0}


def _secs(now: datetime, dt) -> Optional[float]:
    if dt is None:
        return None
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt - now).total_seconds()


def _active(timeline, t):
    return [c for c in timeline if c["start_s"] <= t < c["end_s"]]


def realized_eval(plan, couriers_by_id: dict, jobs_by_id: dict, timeline: list,
                  now: datetime, believed_closed=frozenset()) -> dict:
    """`believed_closed` = the bridges the PLANNER thought were shut. If the plan routed
    over a bridge that is actually closed when the courier arrives, it pays a backtrack to
    the nearest open crossing — the operational cost of not anticipating the closure."""
    realized_arrival: dict[str, float] = {}

    for route in plan.routes:
        courier = couriers_by_id.get(route.courier_id)
        if courier is None or not route.stops:
            continue
        prev = (courier["location"]["lat"], courier["location"]["lng"])
        t = 0.0
        for stop in route.stops:
            loc = (stop.location.lat, stop.location.lng)
            active = _active(timeline, t)
            closed = network.closed_bridges_from(active)
            zones = network.traffic_zones_from(active)
            leg = network.travel_time(prev, loc, closed, zones)
            # backtrack penalty: planner intended a bridge that is actually shut now
            intended = network.chosen_bridge(prev, loc, believed_closed)
            if intended is not None and intended in closed:
                ipos = network.BRIDGE_POS[intended]
                opos = network.nearest_open_bridge_pos(ipos, closed)
                leg += 2 * network._hav(ipos, opos) * network.CIRCUITY / network.SPEED_MPS
            t += leg
            job = jobs_by_id.get(stop.job_id)
            if stop.kind == "pickup":
                ready = _secs(now, (job.get("time_window") or {}).get("ready_at")) if job else None
                if ready is not None:
                    t = max(t, ready)
            else:
                realized_arrival[stop.job_id] = t
            t += SERVICE_S
            prev = loc

    stat_met = stat_tot = win_met = win_tot = 0
    weighted_late = 0.0
    for jid, job in jobs_by_id.items():
        due = _secs(now, (job.get("time_window") or {}).get("due_by"))
        if due is None:
            continue
        win_tot += 1
        is_stat = job.get("priority") == "stat"
        stat_tot += int(is_stat)
        arr = realized_arrival.get(jid, float("inf"))
        met = arr <= due
        win_met += int(met)
        stat_met += int(met and is_stat)
        if not met:
            lateness = (arr - due) if arr != float("inf") else 3600.0
            weighted_late += lateness * PRIORITY_WEIGHT.get(job.get("priority"), 1.0)

    return {
        "stat_on_time": (stat_met / stat_tot) if stat_tot else 1.0,
        "stat_met": stat_met, "stat_total": stat_tot,
        "windows_met": win_met, "windows_total": win_tot,
        "window_rate": (win_met / win_tot) if win_tot else 1.0,
        "weighted_late_s": weighted_late,
    }
