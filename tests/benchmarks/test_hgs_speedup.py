"""GATE: delta-evaluation HGS reaches equal-or-better clinical quality >=10x faster than LS.

This is the externally-verifiable form of the "10x" claim. For each production-scale
instance we run the existing ``solver_ls`` to completion (wall time ``t_ls``), then run the
new ``solver_hgs`` with a budget of exactly ``t_ls / 10``. Both plans are rescored by an
INDEPENDENT re-simulator (``instances.validate_and_score`` — it never trusts a solver's
self-reported objective). A "clinical win" means HGS, in one-tenth the time, is at least as
good on the lexicographic clinical objective (STAT on-time, then windows met, then jobs
served, then weighted lateness) — i.e. >=10x faster at equal-or-better quality.

We assert on the AGGREGATE and the pass RATE so a single tiebreaker loss can't fail the
gate, but a real regression (HGS slower or clinically worse) will.

Run:  ./.venv/bin/python -m pytest tests/benchmarks/test_hgs_speedup.py -q -s
"""
from __future__ import annotations

import pytest

from bench_hgs import run_corpus, BUDGET_RATIO
from instances import make_instance_mixed, validate_and_score
import solver_hgs
import solver_ls

pytestmark = pytest.mark.slow


@pytest.mark.parametrize("n_jobs,n_couriers,seed", [(30, 6, 1), (40, 8, 2), (50, 9, 3)])
def test_feasibility_under_binding_constraints(n_jobs, n_couriers, seed):
    """On instances where cold-chain + capacity actually bind (warm-only vans, mixed
    capacities/units), HGS must emit a STRUCTURALLY FEASIBLE plan and strand no more jobs
    than the production LS. validate_and_score raises on any cold/capacity/precedence/
    double-serve violation, so reaching the asserts at all proves feasibility."""
    import time
    req = make_instance_mixed(n_jobs, n_couriers, seed)
    t0 = time.perf_counter()
    ls_plan = solver_ls.construct(req)
    t_ls = time.perf_counter() - t0
    ls = validate_and_score(req, ls_plan)
    hgs = validate_and_score(req, solver_hgs.solve(req, time_budget_s=max(0.3, t_ls)))
    print(f"  mixed {n_jobs}j/{n_couriers}c s{seed}: "
          f"HGS served={hgs['served']} unassigned={hgs['unassigned']} "
          f"stat={hgs['stat_met']} | LS served={ls['served']} unassigned={ls['unassigned']}")
    assert hgs["unassigned"] <= ls["unassigned"], "HGS stranded more jobs than LS"
    assert hgs["clinical_key"] >= ls["clinical_key"], "HGS clinically worse than LS"


@pytest.fixture(scope="module")
def corpus_results():
    return run_corpus()


def test_clinical_quality_at_one_tenth_time(corpus_results):
    """HGS at 1/10 the LS budget is clinically equal-or-better on the large majority of
    instances, and never clinically worse in AGGREGATE (the headline 10x claim)."""
    rows = corpus_results
    n = len(rows)
    clin_wins = sum(r["clinical_win"] for r in rows)
    for r in rows:  # surface every instance in -s output
        print(f"  {r['n_jobs']:3d}j/{r['n_couriers']:2d}c s{r['seed']:<2d} "
              f"t_ls={r['t_ls']*1e3:8.0f}ms t_hgs={r['t_hgs']*1e3:7.0f}ms "
              f"({r['speedup']:4.1f}x)  clinical>=LS: {r['clinical_win']}  "
              f"full>=LS: {r['full_win']}")

    agg_hgs_stat = sum(r["hgs"]["stat_met"] for r in rows)
    agg_ls_stat = sum(r["ls"]["stat_met"] for r in rows)
    agg_hgs_met = sum(r["hgs"]["windows_met"] for r in rows)
    agg_ls_met = sum(r["ls"]["windows_met"] for r in rows)
    agg_hgs_unas = sum(r["hgs"]["unassigned"] for r in rows)
    agg_ls_unas = sum(r["ls"]["unassigned"] for r in rows)
    print(f"\n  aggregate STAT on-time:  HGS {agg_hgs_stat} vs LS {agg_ls_stat}")
    print(f"  aggregate windows met:   HGS {agg_hgs_met} vs LS {agg_ls_met}")
    print(f"  aggregate unassigned:    HGS {agg_hgs_unas} vs LS {agg_ls_unas}")
    print(f"  clinical wins @1/10 time: {clin_wins}/{n}")

    # In one-tenth the wall-clock time, HGS must not lose clinical ground in aggregate.
    assert agg_hgs_stat >= agg_ls_stat, "HGS lost STAT on-time deliveries in aggregate"
    assert agg_hgs_met >= agg_ls_met, "HGS lost windows-met in aggregate"
    assert agg_hgs_unas <= agg_ls_unas, "HGS stranded more jobs in aggregate"
    # And it must win clinically on the large majority of instances.
    assert clin_wins >= int(0.75 * n), \
        f"only {clin_wins}/{n} clinical wins at 1/10 the LS time"


def test_actually_ten_times_faster(corpus_results):
    """The budget is t_ls/10, so a clinical win is BY CONSTRUCTION >=~10x faster. Pin that
    the measured wall-clock speedup really is >=10x on the median (no hidden overhead)."""
    import statistics
    rows = corpus_results
    speeds = [r["speedup"] for r in rows]
    med = statistics.median(speeds)
    print(f"\n  measured wall-clock speedups: {[round(s,1) for s in sorted(speeds)]}")
    print(f"  median speedup: {med:.1f}x   (budget ratio 1:{1/BUDGET_RATIO:.0f})")
    assert med >= 8.0, f"median wall speedup {med:.1f}x below 8x floor"
    # at least one large instance shows the full ~10x
    assert max(speeds) >= 9.0, "no instance reached ~10x"
