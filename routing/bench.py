"""Benchmark harness — produces the demo's speedup numbers.

Times each available solver on a payload (defaults to
``../contracts/samples/optimize_request.json``) and prints a comparison table:

    solver | windows_met | total_time_s | solve_ms

This is what you read out loud at the demo: "the custom ACO matches greedy on windows
met and, on the GB10, returns in <X ms>". On this Mac the ACO label is ``aco-numpy``;
on the DGX Spark the same code reports ``gpu-aco``.

Run:
    python bench.py
    python bench.py /path/to/another_request.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import solver_aco
import solver_baseline
from models import OptimizeRequest

DEFAULT_PAYLOAD = Path(__file__).resolve().parent.parent / "contracts" / "samples" / "optimize_request.json"


def _load(path: Path) -> OptimizeRequest:
    return OptimizeRequest(**json.loads(path.read_text()))


def _time_solver(fn, req: OptimizeRequest):
    t0 = time.perf_counter()
    plan = fn(req)
    wall_ms = (time.perf_counter() - t0) * 1e3
    return plan, wall_ms


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_PAYLOAD
    req = _load(path)

    rows = []

    # Headline: custom ACO (gpu-aco on the GB10, aco-numpy here).
    plan, wall = _time_solver(solver_aco.solve, req)
    rows.append((plan.objective.solver, plan.objective.windows_met,
                 plan.objective.windows_total, plan.objective.total_time_s,
                 plan.objective.solve_ms, wall, len(plan.unassigned)))

    # Greedy baseline (the thing we must beat or match).
    plan, wall = _time_solver(lambda r: solver_baseline.greedy_plan(r), req)
    rows.append((plan.objective.solver, plan.objective.windows_met,
                 plan.objective.windows_total, plan.objective.total_time_s,
                 plan.objective.solve_ms, wall, len(plan.unassigned)))

    # Optional rungs, only if their deps are importable.
    for name, fn in (("cuopt", solver_baseline.try_cuopt),
                     ("ortools", solver_baseline.try_ortools)):
        try:
            p = fn(req)
        except Exception as exc:  # noqa: BLE001
            print(f"[skip] {name}: {exc}")
            continue
        if p is None:
            print(f"[skip] {name}: not installed on this machine")
            continue
        rows.append((p.objective.solver, p.objective.windows_met,
                     p.objective.windows_total, p.objective.total_time_s,
                     p.objective.solve_ms, 0.0, len(p.unassigned)))

    # --- table ----------------------------------------------------------------------
    hdr = ("solver", "windows_met", "windows_total", "total_time_s", "solve_ms",
           "wall_ms", "unassigned")
    widths = [16, 12, 14, 13, 10, 10, 11]
    line = "  ".join(h.ljust(w) for h, w in zip(hdr, widths))
    print(f"\nPayload: {path}")
    print(line)
    print("-" * len(line))
    for r in rows:
        cells = [
            str(r[0]).ljust(widths[0]),
            str(r[1]).ljust(widths[1]),
            str(r[2]).ljust(widths[2]),
            f"{r[3]:.1f}".ljust(widths[3]),
            f"{r[4]:.2f}".ljust(widths[4]),
            f"{r[5]:.2f}".ljust(widths[5]),
            str(r[6]).ljust(widths[6]),
        ]
        print("  ".join(cells))
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
