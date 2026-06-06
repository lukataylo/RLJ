# 🧭 Routing — GPU-accelerated custom router

The headline compute of RLJ: a **custom Ant Colony Optimisation (ACO) solver** for the
Dynamic Pickup-and-Delivery Problem with Time Windows and clinical priorities
(**D-PDPTW**), plus a travel-time engine. It implements the routing-service contract
(`POST /optimize`) the orchestrator calls, and runs **fully local, zero egress** on the
DGX Spark (GB10).

> Runs on this dev Mac with **numpy only** — no GPU, no cuOpt, no OR-Tools required.
> The same code reports `gpu-aco` and runs the hot loop on CUDA arrays when CuPy is
> present on the Spark.

## Approach

We model each job as a **pickup node + dropoff node** and each courier as a **depot
node**. `traveltime.py` builds an `N×N` travel-time matrix over all nodes. `solver_aco.py`
then runs ACO: `K` ants each stochastically construct a full multi-vehicle solution
biased by **pheromone** (learned edge desirability) and a **heuristic** (inverse travel
time + a priority-weighted lateness penalty); the best solution reinforces its edges;
repeat for `n_iter` iterations.

Constraints honoured during construction:
- **pickup-before-dropoff** — a dropoff is only a legal move once its job is on board;
- **capacity** — a pickup is masked out if it would exceed the courier's remaining load;
- **cold-chain** — a cold job can only be picked by a cold-capable courier;
- **time windows** — `ready_at` causes the courier to wait; lateness past `due_by` is
  **penalised, not forbidden** (so a plan is always produced), weighted by priority so
  **STAT** lateness dominates the objective (`stat=100 ≫ urgent=10 ≫ routine=1`).

The objective minimised is `50·weighted_lateness + makespan + 0.001·total_time +
1e9·unassigned` — windows first, then tight parallel routes.

### Why this is a GPU story (the GB10 angle)

The expensive per-step work — gather pheromone/heuristic rows, mask infeasible moves,
weight, normalise, roulette-select — is computed for **all K ants at once** as `(K, N)`
array operations written through a module-level `xp` namespace:

```python
xp = cupy if available else numpy   # solver_aco.py / traveltime.py
```

On the Spark `xp is cupy`, so each construction step is a kernel launch across thousands
of ants in device memory — **no code change**. On this Mac `xp is numpy` and it runs on
CPU. The travel-time haversine baseline is vectorised the same way, so it too moves to
the GPU for free. The planned next step (documented seams) is a custom **batched-SSSP**
CUDA kernel that fills the whole travel-time matrix from the real London road graph in a
single fused pass — re-optimising after a road closure becomes one more kernel call.

## How to run

```bash
pip install -r requirements.txt          # core only: fastapi, uvicorn, pydantic, numpy
uvicorn app:app --reload --port 8100
```

Point the orchestrator at it with `ROUTING_URL=http://localhost:8100`. Develop standalone:

```bash
curl -s -X POST http://localhost:8100/optimize \
  -H 'content-type: application/json' \
  -d @../contracts/samples/optimize_request.json | jq .plan.objective

curl -s http://localhost:8100/healthz        # {"status":"ok","solver":"aco-numpy"}
```

Endpoints (exactly per `contracts/api.md` / `contracts/schemas.json`):
- `GET  /healthz` → `{status, solver}`
- `POST /optimize` → `OptimizeResponse {plan: Plan}`

## Fallback ladder

Every rung below the headline is **import-guarded** — absent deps simply mean the next
rung is used, so a valid `Plan` is *always* returned.

| Rung | Solver | `objective.solver` | Status on this Mac |
|------|--------|--------------------|--------------------|
| 1 | **Custom GPU ACO** (`solver_aco.py`) | `gpu-aco` / `aco-numpy` | ✅ active (`aco-numpy`) |
| 2 | NVIDIA **cuOpt** (`solver_baseline.try_cuopt`) | `cuopt` | skipped (not installed) |
| 3 | Google **OR-Tools** (`solver_baseline.try_ortools`) | `ortools` | skipped (not installed) |
| 4 | **greedy** (`solver_baseline.greedy_plan`) | `greedy-fallback` | ✅ always available |

Travel-time ladder (`traveltime.py`): GPU batched-SSSP → OSMnx/networkx road graph →
**haversine/numpy** (active default). The two road-graph tiers are documented seams.

## GARNET — neural route-optimiser (optional, off by default)

`solver_garnet.py` + `garnet_model.py` implement **GARNET** (Khriss et al., 2026 —
`garnet.pdf`), the encoder–decoder graph-neural-network TSP solver the team originally
planned for route optimisation: **D-RRWP** multi-hop random-walk positional encoding +
**random rewiring** + **GRASS** edge-additive attention, with an **MHA→SHA** decoder that
builds a tour, trained by policy-gradient RL (`train_garnet.py`).

GARNET solves the *symmetric Euclidean TSP*; our problem is multi-vehicle D-PDPTW. So we use
it honestly as an **ordering brain**: it ranks the jobs, the existing feasible constructor +
local search turn that order into a valid plan, and the result joins the portfolio. Because
`pick_best` chooses lexicographically over all candidates, **enabling GARNET can never make a
plan worse** — same fallback-ladder guarantee as every other rung.

```bash
# torch is an OPTIONAL dep (import-guarded). Install it only to use/train GARNET:
#   torch>=2.2   (CPU wheel fine; CUDA wheel on the GB10)
python train_garnet.py --nodes 20 --steps 2000 --out garnet.pt   # produce a checkpoint
GARNET_ENABLED=1 uvicorn app:app --port 8100                      # switch it on
curl -s http://localhost:8100/healthz   # {"status":"ok","solver":"hgs-adaptive+garnet"}
```

`$GARNET_ENABLED` (truthy `1/true/yes/on`; **unset → off**) is the toggle; `$GARNET_WEIGHTS`
(default `routing/garnet.pt`) points at the checkpoint. With no checkpoint the net still emits
valid tours on its initial weights — just not trained-quality ones. When torch is absent or
the toggle is off, the module is a no-op and the service is byte-for-byte unchanged.

## What to show in the demo

1. `python bench.py` — prints the comparison table below. The **headline line** is the
   custom ACO matching greedy on `windows_met` (all clinical windows protected, including
   the STAT job) at `solve_ms` of a few tens of ms on CPU. State that on the GB10 the
   identical code reports `gpu-aco` and the `(K, N)` hot loop runs across thousands of
   ants on-device — the **speedup line** — while patient data never leaves the box.
2. Hit `/healthz` to show the live solver label the UI reads.
3. Curl `/optimize` with the sample and show all three windows met with per-stop ETAs.

Sample bench output on this Mac (numpy, no GPU):

```
solver            windows_met   windows_total   total_time_s   solve_ms    wall_ms     unassigned
--------------------------------------------------------------------------------------------------
aco-numpy         3             3               4426.8         46.38       46.41       0
greedy-fallback   3             3               4026.1         0.00        0.11        0
```

ACO **matches greedy** (3/3 windows, 0 unassigned) while honouring full PDPTW
constraints greedy ignores (pickup-order, cold-chain, interleaved multi-job loads).

## Files

| File | Purpose |
|------|---------|
| `app.py` | FastAPI service; solver selection + fallback ladder |
| `solver_aco.py` | Custom ACO D-PDPTW solver (`xp` = CuPy/NumPy) |
| `garnet_model.py` | GARNET neural TSP architecture (D-RRWP + rewiring + GRASS + MHA→SHA), torch |
| `solver_garnet.py` | GARNET portfolio member + `$GARNET_ENABLED` toggle (off by default) |
| `train_garnet.py` | Policy-gradient trainer → `garnet.pt` checkpoint (optional, torch) |
| `solver_baseline.py` | Greedy port + import-guarded cuOpt / OR-Tools |
| `traveltime.py` | Travel-time matrix (haversine now; GPU-SSSP + OSMnx seams) |
| `models.py` | Pydantic mirror of `contracts/schemas.json` (self-contained) |
| `bench.py` | Solver comparison table — the demo's speedup numbers |
| `requirements.txt` | Core deps + optional accelerators (commented) |
| `AGENT.md` | Build checklist + NemoClaw note |
