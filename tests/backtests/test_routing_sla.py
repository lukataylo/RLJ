"""Routing service-level backtests — the external definition of 'routing is verified'.

Replays deterministic, now-anchored scenarios through the real ACO solver and asserts
clinical/operational SLAs. These are the bound tests for the impact + performance claims.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scenarios import build_scenarios, NOW

# routing/ is on sys.path via tests/conftest.py
from models import OptimizeRequest  # noqa: E402
import solver  # noqa: E402  (production portfolio: greedy + insertion + GPU ACO, LS-refined)
import solver_baseline  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "golden.json"
SOLVE_BUDGET_MS = 4000.0   # CPU dev budget; GB10 target is <50ms (CuPy backend)
MAX_TOTAL_TIME_S = 6 * 3600.0
HORIZON_S = 8 * 3600.0


def _req(d) -> OptimizeRequest:
    return OptimizeRequest(**d)


def _solve_all():
    res = []
    for name, d, _ in build_scenarios():
        plan = solver.plan(_req(d))
        res.append((name, d, plan))
    return res


@pytest.fixture(scope="module")
def solved():
    return _solve_all()


def test_stat_window_compliance(solved):
    """STAT samples meet their clinical window ≥95% of the time across scenarios."""
    met = total = 0
    for _name, d, plan in solved:
        prio = {j["id"]: j["priority"] for j in d["jobs"]}
        for route in plan.routes:
            for s in route.stops:
                if s.kind == "dropoff" and prio.get(s.job_id) == "stat":
                    total += 1
                    met += int(bool(s.window_met))
    assert total > 0, "no STAT jobs in scenarios"
    rate = met / total
    assert rate >= 0.95, f"STAT compliance {rate:.0%} ({met}/{total}) < 95%"


def test_beats_greedy(solved):
    """ACO meets at least as many windows as naive greedy on every scenario, and
    strictly more on at least one (otherwise the custom solver earns no credit)."""
    strictly_better = 0
    for _name, d, plan in solved:
        g = solver_baseline.greedy_plan(_req(d))
        aco_met = plan.objective.windows_met
        grd_met = g.objective.windows_met
        assert aco_met >= grd_met, f"{_name}: ACO {aco_met} < greedy {grd_met} windows"
        # ACO must also not strand more jobs than greedy
        assert len(plan.unassigned) <= len(g.unassigned), f"{_name}: ACO stranded more jobs"
        strictly_better += int(aco_met > grd_met or len(plan.unassigned) < len(g.unassigned))
    assert strictly_better >= 1, "ACO never strictly beat greedy — no added value"


def test_eta_plausibility(solved):
    """ETAs/total time are physically plausible — catches the now-misalignment scaling bug."""
    for name, d, plan in solved:
        now = datetime.fromisoformat(d["now"])
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        assert plan.objective.total_time_s < MAX_TOTAL_TIME_S, \
            f"{name}: total_time {plan.objective.total_time_s:.0f}s implausible"
        for route in plan.routes:
            last = now
            for s in route.stops:
                assert s.eta is not None
                eta = s.eta if s.eta.tzinfo else s.eta.replace(tzinfo=timezone.utc)
                delta = (eta - now).total_seconds()
                assert 0 <= delta < HORIZON_S, f"{name}: stop ETA {delta:.0f}s out of horizon"
                assert eta >= last, f"{name}: ETAs not monotonic within route"
                last = eta


def test_solve_budget(solved):
    """Each re-optimization completes within the real-time budget."""
    for name, _d, plan in solved:
        assert plan.objective.solve_ms > 0
        assert plan.objective.solve_ms < SOLVE_BUDGET_MS, \
            f"{name}: solve {plan.objective.solve_ms:.0f}ms over budget {SOLVE_BUDGET_MS:.0f}ms"


def test_golden_no_regression(solved):
    """Objective does not regress vs the committed golden baseline (creates it first run)."""
    current = {name: {"windows_met": plan.objective.windows_met,
                      "unassigned": len(plan.unassigned),
                      "windows_total": plan.objective.windows_total}
               for name, _d, plan in solved}
    if not GOLDEN.exists():
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(current, indent=2))
        pytest.skip("golden baseline created; re-run to enforce")
    golden = json.loads(GOLDEN.read_text())
    for name, cur in current.items():
        if name not in golden:
            continue
        assert cur["windows_met"] >= golden[name]["windows_met"], f"{name}: windows regressed"
        assert cur["unassigned"] <= golden[name]["unassigned"], f"{name}: more unassigned"
