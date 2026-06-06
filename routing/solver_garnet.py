"""GARNET route-optimisation member for the portfolio — env-gated, off by default.

GARNET (``garnet_model.GarnetTSP``) is a *neural TSP solver*: it learns a tour ordering
over a set of points. The service's real problem is multi-vehicle **D-PDPTW** (pickups
before drop-offs, capacity, cold-chain, clinical windows), which the paper itself notes is
beyond the symmetric-Euclidean TSP formulation it solves. So we use GARNET honestly, as the
*ordering brain*:

  1. treat each job's pickup as a TSP "city" and ask GARNET for a visiting order,
  2. feed that order into the existing feasible constructor (cheapest-feasible insertion in
     GARNET's order), honouring capacity / cold-chain / windows / pickup-before-dropoff,
  3. polish with the existing local search and hand the candidate to the portfolio.

Because the result re-enters ``solver.plan``'s candidate pool and is chosen only by
``solver_ls.pick_best`` (the same lexicographic clinical objective as every other member),
enabling GARNET can **never make a plan worse** — it can only contribute a better ordering.
That is the fallback-ladder guarantee the repo insists on.

Toggle
------
Controlled by ``$GARNET_ENABLED`` (truthy: ``1/true/yes/on``). **Unset → off.** When off, or
when torch is not installed, ``plan()`` returns ``None`` and the portfolio is byte-for-byte
unchanged. An optional trained checkpoint is loaded from ``$GARNET_WEIGHTS`` (default
``routing/garnet.pt``); without it the network runs on its deterministic initial weights
(still a valid tour, just not a trained-quality one — see ``train_garnet.py``).
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from models import OptimizeRequest, Plan

_TRUTHY = {"1", "true", "yes", "on"}
_DEFAULT_WEIGHTS = os.path.join(os.path.dirname(__file__), "garnet.pt")
SOLVER_NAME = "garnet"


def enabled() -> bool:
    """True only when the operator has explicitly switched GARNET on."""
    return os.environ.get("GARNET_ENABLED", "").strip().lower() in _TRUTHY


@lru_cache(maxsize=1)
def _load_model():
    """Build the GARNET model once (and load a checkpoint if present). torch-guarded.

    Returns ``(model, torch)`` or ``None`` when torch is unavailable. Cached so we pay the
    construction / load cost once per process, not per ``/optimize`` call.
    """
    try:
        import torch  # optional dependency — absent on the numpy-only dev box
        import garnet_model
    except Exception:  # noqa: BLE001 - torch not installed -> GARNET simply unavailable
        return None
    model = garnet_model.GarnetTSP()
    path = os.environ.get("GARNET_WEIGHTS", _DEFAULT_WEIGHTS)
    if os.path.exists(path):
        try:
            model.load_state_dict(torch.load(path, map_location="cpu"))
        except Exception:  # noqa: BLE001 - a stale/incompatible checkpoint must not crash
            pass
    model.eval()
    return model, torch


def _job_order(req: OptimizeRequest) -> Optional[list[int]]:
    """Ask GARNET for a visiting order over the job pickups. Returns indices into req.jobs."""
    loaded = _load_model()
    if loaded is None:
        return None
    model, torch = loaded
    jobs = req.jobs
    if len(jobs) < 2:
        return list(range(len(jobs)))

    # Normalise pickup coords to the unit square the model was trained on ([0,1]^2).
    lats = [j.origin.lat for j in jobs]
    lngs = [j.origin.lng for j in jobs]
    coords = _to_unit_square(lats, lngs, torch)
    tour = model.tour(coords, start=0)
    # The closed tour starts at job 0; the sequence itself is the ordering we want.
    return [i for i in tour if 0 <= i < len(jobs)]


def _to_unit_square(lats, lngs, torch):
    """Min-max normalise lat/lng into [0,1]^2 (degenerate axes collapse to 0)."""
    lat = torch.tensor(lats, dtype=torch.float32)
    lng = torch.tensor(lngs, dtype=torch.float32)

    def _norm(v):
        lo, hi = v.min(), v.max()
        span = (hi - lo).clamp_min(1e-9)
        return (v - lo) / span

    return torch.stack([_norm(lat), _norm(lng)], dim=1)


def plan(req: OptimizeRequest) -> Optional[Plan]:
    """Return a GARNET-ordered feasible plan, or ``None`` if disabled/unavailable.

    Never raises: any failure (torch missing, model error) degrades to ``None`` so the
    caller's portfolio is unaffected — honouring "every component has a fallback".
    """
    if not enabled():
        return None
    try:
        import solver_ls  # reuse the feasible constructor + local search + plan assembly

        order = _job_order(req)
        if order is None:
            return None
        P = solver_ls._P(req)
        if P.C == 0 or P.J == 0:
            return None

        # Cheapest-feasible insertion, visiting jobs in GARNET's learned order.
        assign: dict[str, list[str]] = {c.id: [] for c in P.couriers}
        ordered_jobs = [P.jobs[i] for i in order] + [
            P.jobs[i] for i in range(P.J) if i not in set(order)
        ]
        for job in ordered_jobs:
            best = None  # (key, cid, pos)
            for cid in assign:
                if not solver_ls._feasible_cold(P, cid, job):
                    continue
                seq = assign[cid]
                for pos in range(len(seq) + 1):
                    trial = {**assign, cid: seq[:pos] + [job.id] + seq[pos:]}
                    key, _u, _s = solver_ls._score(P, trial)
                    if best is None or key > best[0]:
                        best = (key, cid, pos)
            if best is not None:
                _k, cid, pos = best
                assign[cid].insert(pos, job.id)

        out = solver_ls._to_plan(P, solver_ls._refine_assign(P, assign))
        out.objective.solver = SOLVER_NAME
        return out
    except Exception:  # noqa: BLE001 - GARNET must never break /optimize
        return None
