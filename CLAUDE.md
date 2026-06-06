# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**PulseGo — Time-Critical Medical Logistics for London** (internal/legacy name: *RLJ*). A
local-first, agentic medical-courier optimiser built for Hack for Impact London (NVIDIA),
designed to run entirely on a single DGX Spark (GB10) so patient data never leaves the box. It
collects pathology samples and delivers urgent meds across London within clinical time windows,
re-planning live when a road closes, a courier drops out, or a STAT (urgent) request arrives.

The defining principle: **every capability shown on screen is backed by an external test that
passed.** A claim is "Verified" only because its bound, non-LLM test passed in the latest run —
`make verify` is the definition of done and CI blocks merges otherwise.

> This repo's root is `RLJ/` (`git rev-parse --show-toplevel`). The tracked files (`git ls-files`,
> ~200 files) *are* the project. The product name is **PulseGo** (domains `pulsego.org`,
> `api.pulsego.org`, etc.); `RLJ` survives only in legacy paths like the `rlj-signal-agent`
> systemd unit. Treat the two names as synonymous.

## Commands

```bash
make install        # install python test + service deps into ./.venv
make data           # build + verify datasets -> data/manifest.json + map geojson
make verify         # THE GATE: run all external suites, map to claims, write STATUS.json. Non-zero unless GREEN
make verify-core    # the gate without browser e2e (fast inner loop)
make demo           # ./scripts/dev.sh — bring up the stack
make e2e-install    # one-time: install Playwright chromium for the e2e suite

# Run the stack (separate terminals)
cd routing && uvicorn app:app --port 8100                                   # routing solver service
cd orchestrator && ROUTING_URL=http://localhost:8100 uvicorn app:app --port 8000   # hub
cd frontend && npm install && npm run dev                                   # command-center :5173
cd driver-app && npm install && npm run dev                                 # driver PWA :5174
python scripts/demo_seed.py                                                  # now-anchored scenario

# Tests (pytest; markers: e2e, slow, data — see pytest.ini; testpaths=tests)
pytest                                  # full suite under tests/
pytest tests/unit                       # fast unit tests
pytest -m "not e2e and not slow"        # skip browser + long backtests
pytest tests/benchmarks/test_hgs_speedup.py   # the HGS speedup gate
pytest tests/unit/test_foo.py::test_bar       # a single test
```

Frontends use Vite: `npm run dev` / `npm run build` (`tsc -b && vite build`) / `npm run preview`.

## Architecture

Three Python services plus two front-ends, all local. Flow: **voice intake → orchestrator →
routing → frontend**, with WebSocket broadcast back to the UI.

| Module | Role |
|---|---|
| `contracts/` | The integration contract: shared data model (`schemas.json`), REST + WebSocket API (`api.md`, `driver-api.md`), sample payloads (`samples/`). **This is the API — integrate through it.** |
| `orchestrator/` | The hub (`:8000`). In-memory state (jobs/couriers/plan/disruptions), WebSocket `/ws` broadcast, dispatch, autonomy loop (`autonomy.py`), congestion field (`congestion.py`), greedy fallback router (`greedy.py`), JWT auth (`auth.py`) + Postgres/SQLAlchemy users (`db.py`), local Nemotron agent (`nemo_agent.py`). |
| `routing/` | The routing service (`:8100`). `POST /optimize` portfolio: greedy + insertion + GPU ACO + OR-Tools/cuOpt, local-search refined. Solvers: `solver.py` (adaptive portfolio entry), `solver_hgs.py`, `solver_ls.py`, `solver_aco.py`, `solver_ortools.py`, `solver_baseline.py`. |
| `voice/` | ElevenLabs intake + outbound caller + driver voice assistant (`driver_assistant.py`, `nlu.py`, `intake.py`, `outbound.py`). |
| `frontend/` | deck.gl/MapLibre dark command-center (`:5173`) for dispatchers; verified badges read live from `STATUS.json`; live data layers. |
| `driver-app/` | Mobile Tron PWA (`:5174`) for delivery drivers: signup, share-GPS, green-wave/signal-aware routing, contribution stats (the data flywheel). |
| `data/` | Datasets + builders: facilities, demand, roads/buildings, Tower Bridge lifts, events, junctions, weather, crowdsourced probes. `build.py` writes `manifest.json` with `dq_passed` flags. |
| `verification/` | The claims ledger + gate. `run.py` runs external suites, maps results onto `claims.yaml`, writes `STATUS.json` (UI reads it) + `VERIFICATION.md`. |
| `tests/` | External suites: `unit/`, `data_quality/`, `contracts/`, `backtests/`, `benchmarks/`, `e2e/`, `integration/`, `completeness/`, `voice/`. |
| `nemoclaw/` | Local-first sandbox egress policies (voice=ElevenLabs-only; routing=zero egress). |
| `scan11/` | GB10 traffic-signal agent (systemd unit `rlj-signal-agent`) — pushes signal recs to the orchestrator. |

### Key API surfaces
- **Orchestrator** `:8000` — `/state`, `/jobs`, `/couriers`, `/disruptions` (triggers re-optimize),
  `/optimize`, `/plan`, `/notifications`, `/drivers`, `/auth/*`, and `ws://.../ws` (events:
  `state`, `job_created`, `plan_updated`, `courier_moved`, `disruption`, `agent_log`,
  `notification`).
- **Routing** `:8100` — `/healthz`, `POST /optimize` (`OptimizeRequest` → `{plan: Plan}`). The
  orchestrator calls it when reachable, else falls back to its built-in greedy router.

### Auth (env-gated)
`AUTH_REQUIRED` is **off by default** so the existing tests (which POST without a token) keep
passing; `require_user` is then a no-op anonymous sentinel. Set `AUTH_REQUIRED=true` (prod) to
demand a `Authorization: Bearer <jwt>` on write endpoints. Other env: `JWT_SECRET` (a warned-about
dev default is used if unset), `ADMIN_EMAIL`/`ADMIN_PASSWORD` (seed an admin at startup),
`DATABASE_URL` (Postgres; falls back to SQLite for local dev). When adding write endpoints, keep
this toggle intact — don't hard-require auth, or you'll break the test suite.

### Conventions
- Times are ISO-8601 UTC strings; the planning clock is `now` in `OptimizeRequest`.
- IDs are strings; orchestrator generates them when omitted (`job-<n>`, `crt-<n>`).
- Coordinates are WGS84 `lat`/`lng`. London bbox ≈ lat 51.28–51.69, lng −0.51–0.33.
- Be liberal in what you accept, strict in what you emit — always return the full entity.
- `Plan.objective.solver` is the string the UI displays (e.g. `gpu-aco`, `cuopt`, `hgs-adaptive`).

## Working in this repo

- **Verification is the source of truth.** Don't mark work done by assertion — wire a capability
  to an external test in `tests/`, bind it in `verification/claims.yaml`, and run `make verify`.
  If a claim isn't backed by a passing test, the UI won't show it as Verified and CI will fail.
- **Module ownership / separation.** The repo was built by three concurrent streams on disjoint
  folders that integrate only through `contracts/` — voice owns `voice/`, routing owns `routing/`,
  frontend owns `frontend/`. Don't reach into another module's internals; change `contracts/`
  deliberately when the shared schema must change. (See `AGENTS.md` and per-module `AGENT.md`.)
- **Code against the mock orchestrator** from the start — it runs standalone via the built-in
  greedy router, so you never block on another service.
- **Every component has a fallback** (see the ladder in `ARCHITECTURE.md`): custom GPU solver →
  cuOpt → OR-Tools → greedy; custom travel-time kernel → OSMnx → haversine; ElevenLabs → text
  intake; live TfL feed → manual injection. Keep a working path.

## Deployment

Railway monorepo → 5 services, each with its own Root Directory + in-folder `Dockerfile`, plus a
Postgres plugin: `api` (orchestrator, public), `routing` (private), `web` (frontend, public),
`driver` (PWA, public), `Postgres`. See `DEPLOY.md`. For the GB10 box ↔ map topology (the
signal agent pushes to the orchestrator at its `ORCH` env IP), see `CONNECT.md`.

## Further reading

`README.md` (overview + quickstart), `ARCHITECTURE.md` (diagram, control flow, fallback ladder),
`AGENTS.md` (module ownership / working agreement), `DEMO.md` (demo runbook), `DEPLOY.md` +
`CONNECT.md` (deploy + box wiring), `RESEARCH.md` + `routing/RESEARCH_HGS.md` (research claims),
`verification/VERIFICATION.md` (live claim status).
</content>
</invoke>
