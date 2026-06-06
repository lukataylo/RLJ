# PulseGo Driver (Expo / React Native)

Native driver companion app for the PulseGo medical-logistics stack. Runs in
**Expo Go** (no native build required). It adds the things the web PWAs don't:

- **Turn-by-turn navigation with text-to-speech.** Spoken maneuvers (`expo-speech`)
  driven by live GPS (`expo-location`). Street-name maneuvers come from the
  Mapbox Directions API when `EXPO_PUBLIC_MAPBOX_TOKEN` is set; otherwise turns
  are derived on-device from the route polyline geometry.
- **Re-routing comms to the server.** "Re-route" calls `POST /couriers/{id}/redirect`;
  "Report blockage" calls `POST /disruptions`. The server re-optimizes and
  broadcasts `plan_updated` over the WebSocket; the app redraws the route and
  announces "Route updated". Going off-route auto-requests a new route.
- **Jobs & History.** Upcoming jobs (`new｜assigned｜in_transit`) ordered by your
  route's stop sequence, and past jobs (`delivered｜failed`), from `GET /jobs`.
- **Green wave + flywheel (parity with the `driver-app` PWA).** Green-wave card
  with a speedometer (current vs target speed), seconds-to-green and confidence
  (`/driver/{id}/guidance` → `/signals/advice`); a live congestion heat layer on
  the map (`/congestion`); and an **Impact** tab (pings sent, couriers helped,
  points, "minutes faster"). All degrade gracefully to demo data when the
  orchestrator or these optional endpoints are unavailable.
- **Calm Command design language.** Pulse-Red accent on a charcoal/cream base,
  Poppins + Inter, glass panels — tokens ported from `frontend/src/index.css`.

## Run

```bash
cd mobile
cp .env.example .env          # set EXPO_PUBLIC_API_URL / EXPO_PUBLIC_MAPBOX_TOKEN
npm install
npx expo start                # scan the QR with Expo Go, or press i / a
```

By default the app targets `https://api.pulsego.org`. To point at a local
orchestrator, set `EXPO_PUBLIC_API_URL` to your machine's LAN IP (e.g.
`http://192.168.1.20:8000`) so the phone can reach it — or change it at runtime
in the **Settings** tab.

## Flow

1. **Login** — `POST /auth/login`; JWT stored in `expo-secure-store`.
2. **Select courier** — pick which `Courier` (vehicle) you're driving; also
   registers a `Driver` for the telemetry flywheel.
3. **Navigate / Jobs / History / Settings** tabs.

`npm run typecheck` runs `tsc --noEmit`.

## Layout

- `app/` — expo-router screens (`login`, `select-courier`, `(tabs)/*`).
- `src/theme/` — Calm Command tokens + theme provider.
- `src/lib/` — `api`, `auth`, `ws`, `store`, `directions`, `navigation`, `geo`,
  `types` (mirrors `contracts/schemas.json`).
- `src/components/` — `GlassCard`, `StatusPill`, `PrimaryButton`, `JobCard`,
  `ManeuverBanner`, `RouteMap`.

## Notes

In Expo Go the base map tiles are Apple (iOS) / Google (Android) with a dark
custom style — they won't match the web's CARTO vector tiles, but routes and
markers use the shared palette so it stays on-brand. A `EXPO_PUBLIC_MAPBOX_TOKEN`
is optional but recommended for real street-name voice directions.
