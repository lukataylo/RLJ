# LiDAR 3D digital twin — an alternative city view

A toggle (top-centre of the command center) switches the main view between the
existing **deck.gl operations map** and a new **LiDAR 3D point-cloud twin** of the
Square Mile. Both share the same RLJ shell (efficiency KPIs, delivery list,
NEMOCLAW log, fleet) and the same live orchestrator state — only the spatial
canvas changes.

## What the point cloud is

- **Real survey data, not a model.** It renders the actual **EA National LIDAR
  Programme** aerial scan of the City of London (tile TQ3080, OGL v3) — 3.0M points
  decimated from the raw ~43M-point LAZ, recentred on Bank junction. Every point is
  a real elevation return.
- **Buildings filled in.** Aerial LiDAR misses vertical walls, so ~4,400 OSM City
  building footprints are extruded to their real heights and sampled as facade
  points, so towers read as solid rather than hollow rooftops.
- **Rendered in Three.js** (`@react-three/fiber`): a cyberpunk teal→cyan height
  gradient, additive glow with distance-attenuated points, an infinite ground grid,
  a sweeping radar ring, bloom + vignette, and orbit/zoom controls.
- **Live-reactive.** Disruptions from the orchestrator rise as light beams at their
  true coordinates (red for road closures, amber otherwise) — the same events that
  redraw routes on the map appear here as vertical markers in real 3D space.
- **Self-contained.** The cloud (`citycloud.bin`, 36 MB) and buildings
  (`citybuildings.json`) are baked static assets served from `/public`. No tile
  server, no API token, no extra backend — it renders entirely client-side.

## Why it's a valuable alternative to the map

1. **Situational awareness through real 3D geometry.** The ops map is an abstract
   flat dark basemap; the twin shows the City's *actual* built form — real building
   heights, density, street canyons, the cluster of tall towers around Bishopsgate.
   For a service operating in a dense vertical city, "where is it, and what does the
   space actually look like" is information the 2D map cannot convey.

2. **Verticality the domain cares about.** Disruption beams, and the height context
   around them, read naturally in 3D — useful for line-of-sight reasoning (CCTV),
   understanding why a street-level closure matters, and communicating impact at a
   glance. On a flat map these are just dots.

3. **It reinforces the local-first / GPU story.** A live 3-million-point cloud with
   bloom is a genuine continuous GPU workload — exactly the kind of thing the GB10
   is justified by — and it runs token-less and offline, matching the resilience
   theme (pull the network cable and it still draws).

4. **Provenance that fits "you can't fake a number."** It's built only from open,
   attributable sources (EA LIDAR + OSM). Nothing is invented; the geometry is the
   real city.

5. **Demo and stakeholder impact.** A cyberpunk 3D digital twin is dramatically more
   compelling than a flat map for judges and non-technical stakeholders — it makes
   the "digital twin of the Square Mile" claim legible in one look.

6. **Complementary, not a replacement.** It's a *toggle*, not a takeover. The map
   stays the tool for routing and precise ops interaction (clicking couriers,
   reading congestion); the twin is the tool for spatial context, briefing, and
   impact. Operators pick the right lens for the task.

## Honest trade-offs

- **Heavyweight assets** (~38 MB) and a 3M-point draw — great on a real GPU, sluggish
  under headless software rendering. It's opt-in via the toggle for that reason.
- **Not a precise interaction surface.** The map is still better for clicking
  individual entities and reading exact positions; the twin is for context and
  presence, not pixel-accurate selection.
- **Static geometry.** The cloud is a fixed 2020 survey snapshot; only the overlaid
  beams are live. It conveys *space*, while the map conveys *operations*.

## Where it lives

- `src/components/CityScene.tsx` — the R3F scene (cloud loader, beams, scanner, post).
- `src/lib/pointcloud.ts` — facade / fallback point-cloud builders.
- `src/lib/scene-geo.ts` — lat/lon → local-metre projection (Bank origin).
- `src/App.tsx` — the Map ⇄ LiDAR 3D view toggle.
- `public/citycloud.{bin,json}`, `public/citybuildings.json` — baked assets.
