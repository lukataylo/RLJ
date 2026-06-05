"""Flywheel research backtest: does crowdsourced driver data improve clinical routing,
and does the benefit scale with participation (network effect)?

An UNSCHEDULED jam shuts a river crossing (not in any published schedule, so only live
probes can reveal it). We vary the number of contributing drivers K; their GPS reveals the
jam once enough of them are stuck there (confidence gate in congestion.field_to_disruptions),
which lets the dispatcher route medical couriers around it. We score realised STAT on-time
on the common ground-truth timeline and test that K=many significantly beats K=0.
"""
from __future__ import annotations
from datetime import datetime, timezone

import numpy as np
import pytest
from scipy import stats

import network
import groundtruth
from congestion import estimate_field, field_to_disruptions
from models import OptimizeRequest
import solver
from study import graph_network

pytestmark = pytest.mark.slow

NOW = datetime(2026, 6, 6, 9, 0, tzinfo=timezone.utc)
TOWER = (51.5055, -0.0754)
SPICK = (51.5000, -0.0780)
NLAB = (51.5190, -0.0590)
DEP_N = (51.5185, -0.0610)
DEP_S = (51.4980, -0.0820)
K_LEVELS = [0, 8, 40]
S_SCENARIOS = 16
ALPHA = 0.05


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def _scenario(seed):
    rng = np.random.default_rng(900 + seed)
    couriers = [
        {"id": "n0", "name": "n0", "capacity": 6, "cold_capable": True, "status": "idle",
         "location": {"lat": DEP_N[0], "lng": DEP_N[1]}, "phone": "x"},
        {"id": "s0", "name": "s0", "capacity": 6, "cold_capable": True, "status": "idle",
         "location": {"lat": DEP_S[0], "lng": DEP_S[1]}, "phone": "x"},
        {"id": "s1", "name": "s1", "capacity": 6, "cold_capable": True, "status": "idle",
         "location": {"lat": DEP_S[0] + 0.01, "lng": DEP_S[1] - 0.01}, "phone": "x"},
    ]
    jobs = []
    for k in range(3):  # cross-river STAT jobs that naturally use Tower Bridge
        o = (SPICK[0] + rng.uniform(-0.003, 0.003), SPICK[1] + rng.uniform(-0.003, 0.003))
        d = (NLAB[0] + rng.uniform(-0.003, 0.003), NLAB[1] + rng.uniform(-0.003, 0.003))
        jobs.append({"id": f"x{k}", "type": "sample_pickup", "priority": "stat",
                     "cold_chain": True, "capacity_units": 1, "status": "new",
                     "origin": {"lat": o[0], "lng": o[1]}, "destination": {"lat": d[0], "lng": d[1]},
                     "time_window": {"ready_at": _iso(NOW),
                                     "due_by": _iso(NOW.replace(minute=55))}})
    # unscheduled jam at Tower, active across the horizon (only probes can reveal it)
    timeline = [{"kind": "road_closure", "geometry": [{"lat": TOWER[0], "lng": TOWER[1]}],
                 "start_s": -600, "end_s": 7200}]
    return couriers, jobs, timeline


def _probes(seed, k):
    """K drivers, ~60% currently stuck in the Tower jam (1 probe each)."""
    rng = np.random.default_rng(7000 + seed * 17 + k)
    pings = []
    for i in range(k):
        if rng.random() < 0.6:  # in the jam
            pings.append({"driver_id": f"d{i}", "lat": TOWER[0] + rng.uniform(-0.0015, 0.0015),
                          "lng": TOWER[1] + rng.uniform(-0.0015, 0.0015), "speed_mps": 0.4,
                          "ts": _iso(NOW)})
        else:  # free-flowing elsewhere
            pings.append({"driver_id": f"d{i}", "lat": 51.515 + rng.uniform(-0.02, 0.02),
                          "lng": -0.12 + rng.uniform(-0.03, 0.03), "speed_mps": 7.0, "ts": _iso(NOW)})
    return pings


def _run():
    by_k = {k: [] for k in K_LEVELS}
    with graph_network():
        for s in range(S_SCENARIOS):
            couriers, jobs, timeline = _scenario(s)
            cby = {c["id"]: c for c in couriers}
            jby = {j["id"]: j for j in jobs}
            for k in K_LEVELS:
                field = estimate_field(_probes(s, k), NOW)
                detected = field_to_disruptions(field)             # confidence-gated
                believed = network.closed_bridges_from(detected)
                req = OptimizeRequest(now=NOW, couriers=couriers, jobs=jobs, disruptions=detected)
                plan = solver.plan(req)
                m = groundtruth.realized_eval(plan, cby, jby, timeline, NOW, believed_closed=believed)
                by_k[k].append(m["stat_on_time"])
    return by_k


@pytest.fixture(scope="module")
def flywheel():
    return _run()


def test_more_drivers_help(flywheel):
    """Many contributing drivers significantly beat zero (the flywheel has value)."""
    a = np.array(flywheel[K_LEVELS[-1]])
    b = np.array(flywheel[K_LEVELS[0]])
    assert a.mean() > b.mean(), f"K={K_LEVELS[-1]} mean {a.mean():.3f} !> K=0 {b.mean():.3f}"
    diffs = a - b
    if np.any(diffs != 0):
        _stat, p = stats.wilcoxon(a, b, alternative="greater", zero_method="wilcox")
        assert p < ALPHA, f"flywheel benefit not significant: p={p:.4f}"


def test_benefit_is_monotone(flywheel):
    """STAT on-time is non-decreasing in driver participation (network effect)."""
    means = [np.mean(flywheel[k]) for k in K_LEVELS]
    for lo, hi in zip(means, means[1:]):
        assert hi >= lo - 1e-9, f"non-monotone flywheel: {means}"
