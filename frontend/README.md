# 🗺️ Frontend — RLJ live operations map

The demo centerpiece: a live London map of couriers, jobs and routes that **redraws
when the world changes**. Vite + React + TypeScript, **MapLibre GL** basemap (free,
no API token) with **deck.gl** overlays for GPU-rendered routes and animated couriers.

## Views: operations map ⇄ LiDAR 3D twin

A toggle (top-centre) switches the main view between:

- **Map** — the deck.gl/MapLibre operations map (couriers, routes, congestion, incidents).
- **LiDAR 3D** — a Three.js point-cloud digital twin of the Square Mile: the real EA
  National LIDAR Programme scan (`public/citycloud.bin`, 3M points) with OSM building
  facades extruded to fill the towers (`public/citybuildings.json`, ~4.4k City buildings),
  an infinite grid, radar sweep, bloom + vignette, and orbit/zoom. Live disruptions from
  the orchestrator rise as beams (red for road closures). Ported from Square Mile Pulse
  (`src/components/CityScene.tsx`, `src/lib/pointcloud.ts`, `src/lib/scene-geo.ts`); needs
  `three` + `@react-three/{fiber,drei,postprocessing}`.

## Run

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

By default it talks to the orchestrator at `http://localhost:8000`. To point elsewhere:

```bash
cp .env.example .env
# edit VITE_ORCHESTRATOR_URL=http://localhost:8000
```

Start the hub first (in another terminal) so there's something to talk to:

```bash
cd orchestrator && pip install -r requirements.txt && uvicorn app:app --reload --port 8000
# optional: python seed.py   # to load demo couriers/jobs
```

## What it talks to

- `GET http://localhost:8000/state` — hydrate on load (and after any WS drop).
- `ws://localhost:8000/ws` — live events `{type, payload, ts}`: `state`, `job_created`,
  `plan_updated`, `courier_moved`, `disruption`, `agent_log`, `notification`.
- `POST /jobs` — "Add STAT job" button.
- `POST /disruptions` — "Close road" (`road_closure`) and "Courier down" (`courier_down`).
- `POST /optimize` — "Re-optimize" button.

All entity field names mirror [`../contracts/schemas.json`](../contracts/schemas.json)
(see [`src/types.ts`](src/types.ts)). No endpoints are invented.

### Resilience
On load the app does `GET /state`, then live-updates from `/ws`. If the socket drops it
auto-reconnects with backoff **and re-hydrates** via `GET /state`, so it never shows
stale state. The basemap uses token-less CARTO dark raster tiles so there's nothing to
configure at the venue.

## What it shows

- **Couriers** as markers, coloured by status (idle=green, enroute=cyan, offline=grey).
- **Jobs** as origin→destination pairs coloured by priority (stat=red, urgent=amber,
  routine=blue), endpoints marked.
- **Current plan** routes drawn from each `route.polyline` (deck.gl `PathLayer`), with a
  marker animated along every route.
- **Agent log** panel streaming `agent_log` + `notification` narration in plain English.
- **Scoreboard / HUD**: `windows_met / windows_total`, total route time, active solver
  (`plan.objective.solver`) and `solve_ms` — the GPU story.

## What to show in the demo

Seed a couple of couriers and jobs, let the map settle with routes drawn and the
scoreboard reading e.g. `3/3 windows met`. Then hit **Close road** — the orchestrator
posts a `road_closure`, re-optimizes, and the map **visibly redraws** the routes to
protect the at-risk clinical windows while the agent log narrates *why* and the
scoreboard updates live. That close-road → re-route redraw, paired with the
`solver` / `solve_ms` HUD ticking, is the money shot. Follow up with **Add STAT job**
(a red drop-everything pickup appears and gets slotted in) and **Courier down** (a van
goes grey and its work is reassigned) to show continuous local re-planning.
