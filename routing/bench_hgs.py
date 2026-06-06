"""Head-to-head benchmark: delta-evaluation HGS vs the current production local search.

Claim under test (the honest one — see RESEARCH.md): the delta-evaluation engine reaches
**equal-or-better clinical solution quality in ~1/10th the wall-clock time** of the existing
``solver_ls`` insertion+refinement solver (the production member that re-simulates the whole
plan per move and is hard-gated off above ~25 jobs). Quality and time are both recomputed
from the emitted plans by an INDEPENDENT re-scorer (``instances.validate_and_score``); a
solver's self-reported objective is never trusted.

Run:
    ./.venv/bin/python -m pytest tests/benchmarks/test_hgs_speedup.py -q -s   # gated
    ./.venv/bin/python routing/bench_hgs.py                                   # table
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# allow `python routing/bench_hgs.py` from the repo root
_ROOT = Path(__file__).resolve().parent.parent
for _p in ("routing", "tests/backtests", "tests/benchmarks"):
    sys.path.insert(0, str(_ROOT / _p))

import solver_hgs  # noqa: E402
import solver_ls  # noqa: E402
from instances import make_instance, validate_and_score  # noqa: E402

# Production-scale corpus: the regime where the O(J^3) production LS is slow or gated off.
CORPUS = [
    (30, 6, 1), (30, 6, 2),
    (40, 8, 7), (40, 8, 11),
    (50, 8, 3), (50, 10, 5),
    (60, 10, 7), (60, 10, 13),
    (80, 12, 3), (80, 12, 17),
    (100, 15, 5),
]
BUDGET_RATIO = 0.10  # HGS gets one-tenth of the LS wall-clock it must match


def run_one(n_jobs: int, n_couriers: int, seed: int, ratio: float = BUDGET_RATIO) -> dict:
    """Run LS to completion, then HGS at ``ratio`` of LS's wall time; rescore both."""
    req = make_instance(n_jobs, n_couriers, seed)

    t0 = time.perf_counter()
    ls_plan = solver_ls.construct(req)
    t_ls = time.perf_counter() - t0
    ls = validate_and_score(req, ls_plan)

    budget = max(0.03, t_ls * ratio)
    t0 = time.perf_counter()
    hgs_plan = solver_hgs.solve(req, time_budget_s=budget)
    t_hgs = time.perf_counter() - t0
    hgs = validate_and_score(req, hgs_plan)

    clinical_win = hgs["clinical_key"] >= ls["clinical_key"]
    full_win = hgs["full_key"] >= ls["full_key"]
    return {
        "n_jobs": n_jobs, "n_couriers": n_couriers, "seed": seed,
        "t_ls": t_ls, "t_hgs": t_hgs, "speedup": t_ls / t_hgs if t_hgs else float("inf"),
        "ls": ls, "hgs": hgs, "clinical_win": clinical_win, "full_win": full_win,
    }


def run_corpus(corpus=CORPUS, ratio: float = BUDGET_RATIO) -> list[dict]:
    return [run_one(nj, nc, s, ratio) for (nj, nc, s) in corpus]


def main() -> int:
    rows = run_corpus()
    hdr = ("jobs", "cour", "seed", "t_ls(ms)", "t_hgs(ms)", "speed",
           "LS clin", "HGS clin", "clin>=", "full>=")
    w = [5, 5, 5, 10, 10, 7, 18, 18, 7, 7]
    print("\nHGS (delta-eval) vs production LS — independently rescored\n")
    print("  ".join(h.ljust(x) for h, x in zip(hdr, w)))
    print("-" * 110)
    for r in rows:
        lk, hk = r["ls"], r["hgs"]
        lcl = f"({lk['stat_met']},{lk['windows_met']},-{lk['unassigned']},L{lk['late_w']:.0f})"
        hcl = f"({hk['stat_met']},{hk['windows_met']},-{hk['unassigned']},L{hk['late_w']:.0f})"
        cells = [str(r["n_jobs"]), str(r["n_couriers"]), str(r["seed"]),
                 f"{r['t_ls']*1e3:.0f}", f"{r['t_hgs']*1e3:.0f}", f"{r['speedup']:.1f}x",
                 lcl, hcl, "Y" if r["clinical_win"] else "n",
                 "Y" if r["full_win"] else "n"]
        print("  ".join(c.ljust(x) for c, x in zip(cells, w)))

    import statistics
    speeds = sorted(r["speedup"] for r in rows)
    clin = sum(r["clinical_win"] for r in rows)
    full = sum(r["full_win"] for r in rows)
    n = len(rows)
    print("-" * 110)
    print(f"\nBudget ratio: HGS time = {BUDGET_RATIO:.0%} of LS time (so a clinical win == "
          f">= {1/BUDGET_RATIO:.0f}x faster at equal-or-better quality)")
    print(f"median wall speedup (LS / HGS):           {statistics.median(speeds):.1f}x")
    print(f"clinical equal-or-better (stat/met/unassigned/lateness): {clin}/{n} "
          f"instances ({clin/n:.0%})")
    print(f"full key equal-or-better (+ total-time tiebreak):        {full}/{n} "
          f"instances ({full/n:.0%})")
    agg_ls = sum(r['ls']['windows_met'] for r in rows)
    agg_hgs = sum(r['hgs']['windows_met'] for r in rows)
    agg_ls_stat = sum(r['ls']['stat_met'] for r in rows)
    agg_hgs_stat = sum(r['hgs']['stat_met'] for r in rows)
    print(f"aggregate STAT on-time:   HGS {agg_hgs_stat}  vs  LS {agg_ls_stat}")
    print(f"aggregate windows met:    HGS {agg_hgs}  vs  LS {agg_ls}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
