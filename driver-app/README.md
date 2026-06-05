# RLJ Driver

A mobile-first **PWA for crowdsourced delivery drivers** (Deliveroo-style) — the
*consumer* side of the RLJ congestion flywheel. Drivers share anonymised GPS and
in return get **green-wave / signal-aware routing**. More drivers → denser
congestion field → better routing for the medical-courier fleet *and* the drivers
themselves.

Built to match the RLJ ops-console aesthetic: near-black TRON glass, neon cyan
`#18f0ff` + hot-orange `#ff9d2f`, Orbitron headings / Rajdhani body, frosted
glass and neon glow.

## Stack

- **Vite + React + TypeScript**
- **maplibre-gl** token-less CARTO dark basemap by default; **mapbox-gl** premium
  dark style automatically when `VITE_MAPBOX_TOKEN` is set (mirrors `frontend/`).
- **zustand** for session state.
- Talks to the orchestrator at `VITE_ORCHESTRATOR_URL` (default
  `http://localhost:8000`) per [`contracts/driver-api.md`](../contracts/driver-api.md)
  and [`contracts/schemas.json`](../contracts/schemas.json).

## Run

```bash
cd driver-app
cp .env.example .env        # optional: set VITE_ORCHESTRATOR_URL / VITE_MAPBOX_TOKEN
npm install
npm run dev                 # http://localhost:5174
```

Production build / preview:

```bash
npm run build               # tsc -b && vite build  (must pass clean)
npm run preview             # serves dist/ on :5174
```

> The dev server uses **port 5174** so it can run alongside the ops console
> (`frontend/` on 5173).

## What to show in the demo

The app is designed to be fully demoable **on a laptop with no orchestrator and
no GPS** — everything degrades gracefully to live-looking demo data.

1. **Onboarding** — enter a name, pick a vehicle (bike/scooter/car/van), flip the
   **consent** toggle (required), tap *Start driving*. The driver id is persisted
   in `localStorage`, so reloads skip straight back to the map.
2. **Share location** — flip the big **Share location** toggle. With no GPS the
   app **simulates** movement along a central-London loop; the map follows the
   driver dot and the **"Contributing · N pings"** indicator ticks up every ~5s
   (each tick is a `DriverPing` POSTed to `/telemetry`).
3. **Green wave** — the headline card shows the big advice line
   (*"Ease to 28 km/h to catch the next green"*), a **speedometer** gauge
   (current speed vs the orange target tick) and a **seconds-to-green** countdown.
4. **Your impact** — gamified contribution: pings sent, couriers helped, points,
   and the **"you made London faster"** hero number that counts up.
5. **Ask** — the prominent orange voice FAB (deep-link placeholder for the driver
   voice assistant) pulses while "listening".
6. **The flywheel story** — congestion heat on the map is the data drivers
   produce; the green-wave guidance is what they get back. Point at the ops
   console (`frontend/`) to show the medical fleet re-routing around the same
   congestion.

### Graceful degradation (all handled)

| Condition | Behaviour |
|-----------|-----------|
| No orchestrator | Full **demo data** (heat field, green-wave, growing stats); `◌ demo` chip |
| Orchestrator up, driver endpoint 404s | That card is **hidden** (green-wave) / heat layer cleared |
| No Geolocation / permission denied | **Simulated** movement along central London |
| GPS drops mid-session | Falls back to the simulator automatically |
| No Mapbox token | Token-less **MapLibre** CARTO dark fallback |

## Endpoints used (see `contracts/driver-api.md`)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/drivers` | signup |
| POST | `/telemetry` | send `DriverPing` batch (every ~5s while sharing) |
| GET  | `/congestion` | congestion heat layer |
| GET  | `/driver/{id}/guidance` | route + green-wave + contribution |
| GET  | `/signals/advice` | green-wave advice (fallback when guidance 404s) |

`GET /healthz` (core orchestrator) is used to distinguish "offline → demo" from
"endpoint missing → hide card".

## Test hooks (`data-testid`)

`signup-form`, `btn-consent`, `btn-share-toggle`, `greenwave-advice`,
`contribution-pings`, `ask-voice`.
