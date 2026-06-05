# AGENT.md — Frontend (Agent 3)

Runs as a **normal local dev process** (`npm run dev` on :5173) — **not** in a NemoClaw
sandbox. It only talks to the orchestrator on localhost (REST + WS) and pulls a public
dark raster basemap; no secrets, no egress allowlist needed.

## Build checklist

- [x] Vite + React + TypeScript app, dev server on `:5173`.
- [x] `src/types.ts` mirrors `contracts/schemas.json` (exact field names) + WS envelope.
- [x] `src/api.ts`: `getState`, `postJob`, `postDisruption`, `optimize`, and
      `connectWs(handlers)` with auto-reconnect; base URL from
      `import.meta.env.VITE_ORCHESTRATOR_URL` (default `http://localhost:8000`).
- [x] `src/store.ts` (zustand): jobs/couriers/plan/disruptions/logs updated from WS events.
- [x] `src/MapView.tsx`: MapLibre (token-less CARTO dark style) + deck.gl `MapboxOverlay`
      — job pairs (priority colour), endpoints, route `PathLayer` from `polyline`, animated
      head markers, couriers (status colour), disruption markers.
- [x] `src/Panel.tsx`: scoreboard (`windows_met/total`, total time, `solver`, `solve_ms`),
      legend, demo buttons (Close road / Courier down / Add STAT job / Re-optimize), agent log.
- [x] `src/App.tsx` + `src/main.tsx`: hydrate via `GET /state`, wire WS → store, re-hydrate
      on reconnect.
- [x] Dark theme CSS, big legible HUD.
- [x] `.env.example` with `VITE_ORCHESTRATOR_URL`.

## Definition of done (shared, from AGENTS.md)

1. Runs standalone against the mock orchestrator (greedy fallback router).
2. Survives fallback: WS drop → auto-reconnect + re-hydrate; no map token required.
3. README has a "what to show in the demo" paragraph (close-road re-route + scoreboard).

## Conventions

- Coordinates are WGS84 `lat`/`lng`; map centred on London (~51.50, -0.12).
- Never reach into `voice/` or `routing/`; integrate only through `contracts/` + orchestrator.
- If a contract change is needed, edit `contracts/` and announce — do not fork the schema here.

## Local manual test

```bash
# terminal 1
cd orchestrator && uvicorn app:app --reload --port 8000 && python seed.py
# terminal 2
cd frontend && npm install && npm run dev
```
Open http://localhost:5173, confirm routes draw, then click **Close road** and watch the
plan redraw + scoreboard update.
