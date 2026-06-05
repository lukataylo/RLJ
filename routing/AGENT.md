# AGENT — Routing stream (Agent 2)

Owner of `routing/` only. May **read** `contracts/`, `orchestrator/`, `data/`, the
root docs, and `nemoclaw/`. Must not edit anything outside `routing/`.

## Mission

Ship the GPU-accelerated custom router behind the `POST /optimize` contract so the
orchestrator prefers us over its built-in greedy. Headline = a **custom ACO** D-PDPTW
solver on the GB10. Must beat or match greedy on `windows_met` for the sample, and run
on a numpy-only Mac with graceful fallback.

## Build checklist

- [x] `models.py` — self-contained pydantic mirror of `contracts/schemas.json` (no
      cross-folder import).
- [x] `traveltime.py` — haversine/numpy `N×N` travel-time matrix via `xp` (CuPy/NumPy);
      documented seams for GPU batched-SSSP and OSMnx road-graph tiers.
- [x] `solver_aco.py` — custom ACO for D-PDPTW. Vectorised `(K, N)` hot loop through
      `xp`; honours pickup-before-dropoff, capacity, cold-chain, priority-weighted time
      windows. Emits a `Plan` with per-stop ETAs, `window_met`, and `objective.solve_ms`.
- [x] `solver_baseline.py` — greedy port (rung 4) + import-guarded cuOpt (rung 2) /
      OR-Tools (rung 3).
- [x] `app.py` — FastAPI on :8100; `GET /healthz` → `{status, solver}`,
      `POST /optimize` → `{plan}`. Selects solver at startup; runs the fallback ladder so
      a valid Plan is always returned. `response_model_exclude_none=True` keeps output
      schema-valid.
- [x] `bench.py` — solver comparison table (the demo speedup numbers).
- [x] `requirements.txt` — core (fastapi/uvicorn/pydantic/numpy); CuPy/cuOpt/OR-Tools/
      OSMnx optional + commented.
- [x] Verified: `/optimize` returns a schema-valid Plan on the sample with **3/3 windows
      met, 0 unassigned** on this Mac (`aco-numpy`); curl + jsonschema checked.

### On the DGX Spark (GB10) — to light up the GPU path

- [ ] `pip install cupy-cuda12x` (match the box CUDA) → ACO hot loop runs on-device;
      `/healthz` and `objective.solver` flip to `gpu-aco` automatically.
- [ ] Optionally install `cuopt` (rung 2) and/or `ortools` (rung 3) — auto-detected.
- [ ] Implement `traveltime.gpu_sssp_matrix` (batched-SSSP over the London road graph)
      and wire road closures from `disruptions` into edge weights for live re-route.
- [ ] Re-run `python bench.py` on the Spark to capture the real `gpu-aco` solve_ms for
      the demo speedup line.

## NemoClaw — fully local, zero egress

Routing reasoning runs as the **NemoClaw `rlj-routing`** sandboxed agent on local
Nemotron. Per `../nemoclaw/policy-routing.yaml` it has **no `network_policies`** —
default local inference (`inference.local`) only, **no outbound network**. Patient-derived
job data (origins/destinations/raw intake text) stays on the box. This is the local-first
"pull the cable" resilience story: with the network down, routing + the local model keep
the core loop alive. Verify egress is blocked:

```bash
nemoclaw rlj-routing exec -- bash -c 'curl -sS --max-time 5 https://example.com'
# expect: curl: (56) CONNECT tunnel failed, response 403
```

Keep it that way: this service makes **no outbound calls** (no map APIs, no telemetry).
Travel times come from local computation (haversine now; on-box road graph later).

## Contract notes / gaps (report only — do not edit contracts/)

- `Stop.window_met` is typed non-nullable `boolean` but isn't `required`. Pickups have no
  clinical window, so we **omit** the field for pickups (via `exclude_none`) rather than
  emit `null` — keeps the Plan schema-valid. Suggest the contract either mark it
  nullable or document "dropoff-only".
- No courier **cold-chain capability** field in `schemas.json`. We added an optional,
  non-schema `Courier.cold_capable` (default `True`) so cold-chain feasibility is
  enforceable; it's ignored by other streams. Suggest adding it to the shared schema.
- `objective` and several `Plan` sub-fields are optional in the schema; we always
  populate `total_time_s / windows_met / windows_total / solver / solve_ms`.
