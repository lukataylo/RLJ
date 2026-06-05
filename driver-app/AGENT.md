# AGENT.md — driver-app

Scope for any agent working in `driver-app/`.

## What this is

The **Driver-App**: a mobile-first PWA for crowdsourced delivery drivers — the
consumer side of the RLJ congestion flywheel. Drivers share GPS (`/telemetry`)
and get green-wave routing back (`/driver/{id}/guidance`, `/signals/advice`).

## Boundaries (hard rules)

- **Work ONLY inside `driver-app/`.** Do not edit `frontend/`, `routing/`,
  `data/`, `voice/`, or `orchestrator/`.
- Read-only references: `contracts/schemas.json`, `contracts/driver-api.md`,
  `frontend/src/lib/palette.ts`, and `frontend/src/*` for the visual style.
- **Mirror schema field names EXACTLY** (`src/types.ts` ↔ `contracts/schemas.json`).
- **No secrets.** `.env` is gitignored; only `.env.example` holds placeholders.

## Conventions

- Stack: Vite + React + TS + zustand; maplibre-gl (token-less CARTO dark) with a
  mapbox-gl upgrade path when `VITE_MAPBOX_TOKEN` is set (same pattern as
  `frontend/`).
- Aesthetic: TRON glass — near-black, neon cyan `#18f0ff` + hot-orange `#ff9d2f`,
  Orbitron headings / Rajdhani body, frosted glass, neon glow. Tokens live in
  `src/index.css` `:root` and `src/lib/palette.ts`.
- **Everything degrades gracefully.** No API call should throw to the UI: see
  `src/api.ts` (`ApiResult`), the demo fallbacks in `src/lib/demo.ts`, and the
  online-vs-404 split in `src/App.tsx`.

## Must stay green

```bash
npx tsc -b        # clean
npm run build     # clean
```

## Map of the code

| File | Responsibility |
|------|----------------|
| `src/types.ts` | TS mirror of `schemas.json` (driver entities) |
| `src/api.ts` | REST helpers + `simulateGps` + `getGeoFix` + `health` |
| `src/lib/demo.ts` | demo congestion / advice / guidance fallbacks |
| `src/lib/palette.ts` | shared neon palette + congestion ramp |
| `src/store.ts` | zustand session store (persists driver identity) |
| `src/App.tsx` | shell + health/telemetry/congestion/guidance loops |
| `src/components/Signup.tsx` | onboarding → `POST /drivers` |
| `src/components/DriverMap.tsx` | maplibre/mapbox map + heat/route/driver layers |
| `src/components/GreenWaveCard.tsx` | advice + `Speedometer` |
| `src/components/ContributionStats.tsx` | gamified impact stats |
| `src/components/AskButton.tsx` | voice deep-link placeholder FAB |

## Known contract gap (report only — do not fix here)

As of writing, `orchestrator/app.py` implements none of the driver endpoints
(`/drivers`, `/telemetry`, `/congestion`, `/driver/{id}/guidance`,
`/signals/advice`) nor the `driver_joined` / `congestion_updated` WS events from
`contracts/driver-api.md`. The app runs fully on demo data until those land.
