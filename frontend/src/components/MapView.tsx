// The live operations map — "Direction C" clean dark mission-control basemap.
//
// Token-less MapLibre dark basemap (or Mapbox dark-v11 when VITE_MAPBOX_TOKEN is
// set) + a deck.gl overlay. NO grid / no 3D terrain — the map is a clean dark
// canvas with a soft glowing Thames.
//
// Layers (deck.gl, via MapboxOverlay):
//   - CONGESTION ROADS  — roads.geojson LineStrings coloured by congestion
//                         (lime→amber→red), Waze-style glowing lines; segments near
//                         live /congestion hotspots are thickened/reddened.
//   - ROUTES            — courier plans that FOLLOW THE ROAD NETWORK via the Mapbox
//                         Directions API (falls back to the straight stop polyline);
//                         drawn Google-Maps style: NEUTRAL grey-blue for free-flowing
//                         segments, RED where the path passes live congestion. The
//                         selected courier's route is brightened; others are dimmed.
//   - JOB NODES         — pickup (priority colour, ring) + dropoff (lime) glowing dots.
//   - COURIERS          — glowing markers, status colour, moving along the road path.
//   - DISRUPTIONS       — pulsing markers; a red ✕ glyph for road closures.
//   - DISTRICT LABELS   — static muted London place names for atmosphere.

import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import mapboxgl from "mapbox-gl";
import { MapboxOverlay } from "@deck.gl/mapbox";
import type { Layer, PickingInfo } from "@deck.gl/core";
import { ScatterplotLayer, PathLayer, TextLayer, IconLayer } from "@deck.gl/layers";
import { useStore } from "../store";
import type {
  CctvCamera,
  CongestionCell,
  CongestionField,
  Courier,
  DeliveryJob,
  DisruptionEvent,
  Location,
  Plan,
  SignalRec,
} from "../types";
import {
  COURIER_RGB,
  DISRUPTION_CLASS_RGB,
  PRIORITY_RGB,
  ROUTE_CONGESTED_RGB,
  ROUTE_HIGHLIGHT_RGB,
  ROUTE_NEUTRAL_RGB,
  congestionRGB,
  facilityRGB,
  signalActionRGB,
} from "../lib/palette";
import {
  fetchOptionalJson,
  parseRoads,
  type RoadPath,
} from "../lib/geojson";
import {
  classifyDisruption,
  fetchOptional,
  parseEventVenues,
  parseFacilities,
  type EventVenue,
  type Facility,
} from "../lib/datasets";
import { getRoadRoute, routeSignature, clearRouteCache, type LngLat, type RoadGeom } from "../lib/routing";
import { sticker, vehicleEmoji, pickupEmoji, dropoffEmoji, facilityEmoji } from "../lib/emojiMarkers";

// Waze-style live-traffic colour for a Mapbox congestion_numeric value (0–100).
// -1 (unknown) returns null so the caller uses the neutral free-flow colour.
function wazeRGB(c: number): [number, number, number] | null {
  if (c < 0) return null;
  if (c < 35) return [80, 200, 120]; // free — green
  if (c < 60) return [242, 194, 26]; // moderate — yellow
  if (c < 80) return [230, 140, 40]; // heavy — orange
  return [232, 60, 50]; // severe — red
}

// Interpolate a position a fraction `f` (0..1) along a polyline by cumulative length.
function posAlong(coords: LngLat[], f: number): LngLat {
  if (coords.length < 2) return coords[0] ?? [0, 0];
  const segLen: number[] = [];
  let total = 0;
  for (let i = 0; i < coords.length - 1; i++) {
    const dx = coords[i + 1][0] - coords[i][0];
    const dy = coords[i + 1][1] - coords[i][1];
    const d = Math.hypot(dx, dy);
    segLen.push(d);
    total += d;
  }
  if (total === 0) return coords[0];
  let want = Math.max(0, Math.min(1, f)) * total;
  for (let i = 0; i < segLen.length; i++) {
    if (want <= segLen[i]) {
      const t = segLen[i] === 0 ? 0 : want / segLen[i];
      return [
        coords[i][0] + (coords[i + 1][0] - coords[i][0]) * t,
        coords[i][1] + (coords[i + 1][1] - coords[i][1]) * t,
      ];
    }
    want -= segLen[i];
  }
  return coords[coords.length - 1];
}

// Stable 0..1 offset per courier so the fleet doesn't move in lock-step.
function courierOffset(id: string): number {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) % 997;
  return h / 997;
}

// Realistic cruise speed per vehicle (m/s). Driving the animation off a constant speed
// (period ∝ actual path length) means a courier on a long route no longer blurs across
// London faster than one on a short hop — they all move at a believable pace.
const SPEED_MPS: Record<string, number> = { van: 8, scooter: 9, bike: 5 }; // ~29/32/18 km/h
const MIN_TRAVERSE_S = 150; // floor so very short paths don't teleport

// Approximate polyline length in metres (London-local equirectangular projection).
function pathMeters(coords: LngLat[]): number {
  if (coords.length < 2) return 0;
  const kLat = 111_320;
  const kLng = 111_320 * Math.cos((coords[0][1] * Math.PI) / 180);
  let m = 0;
  for (let i = 0; i < coords.length - 1; i++) {
    const dLng = (coords[i + 1][0] - coords[i][0]) * kLng;
    const dLat = (coords[i + 1][1] - coords[i][1]) * kLat;
    m += Math.hypot(dLng, dLat);
  }
  return m;
}

// Animated demo position: progress the courier along its road-following path at a
// vehicle-appropriate pace. Ping-pongs (start→end→start) so there's no teleport
// jump at the loop boundary. Falls back to the courier's static location.
function courierAnimPos(
  c: Courier,
  roadPaths: Record<string, RoadGeom | null>,
  tSec: number,
): [number, number] {
  const road = roadPaths[c.id];
  if (road && road.coords.length >= 2 && c.status !== "offline" && c.status !== "idle") {
    const speed = SPEED_MPS[c.vehicle_type ?? "van"] ?? 8;
    // One-way traversal time at a constant realistic speed (floored for tiny paths).
    const period = Math.max(MIN_TRAVERSE_S, pathMeters(road.coords) / speed);
    const u = (tSec / period + courierOffset(c.id)) % 2; // 0..2
    const f = u <= 1 ? u : 2 - u; // triangle wave → smooth out-and-back
    return posAlong(road.coords, f);
  }
  return [c.location.lng, c.location.lat];
}
import { getTheme, onThemeChange, type Theme } from "../lib/theme";
import {
  getRouteSource,
  onRouteSourceChange,
  type RouteSource,
} from "../lib/routeSource";
import {
  mdiTrafficLight,
  mdiCarMultiple,
  mdiRoutes,
  mdiAlertOutline,
  mdiCctv,
  mdiCrosshairsGps,
  mdiPlus,
  mdiMinus,
  mdiAirFilter,
  mdiTrafficCone,
  mdiWaves,
  mdiBike,
  mdiWeatherPouring,
  mdiCarBrakeAlert,
  mdiCrane,
  mdiCalendarClock,
} from "@mdi/js";

// Civic real-data feeds (published to /data/*.json by data/build.py).
interface AirBorough { id: string; name: string; lat: number; lng: number; aqi: number }
interface PointFeature { id: string; description: string; lat: number; lng: number; severity?: string }
interface PlanningApp { id: string; description: string; lat: number; lng: number; scale?: string; authority?: string; status?: string; category?: string }
interface Condition { id: string; category: string; title: string; severity: string; starts?: string | null; ends?: string | null; lat: number; lng: number; source?: string }
interface CycleStation { id: string; name: string; lat: number; lng: number; capacity: number }
interface CycleHighway { id: string; name: string; geometry: { lat: number; lng: number }[] }
interface LoadingZone {
  id: string;
  name: string;
  lat: number;
  lng: number;
  restriction: string;
  max_stay_min: number;
  clinical_priority: string;
}
interface RoadSign {
  id: string;
  name: string;
  lat: number;
  lng: number;
  message: string;
  severity: "low" | "moderate" | "severe";
}

// Inline Material Design icon (24×24 path data from @mdi/js).
function McIcon({ path, size = 18 }: { path: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden focusable="false">
      <path fill="currentColor" d={path} />
    </svg>
  );
}

// Lower pitch than before (~0–30°, near top-down) so road-following routes read.
const INITIAL_VIEW = {
  center: [-0.095, 51.508] as [number, number],
  zoom: 12.1,
  pitch: 24,
  bearing: 0,
};

const MAPBOX_TOKEN = (import.meta.env.VITE_MAPBOX_TOKEN ?? "").trim();
const USE_MAPBOX = MAPBOX_TOKEN.length > 0;
const MAPBOX_STYLE_DARK = "mapbox://styles/mapbox/dark-v11";
const MAPBOX_STYLE_LIGHT = "mapbox://styles/mapbox/light-v11";
const mapboxStyleFor = (theme: Theme) => (theme === "light" ? MAPBOX_STYLE_LIGHT : MAPBOX_STYLE_DARK);

// Calm Command basemap: CARTO dark_all (charcoal) or light_all (cream) raster,
// swapped live when the dark/light theme toggles.
const CARTO_TILES = (theme: Theme) => {
  const variant = theme === "light" ? "light_all" : "dark_all";
  return ["a", "b", "c"].map((s) => `https://${s}.basemaps.cartocdn.com/${variant}/{z}/{x}/{y}.png`);
};
const MAP_BG = (theme: Theme) => (theme === "light" ? "#e9ded0" : "#0e0d0c");

const mapStyle = (theme: Theme): maplibregl.StyleSpecification => ({
  version: 8,
  sources: {
    carto: {
      type: "raster",
      tiles: CARTO_TILES(theme),
      tileSize: 256,
      attribution: "© OpenStreetMap contributors © CARTO",
    },
  },
  layers: [
    { id: "bg", type: "background", paint: { "background-color": MAP_BG(theme) } },
    { id: "carto", type: "raster", source: "carto" },
  ],
});

// RainViewer precipitation radar (open, NO API key). The index lists past radar
// frames; we render the most recent as a semi-transparent raster overlay. Returns
// a ready-to-use tile URL template, or null on any failure (degrades to no radar).
const RAINVIEWER_INDEX = "https://api.rainviewer.com/public/weather-maps.json";
async function fetchLatestRadarTileUrl(): Promise<string | null> {
  try {
    const res = await fetch(RAINVIEWER_INDEX);
    if (!res.ok) return null;
    const data = (await res.json()) as { host?: string; radar?: { past?: { path?: string }[] } };
    const host = data.host;
    const past = data.radar?.past ?? [];
    const path = past.length ? past[past.length - 1]?.path : undefined;
    if (!host || !path) return null;
    // {host}{path}/256/{z}/{x}/{y}/2/1_1.png — 256px tiles, scheme 2 (colour), smoothed+snow.
    return `${host}${path}/256/{z}/{x}/{y}/2/1_1.png`;
  } catch {
    return null;
  }
}

// Static London district labels — atmosphere, drawn muted/uppercase.
const DISTRICTS: { name: string; lng: number; lat: number }[] = [
  { name: "ISLINGTON", lng: -0.103, lat: 51.538 },
  { name: "SHOREDITCH", lng: -0.078, lat: 51.526 },
  { name: "THE CITY", lng: -0.092, lat: 51.5155 },
  { name: "WESTMINSTER", lng: -0.135, lat: 51.4995 },
  { name: "SOUTHWARK", lng: -0.09, lat: 51.5015 },
  { name: "CANARY WHARF", lng: -0.019, lat: 51.505 },
  { name: "GREENWICH", lng: -0.0095, lat: 51.4825 },
];

// Toggleable layers shown in the left control stack.
type LayerKey = "congestion" | "routes" | "incidents" | "signals" | "cctv" | "air" | "roadworks" | "kerb" | "roadsigns" | "flood" | "cycle" | "weather" | "hazards" | "planning" | "conditions";
type LayerVis = Record<LayerKey, boolean>;

const DEFAULT_VIS: LayerVis = {
  congestion: false, // "Traffic" grid — default OFF (keep the map clean)
  routes: true,
  incidents: true,
  signals: true, // GB10 Nemotron signal recs — default ON
  cctv: false, // live CCTV cameras — default OFF to keep the map clean
  air: false, // London air quality (LAQN) — default OFF
  roadworks: true, // planned works — default ON for the first-60-second story
  kerb: true, // medical loading/handoff points — default ON
  roadsigns: true, // TfL variable-message signs — default ON
  flood: false, // EA flood warnings — default OFF
  cycle: false, // TfL cycle infra + hire — default OFF
  weather: false, // RainViewer precipitation radar — default OFF
  hazards: false, // TfL live road disruptions/hazards — default OFF
  planning: false, // major developments (planning) — default OFF
  conditions: false, // merged upcoming-conditions feed — default OFF
};

// Cap on simultaneously rendered camera icons so a dense viewport never clutters.
const CCTV_RENDER_CAP = 80;

interface Snapshot {
  jobs: DeliveryJob[];
  couriers: Courier[];
  plan: Plan | null;
  disruptions: DisruptionEvent[];
  congestion: CongestionField;
  signalRecs: SignalRec[];
  cctv: CctvCamera[];
  selectedCourierId: string | null;
  focusJobId: string | null;
  // The just-created delivery's own road geometry, drawn as a dedicated clean
  // blue route (and dimming the fleet). null = not active.
  focusRoute: { lat: number; lng: number }[] | null;
  // Optimized stops for the focus route (origin + drops in visit order), drawn as
  // numbered waypoint markers on top of the blue route. null = not active.
  focusStops: { name: string; lat: number; lng: number }[] | null;
}

// Map viewport bounds [west, south, east, north]; null until the map first moves.
type Bounds = [number, number, number, number] | null;

interface OptionalData {
  roads: RoadPath[];
  facilities: Facility[];
  venues: EventVenue[];
  air: AirBorough[];
  roadworks: PointFeature[];
  kerb: LoadingZone[];
  roadsigns: RoadSign[];
  floods: PointFeature[];
  cycleStations: CycleStation[];
  cycleHighways: CycleHighway[];
  hazards: PointFeature[];
  planning: PlanningApp[];
  conditions: Condition[];
}

const EMPTY_OPTIONAL: OptionalData = {
  roads: [], facilities: [], venues: [],
  air: [], roadworks: [], kerb: [], roadsigns: [], floods: [], cycleStations: [], cycleHighways: [],
  hazards: [], planning: [], conditions: [],
};

const EMPTY_SNAP: Snapshot = {
  jobs: [],
  couriers: [],
  plan: null,
  disruptions: [],
  congestion: { cells: [] },
  signalRecs: [],
  cctv: [],
  selectedCourierId: null,
  focusJobId: null,
  focusRoute: null,
  focusStops: null,
};

// Short uppercase glyph per signal action for the on-map label.
const SIGNAL_ACTION_LABEL: Record<string, string> = {
  green_wave: "GREEN WAVE",
  retime: "RETIME",
  hold: "HOLD",
  clear: "CLEAR",
};

// Ordered stop coords for a route (courier start + stops in sequence), de-duped.
function routeStopCoords(plan: Plan | null, courier: Courier | undefined, courierId: string): LngLat[] {
  const route = plan?.routes?.find((r) => r.courier_id === courierId);
  if (!route) return [];
  const stops = [...(route.stops ?? [])].sort((a, b) => a.sequence - b.sequence);
  const coords: LngLat[] = [];
  if (courier?.location) coords.push([courier.location.lng, courier.location.lat]);
  for (const s of stops) {
    if (s.location) coords.push([s.location.lng, s.location.lat]);
  }
  // de-dup consecutive identical points
  const out: LngLat[] = [];
  for (const c of coords) {
    const last = out[out.length - 1];
    if (!last || last[0] !== c[0] || last[1] !== c[1]) out.push(c);
  }
  return out;
}

// Straight fallback path from the plan's decoded polyline, else the raw stop coords.
function fallbackPath(plan: Plan | null, courierId: string, stopCoords: LngLat[]): LngLat[] {
  const route = plan?.routes?.find((r) => r.courier_id === courierId);
  if (route?.polyline && route.polyline.length >= 2) {
    return route.polyline.map((p) => [p.lng, p.lat] as LngLat);
  }
  return stopCoords;
}

// Congestion "source" points used to colour route segments red: live hotspot
// cells plus the midpoints of high-congestion road segments (roads.geojson). A
// route segment whose midpoint sits within ~SEG_RADIUS of any source reads as
// congested; everything else stays neutral grey-blue.
const SEG_RADIUS = 0.0032; // ~320 m in lng/lat degrees near London
const SEG_R2 = SEG_RADIUS * SEG_RADIUS;

let _srcCache: { key: string; pts: [number, number][] } | null = null;
function congestionSources(roads: RoadPath[], cells: CongestionCell[], stamp: string): [number, number][] {
  const key = `${stamp}:${roads.length}:${cells.length}`;
  if (_srcCache && _srcCache.key === key) return _srcCache.pts;
  const pts: [number, number][] = [];
  for (const c of cells) if (c.congestion >= 0.55) pts.push([c.lng, c.lat]);
  for (const r of roads) {
    if (r.congestion >= 0.75) {
      const mid = r.path[Math.floor(r.path.length / 2)] ?? r.path[0];
      pts.push(mid);
    }
  }
  _srcCache = { key, pts };
  return pts;
}

// True when a segment a→b passes through congestion (midpoint near a source).
function segmentCongested(a: LngLat, b: LngLat, sources: [number, number][]): boolean {
  const mx = (a[0] + b[0]) / 2;
  const my = (a[1] + b[1]) / 2;
  for (const s of sources) {
    const dx = mx - s[0];
    const dy = my - s[1];
    if (dx * dx + dy * dy < SEG_R2) return true;
  }
  return false;
}

// Boost road congestion near live hotspot cells (Waze-style "live" colouring).
// Memoised by the congestion stamp so the per-frame render loop reuses a stable
// array reference (deck.gl then skips re-uploading 586 paths every frame).
let _enhCache: { key: string; roads: RoadPath[] } | null = null;
function enhanceRoadsMemo(roads: RoadPath[], cells: CongestionCell[], stamp: string): RoadPath[] {
  const key = `${stamp}:${roads.length}:${cells.length}`;
  if (_enhCache && _enhCache.key === key) return _enhCache.roads;
  const out = enhanceRoads(roads, cells);
  _enhCache = { key, roads: out };
  return out;
}
function enhanceRoads(roads: RoadPath[], cells: CongestionCell[]): RoadPath[] {
  const hotspots = cells.filter((c) => c.congestion >= 0.55).slice(0, 48);
  if (!hotspots.length) return roads;
  const R2 = 0.0035 * 0.0035; // ~350 m
  return roads.map((r) => {
    const mid = r.path[Math.floor(r.path.length / 2)] ?? r.path[0];
    let boost = 0;
    for (const h of hotspots) {
      const dx = mid[0] - h.lng;
      const dy = mid[1] - h.lat;
      if (dx * dx + dy * dy < R2) boost = Math.max(boost, h.congestion);
    }
    return boost > r.congestion ? { ...r, congestion: r.congestion * 0.4 + boost * 0.6 } : r;
  });
}

// Build short dash segments along a→b so a connector reads as a dashed line.
function dashSegments(a: LngLat, b: LngLat, dash = 0.0009, gap = 0.0007): LngLat[][] {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len = Math.hypot(dx, dy);
  if (len === 0) return [];
  const ux = dx / len;
  const uy = dy / len;
  const segs: LngLat[][] = [];
  let t = 0;
  while (t < len) {
    const s: LngLat = [a[0] + ux * t, a[1] + uy * t];
    const e = Math.min(t + dash, len);
    const f: LngLat = [a[0] + ux * e, a[1] + uy * e];
    segs.push([s, f]);
    t += dash + gap;
  }
  return segs;
}

// Cameras inside the current viewport (bounds), capped so a dense area never clutters.
function visibleCams(cams: CctvCamera[], bounds: Bounds): CctvCamera[] {
  if (!cams.length) return [];
  let inView = cams;
  if (bounds) {
    const [w, s, e, n] = bounds;
    inView = cams.filter((c) => c.lng >= w && c.lng <= e && c.lat >= s && c.lat <= n);
  }
  return inView.length > CCTV_RENDER_CAP ? inView.slice(0, CCTV_RENDER_CAP) : inView;
}

function buildLayers(
  snap: Snapshot,
  data: OptionalData,
  vis: LayerVis,
  phase: number,
  roadPaths: Record<string, RoadGeom | null>,
  bounds: Bounds,
  tSec: number,
): Layer[] {
  const { jobs, couriers, plan, disruptions, congestion, signalRecs, cctv, selectedCourierId, focusJobId, focusRoute, focusStops } = snap;
  const layers: Layer[] = [];

  // A dedicated delivery route is active when /intake handed us ≥2 road points.
  // While active, the fleet routes dim hard and only the blue A→B line stands out.
  const focusRouteActive = !!focusRoute && focusRoute.length >= 2;
  const courierById = new Map(couriers.map((c) => [c.id, c]));

  // The courier whose route serves the just-created (focused) job, if any.
  const focusedCourierId =
    focusJobId != null
      ? plan?.routes?.find((r) => (r.stops ?? []).some((s) => s.job_id === focusJobId))
          ?.courier_id ?? null
      : null;
  // A route is "highlighted" (vivid blue) when it's the selected OR the focused one.
  const isHighlighted = (courierId: string) =>
    courierId === selectedCourierId || courierId === focusedCourierId;

  // 1. Congestion-as-roads — glowing Waze-style coloured network.
  if (vis.congestion && data.roads.length) {
    const roads = enhanceRoadsMemo(data.roads, congestion.cells, congestion.generated_at ?? "static");
    layers.push(
      new PathLayer<RoadPath>({
        id: "congestion-roads-glow",
        data: roads,
        getPath: (d) => d.path,
        getColor: (d) => [...congestionRGB(d.congestion), 70] as [number, number, number, number],
        getWidth: (d) => 3 + d.congestion * 5,
        widthUnits: "pixels",
        capRounded: true,
        jointRounded: true,
        updateTriggers: { getColor: congestion.generated_at, getWidth: congestion.generated_at },
      }),
    );
    layers.push(
      new PathLayer<RoadPath>({
        id: "congestion-roads",
        data: roads,
        getPath: (d) => d.path,
        getColor: (d) => [...congestionRGB(d.congestion), 205] as [number, number, number, number],
        getWidth: (d) => 1.2 + d.congestion * 2.4,
        widthUnits: "pixels",
        capRounded: true,
        jointRounded: true,
        pickable: true,
        updateTriggers: { getColor: congestion.generated_at, getWidth: congestion.generated_at },
      }),
    );
  }

  // 2. Routes — road-following geometry (Directions API) or straight fallback,
  //    coloured Google-Maps style: NEUTRAL grey-blue, RED through congestion.
  // Click-to-select dimming (connectors / job nodes / courier markers below).
  const selActive = selectedCourierId != null;
  // Any route in "highlighted" focus (a selected courier or a freshly-created job)?
  const highlightActive = selectedCourierId != null || focusedCourierId != null;
  const congSources = congestionSources(data.roads, congestion.cells, congestion.generated_at ?? "static");

  interface RouteLine { courier_id: string; highlighted: boolean; path: LngLat[]; congestion: number[] | null }
  const routeLines = (plan?.routes ?? [])
    .map((r): RouteLine | null => {
      const courier = courierById.get(r.courier_id);
      const stopCoords = routeStopCoords(plan, courier, r.courier_id);
      if (stopCoords.length < 2) return null;
      const road = roadPaths[r.courier_id];
      const onRoad = road && road.coords.length >= 2;
      const path = onRoad ? road!.coords : fallbackPath(plan, r.courier_id, stopCoords);
      if (path.length < 2) return null;
      return {
        courier_id: r.courier_id,
        highlighted: isHighlighted(r.courier_id),
        path,
        congestion: onRoad ? road!.congestion : null,
      };
    })
    .filter((r): r is RouteLine => r !== null);

  // One record per drawn segment so each carries its own live-traffic colour.
  // `cong` is Mapbox congestion_numeric (0–100) when road-following, else -1 and we
  // fall back to our own congestion sources (binary neutral/red).
  interface RouteSeg { courier_id: string; highlighted: boolean; cong: number; congested: boolean; path: LngLat[] }
  const routeSegs: RouteSeg[] = [];
  for (const rl of routeLines) {
    for (let i = 0; i < rl.path.length - 1; i++) {
      const a = rl.path[i];
      const b = rl.path[i + 1];
      const cong = rl.congestion ? (rl.congestion[i] ?? -1) : -1;
      routeSegs.push({
        courier_id: rl.courier_id,
        highlighted: rl.highlighted,
        cong,
        congested: cong >= 0 ? cong >= 60 : segmentCongested(a, b, congSources),
        path: [a, b],
      });
    }
  }

  // Alpha ramps: when a route is highlighted, it brightens and the rest dim away.
  // When a dedicated delivery (focus) route is active, ALL fleet segments dim
  // hard so only the standalone blue A→B line reads.
  const segGlowAlpha = (s: RouteSeg) =>
    focusRouteActive ? 10 : !highlightActive ? 60 : s.highlighted ? 130 : 16;
  const segMainAlpha = (s: RouteSeg) =>
    focusRouteActive ? 28 : !highlightActive ? 215 : s.highlighted ? 255 : 55;
  // Highlighted (focused/selected) routes render in vivid blue for clarity; every
  // other route uses the live Waze traffic colour when available, else the
  // neutral/red congestion fallback.
  const segColor = (s: RouteSeg): [number, number, number] =>
    s.highlighted
      ? (ROUTE_HIGHLIGHT_RGB as [number, number, number])
      : (wazeRGB(s.cong) ?? (s.congested ? ROUTE_CONGESTED_RGB : ROUTE_NEUTRAL_RGB));

  if (vis.routes && routeSegs.length) {
    layers.push(
      new PathLayer<RouteSeg>({
        id: "routes-glow",
        data: routeSegs,
        getPath: (d) => d.path,
        getColor: (d) => [...segColor(d), segGlowAlpha(d)] as [number, number, number, number],
        getWidth: (d) => (d.highlighted ? 18 : 10),
        widthUnits: "pixels",
        capRounded: true,
        jointRounded: true,
        updateTriggers: {
          getColor: [selectedCourierId, focusedCourierId, focusRouteActive],
          getWidth: [selectedCourierId, focusedCourierId, focusRouteActive],
        },
      }),
    );
    layers.push(
      new PathLayer<RouteSeg>({
        id: "routes",
        data: routeSegs,
        getPath: (d) => d.path,
        getColor: (d) => [...segColor(d), segMainAlpha(d)] as [number, number, number, number],
        getWidth: (d) => (d.highlighted ? 6.5 : 3.4),
        widthUnits: "pixels",
        capRounded: true,
        jointRounded: true,
        pickable: true,
        updateTriggers: {
          getColor: [selectedCourierId, focusedCourierId, focusRouteActive],
          getWidth: [selectedCourierId, focusedCourierId, focusRouteActive],
        },
      }),
    );
    // (Removed the animated "trip-head" dots that raced along every route — they read as
    // noise / made it look like nothing was settling. Routes are static lines; the courier
    // markers below show real position.)
  }

  // 2b. FOCUS ROUTE — the just-created delivery's OWN clean pickup→dropoff line,
  //     traced along real London streets (from /intake). Drawn vivid blue, thick,
  //     full alpha, ON TOP of the (dimmed) fleet routes so it's unmistakable.
  if (vis.routes && focusRouteActive && focusRoute) {
    const focusPath: LngLat[] = focusRoute.map((p) => [p.lng, p.lat] as LngLat);
    const focusData = [{ path: focusPath }];
    layers.push(
      new PathLayer<(typeof focusData)[number]>({
        id: "focus-route-glow",
        data: focusData,
        getPath: (d) => d.path,
        getColor: [...ROUTE_HIGHLIGHT_RGB, 90] as [number, number, number, number],
        getWidth: 18,
        widthUnits: "pixels",
        capRounded: true,
        jointRounded: true,
        updateTriggers: { getPath: focusRoute },
      }),
    );
    layers.push(
      new PathLayer<(typeof focusData)[number]>({
        id: "focus-route",
        data: focusData,
        getPath: (d) => d.path,
        getColor: [...ROUTE_HIGHLIGHT_RGB, 255] as [number, number, number, number],
        getWidth: 6,
        widthUnits: "pixels",
        capRounded: true,
        jointRounded: true,
        updateTriggers: { getPath: focusRoute },
      }),
    );

    // 2c. FOCUS STOPS — numbered waypoint markers at the optimized visit stops
    //     (origin + drops in order). Drawn on top of the blue route so a multi-hop
    //     delivery reads clearly. Falls back to the route's endpoints when the
    //     store didn't supply stops. The origin (index 0) gets a brighter ring.
    const stops: { name: string; lat: number; lng: number }[] =
      focusStops && focusStops.length
        ? focusStops
        : [
            { name: "origin", lat: focusRoute[0].lat, lng: focusRoute[0].lng },
            {
              name: "destination",
              lat: focusRoute[focusRoute.length - 1].lat,
              lng: focusRoute[focusRoute.length - 1].lng,
            },
          ];
    const stopPts = stops.map((s, i) => ({ ...s, _t: "focusStop" as const, index: i }));
    layers.push(
      new ScatterplotLayer<(typeof stopPts)[number]>({
        id: "focus-stops",
        data: stopPts,
        getPosition: (d) => [d.lng, d.lat],
        getRadius: 11,
        radiusUnits: "pixels",
        radiusMinPixels: 9,
        stroked: true,
        lineWidthMinPixels: 2,
        getLineColor: [232, 237, 230, 255],
        getFillColor: (d) =>
          d.index === 0
            ? ([...ROUTE_HIGHLIGHT_RGB, 255] as [number, number, number, number])
            : ([...ROUTE_HIGHLIGHT_RGB, 200] as [number, number, number, number]),
        pickable: true,
        updateTriggers: { getPosition: focusStops, getFillColor: focusStops },
      }),
    );
    layers.push(
      new TextLayer<(typeof stopPts)[number]>({
        id: "focus-stops-label",
        data: stopPts,
        getPosition: (d) => [d.lng, d.lat],
        // Origin shows "S" (start); subsequent drops are numbered 1, 2, 3…
        getText: (d) => (d.index === 0 ? "S" : String(d.index)),
        getSize: 12,
        getColor: [5, 9, 11, 255],
        fontWeight: 700,
        getTextAnchor: "middle",
        getAlignmentBaseline: "center",
        characterSet: "auto",
        fontSettings: { sdf: true },
        updateTriggers: { getText: focusStops, getPosition: focusStops },
      }),
    );
  }

  // 3. Dashed connectors from each courier to its next stop (neutral; dimmed off-selection).
  if (vis.routes) {
    const connectors: { path: LngLat[]; selected: boolean }[] = [];
    for (const r of plan?.routes ?? []) {
      const courier = courierById.get(r.courier_id);
      if (!courier?.location) continue;
      const next = [...(r.stops ?? [])].sort((a, b) => a.sequence - b.sequence)[0];
      if (!next?.location) continue;
      const a: LngLat = [courier.location.lng, courier.location.lat];
      const b: LngLat = [next.location.lng, next.location.lat];
      const selected = r.courier_id === selectedCourierId;
      for (const seg of dashSegments(a, b)) connectors.push({ path: seg, selected });
    }
    if (connectors.length) {
      layers.push(
        new PathLayer<(typeof connectors)[number]>({
          id: "courier-connectors",
          data: connectors,
          getPath: (d) => d.path,
          getColor: (d) =>
            [...ROUTE_NEUTRAL_RGB, !selActive ? 150 : d.selected ? 190 : 30] as [number, number, number, number],
          getWidth: 1.4,
          widthUnits: "pixels",
          updateTriggers: { getColor: selectedCourierId },
        }),
      );
    }
  }

  // 4. Job nodes — pickup (priority colour + ring) and dropoff (lime) glowing dots.
  //    Jobs not served by the selected courier dim away while a route is selected.
  if (vis.routes) {
    const selectedJobIds = new Set<string>();
    if (selActive) {
      const selRoute = plan?.routes?.find((r) => r.courier_id === selectedCourierId);
      for (const s of selRoute?.stops ?? []) selectedJobIds.add(s.job_id);
    }
    // Emoji "sticker" pins: white teardrop + accent ring (priority for pickups,
    // lime for dropoffs) with the job-type glyph inside. Jobs not on the selected
    // courier's route fade into a dimmed layer.
    type JobNode = { job: DeliveryJob; loc: Location };
    const isDim = (jobId: string) => selActive && !selectedJobIds.has(jobId);
    const DROP_RGB: [number, number, number] = [191, 227, 107];
    const pickIcon = (d: JobNode) => sticker(pickupEmoji(d.job.type), PRIORITY_RGB[d.job.priority], true);
    const dropIcon = (d: JobNode) => sticker(dropoffEmoji(d.job.type), DROP_RGB, true);
    const jobLayer = (
      id: string,
      rows: JobNode[],
      getIcon: (d: JobNode) => ReturnType<typeof sticker>,
      dim: boolean,
    ) =>
      new IconLayer<JobNode>({
        id,
        data: rows,
        getPosition: (d) => [d.loc.lng, d.loc.lat],
        getIcon,
        getSize: 34,
        sizeUnits: "pixels",
        sizeMinPixels: 22,
        sizeMaxPixels: 48,
        opacity: dim ? 0.22 : 1,
        pickable: !dim,
        updateTriggers: { getIcon: selectedCourierId },
      });
    const pickups: JobNode[] = jobs.map((j) => ({ job: j, loc: j.origin }));
    const drops: JobNode[] = jobs.map((j) => ({ job: j, loc: j.destination }));
    const pickDim = pickups.filter((d) => isDim(d.job.id));
    const dropDim = drops.filter((d) => isDim(d.job.id));
    if (dropDim.length) layers.push(jobLayer("job-drops-dim", dropDim, dropIcon, true));
    if (pickDim.length) layers.push(jobLayer("job-pickups-dim", pickDim, pickIcon, true));
    layers.push(jobLayer("job-drops", drops.filter((d) => !isDim(d.job.id)), dropIcon, false));
    layers.push(jobLayer("job-pickups", pickups.filter((d) => !isDim(d.job.id)), pickIcon, false));
  }

  // 5. NHS facilities — subtle emoji sticker badges (🏥/🔬/🩺/🩹/💊), ring by type.
  if (data.facilities.length) {
    layers.push(
      new IconLayer<Facility>({
        id: "facilities",
        data: data.facilities,
        getPosition: (f) => [f.lng, f.lat],
        getIcon: (f) => sticker(facilityEmoji(f.type), facilityRGB(f.type), false),
        getSize: 26,
        sizeUnits: "pixels",
        sizeMinPixels: 16,
        sizeMaxPixels: 34,
        opacity: 0.95,
        pickable: true,
      }),
    );
  }

  // 6. (Random driver/probe dots removed — drivers still feed congestion server-side.)

  // 7. Couriers — glowing markers, colour by status; selected gets a halo.
  layers.push(
    new ScatterplotLayer<Courier>({
      id: "couriers-glow",
      data: couriers,
      getPosition: (c) => courierAnimPos(c, roadPaths, tSec),
      getRadius: 280,
      radiusUnits: "meters",
      radiusMinPixels: 12,
      radiusMaxPixels: 38,
      getFillColor: (c) =>
        [...(COURIER_RGB[c.status] ?? [200, 200, 200]), c.id === selectedCourierId ? 90 : selActive ? 14 : 45] as [number, number, number, number],
      updateTriggers: { getFillColor: selectedCourierId, getPosition: tSec },
    }),
  );
  // Vehicle emoji "sticker" badge: white round badge + status-coloured ring with the
  // 🚚/🛵/🚲 glyph. The selected courier is enlarged; the rest fade into a dimmed layer
  // while a route is selected (IconLayer can't tint full-colour emoji, so we dim via opacity).
  const courierIconLayer = (id: string, rows: Courier[], dim: boolean) =>
    new IconLayer<Courier>({
      id,
      data: rows,
      getPosition: (c) => courierAnimPos(c, roadPaths, tSec),
      getIcon: (c) => sticker(vehicleEmoji(c.vehicle_type), COURIER_RGB[c.status] ?? [200, 200, 200], false),
      getSize: (c) => (c.id === selectedCourierId ? 46 : 36),
      sizeUnits: "pixels",
      sizeMinPixels: 24,
      sizeMaxPixels: 56,
      opacity: dim ? 0.35 : 1,
      pickable: !dim,
      updateTriggers: { getIcon: selectedCourierId, getSize: selectedCourierId, getPosition: tSec },
    });
  const courierDim = selActive ? couriers.filter((c) => c.id !== selectedCourierId) : [];
  const courierLit = selActive ? couriers.filter((c) => c.id === selectedCourierId) : couriers;
  if (courierDim.length) layers.push(courierIconLayer("couriers-dim", courierDim, true));
  layers.push(courierIconLayer("couriers", courierLit, false));

  // 8. Disruptions — pulsing markers; red ✕ glyph for road closures.
  if (vis.incidents) {
    const disrPts = disruptions
      .map((d) => ({ ev: d, c: classifyDisruption(d, data.venues) }))
      .filter((x): x is { ev: DisruptionEvent; c: NonNullable<ReturnType<typeof classifyDisruption>> } => x.c !== null)
      .map((x) => ({ ...x.c, _t: "disr" as const, isClosure: x.ev.kind === "road_closure" }));
    if (disrPts.length) {
      const pulse = 0.5 + 0.5 * Math.sin(phase * Math.PI * 2);
      layers.push(
        new ScatterplotLayer<(typeof disrPts)[number]>({
          id: "disruptions-pulse",
          data: disrPts,
          getPosition: (d) => [d.lng, d.lat],
          getRadius: 160 + pulse * 200,
          radiusUnits: "meters",
          radiusMinPixels: 9,
          radiusMaxPixels: 44,
          getFillColor: (d) =>
            [...(DISRUPTION_CLASS_RGB[d.cls] ?? DISRUPTION_CLASS_RGB.manual), Math.round(35 + pulse * 55)] as [number, number, number, number],
          updateTriggers: { getRadius: phase, getFillColor: phase },
        }),
      );
      const closures = disrPts.filter((d) => d.isClosure);
      const others = disrPts.filter((d) => !d.isClosure);
      if (others.length) {
        layers.push(
          new ScatterplotLayer<(typeof others)[number]>({
            id: "disruptions",
            data: others,
            getPosition: (d) => [d.lng, d.lat],
            getRadius: 120,
            radiusUnits: "meters",
            radiusMinPixels: 6,
            radiusMaxPixels: 18,
            stroked: true,
            lineWidthMinPixels: 2,
            getLineColor: [232, 237, 230, 230],
            getFillColor: (d) =>
              [...(DISRUPTION_CLASS_RGB[d.cls] ?? DISRUPTION_CLASS_RGB.manual), 190] as [number, number, number, number],
            pickable: true,
          }),
        );
      }
      if (closures.length) {
        layers.push(
          new TextLayer<(typeof closures)[number]>({
            id: "disruptions-closure",
            data: closures,
            getPosition: (d) => [d.lng, d.lat],
            getText: () => "✕",
            getSize: 22,
            getColor: [255, 77, 77, 255],
            fontWeight: 700,
            getTextAnchor: "middle",
            getAlignmentBaseline: "center",
            pickable: true,
          }),
        );
      }
    }
  }

  // 8b. Signal recs — GB10 Nemotron traffic-signal recommendations. A pulsing
  //     halo + solid ring marker at each junction, coloured by action, with a
  //     small uppercase action label. Toggleable via the "Signals" control.
  if (vis.signals && signalRecs.length) {
    const sigPts = signalRecs.map((r) => ({ ...r, _t: "signal" as const }));
    const pulse = 0.5 + 0.5 * Math.sin(phase * Math.PI * 2);
    layers.push(
      new ScatterplotLayer<(typeof sigPts)[number]>({
        id: "signal-recs-glow",
        data: sigPts,
        getPosition: (d) => [d.lng, d.lat],
        getRadius: 150 + pulse * 150,
        radiusUnits: "meters",
        radiusMinPixels: 10,
        radiusMaxPixels: 40,
        getFillColor: (d) =>
          [...signalActionRGB(d.action), Math.round(30 + pulse * 50)] as [number, number, number, number],
        updateTriggers: { getRadius: phase, getFillColor: phase },
      }),
    );
    layers.push(
      new ScatterplotLayer<(typeof sigPts)[number]>({
        id: "signal-recs",
        data: sigPts,
        getPosition: (d) => [d.lng, d.lat],
        getRadius: 9,
        radiusUnits: "pixels",
        radiusMinPixels: 7,
        stroked: true,
        lineWidthMinPixels: 2.5,
        getLineColor: (d) => [...signalActionRGB(d.action), 255] as [number, number, number, number],
        getFillColor: (d) => [...signalActionRGB(d.action), 70] as [number, number, number, number],
        pickable: true,
      }),
    );
    layers.push(
      new TextLayer<(typeof sigPts)[number]>({
        id: "signal-recs-label",
        data: sigPts,
        getPosition: (d) => [d.lng, d.lat],
        getText: (d) => SIGNAL_ACTION_LABEL[d.action] ?? d.action.toUpperCase(),
        getSize: 10,
        getColor: (d) => [...signalActionRGB(d.action), 255] as [number, number, number, number],
        fontWeight: 700,
        getTextAnchor: "middle",
        getAlignmentBaseline: "top",
        getPixelOffset: [0, 12],
        characterSet: "auto",
        fontSettings: { sdf: true },
        outlineWidth: 2,
        outlineColor: [5, 9, 11, 220],
        pickable: true,
      }),
    );
  }

  // 8c. Live CCTV cameras — small clickable markers (default OFF). Only the cams in
  //     the current viewport are drawn, capped, so a dense area never clutters.
  if (vis.cctv && cctv.length) {
    const cams = visibleCams(cctv, bounds).map((c) => ({ ...c, _t: "cctv" as const }));
    if (cams.length) {
      layers.push(
        new ScatterplotLayer<(typeof cams)[number]>({
          id: "cctv-cams",
          data: cams,
          getPosition: (d) => [d.lng, d.lat],
          getRadius: 7,
          radiusUnits: "pixels",
          radiusMinPixels: 6,
          radiusMaxPixels: 10,
          stroked: true,
          lineWidthMinPixels: 1.5,
          getLineColor: [232, 237, 230, 235],
          getFillColor: [100, 210, 255, 150],
          pickable: true,
        }),
      );
      layers.push(
        new TextLayer<(typeof cams)[number]>({
          id: "cctv-cams-glyph",
          data: cams,
          getPosition: (d) => [d.lng, d.lat],
          getText: () => "▣",
          getSize: 11,
          getColor: [5, 9, 11, 255],
          fontWeight: 700,
          getTextAnchor: "middle",
          getAlignmentBaseline: "center",
          characterSet: "auto",
          fontSettings: { sdf: true },
          pickable: true,
        }),
      );
    }
  }

  // 9. District labels — static muted atmosphere.
  layers.push(
    new TextLayer<(typeof DISTRICTS)[number]>({
      id: "district-labels",
      data: DISTRICTS,
      getPosition: (d) => [d.lng, d.lat],
      getText: (d) => d.name,
      getSize: 11,
      getColor: [126, 138, 130, 150],
      fontWeight: 600,
      getTextAnchor: "middle",
      getAlignmentBaseline: "center",
      characterSet: "auto",
      fontSettings: { sdf: true },
      outlineWidth: 2,
      outlineColor: [5, 9, 11, 200],
    }),
  );

  // ---- Civic real-data overlays (toggleable, default off) ------------------
  // Air quality — borough AQI dots (green=good → red=poor; AQI 1–10).
  if (vis.air && data.air.length) {
    const aqiRGB = (a: number): [number, number, number] =>
      a <= 3 ? [80, 200, 120] : a <= 6 ? [242, 194, 26] : a <= 8 ? [230, 140, 40] : [232, 60, 50];
    layers.push(
      new ScatterplotLayer<AirBorough>({
        id: "air-quality",
        data: data.air,
        getPosition: (d) => [d.lng, d.lat],
        getRadius: 380,
        radiusUnits: "meters",
        radiusMinPixels: 10,
        getFillColor: (d) => [...aqiRGB(d.aqi), 70] as [number, number, number, number],
        getLineColor: (d) => [...aqiRGB(d.aqi), 220] as [number, number, number, number],
        lineWidthMinPixels: 1.5,
        stroked: true,
        pickable: true,
      }),
    );
  }

  // Roadworks — TfL streetworks closures (amber cones).
  if (vis.roadworks && data.roadworks.length) {
    layers.push(
      new ScatterplotLayer<PointFeature>({
        id: "roadworks",
        data: data.roadworks,
        getPosition: (d) => [d.lng, d.lat],
        getRadius: 7,
        radiusUnits: "pixels",
        getFillColor: [230, 140, 40, 230],
        getLineColor: [20, 14, 4, 255],
        lineWidthMinPixels: 1.5,
        stroked: true,
        pickable: true,
      }),
    );
  }

  // Kerbside handoff/loading zones — legal stop points that make routing operational.
  if (vis.kerb && data.kerb.length) {
    layers.push(
      new ScatterplotLayer<LoadingZone>({
        id: "kerbside-loading",
        data: data.kerb,
        getPosition: (d) => [d.lng, d.lat],
        getRadius: (d) => (d.clinical_priority === "stat" ? 10 : 8),
        radiusUnits: "pixels",
        getFillColor: (d) =>
          d.clinical_priority === "stat"
            ? [232, 60, 50, 240]
            : d.clinical_priority === "urgent"
              ? [242, 194, 26, 230]
              : [80, 200, 120, 210],
        getLineColor: [255, 255, 255, 230],
        lineWidthMinPixels: 1.5,
        stroked: true,
        pickable: true,
      }),
    );
  }

  // TfL roadside Variable Message Signs — the human-readable reason for a reroute.
  if (vis.roadsigns && data.roadsigns.length) {
    layers.push(
      new ScatterplotLayer<RoadSign>({
        id: "roadside-signs",
        data: data.roadsigns,
        getPosition: (d) => [d.lng, d.lat],
        getRadius: (d) => (d.severity === "severe" ? 11 : 8),
        radiusUnits: "pixels",
        getFillColor: (d) =>
          d.severity === "severe"
            ? [232, 60, 50, 245]
            : d.severity === "moderate"
              ? [230, 140, 40, 230]
              : [80, 200, 120, 210],
        getLineColor: [8, 8, 8, 255],
        lineWidthMinPixels: 2,
        stroked: true,
        pickable: true,
      }),
    );
  }

  // Flood warnings — Environment Agency (blue).
  if (vis.flood && data.floods.length) {
    layers.push(
      new ScatterplotLayer<PointFeature>({
        id: "flood",
        data: data.floods,
        getPosition: (d) => [d.lng, d.lat],
        getRadius: 9,
        radiusUnits: "pixels",
        getFillColor: [60, 150, 230, 230],
        getLineColor: [10, 30, 60, 255],
        lineWidthMinPixels: 1.5,
        stroked: true,
        pickable: true,
      }),
    );
  }

  // Road hazards — TfL live road disruptions the driver should avoid
  // (accidents, closures, obstructions), coloured by severity with a ✕ glyph
  // for severe ones so a closure reads at a glance.
  if (vis.hazards && data.hazards.length) {
    const hazards = data.hazards.map((h) => ({ ...h, _t: "hazard" as const }));
    const hazardRGB = (s?: string): [number, number, number] =>
      s === "severe" ? [232, 60, 50] : s === "moderate" ? [230, 140, 40] : [242, 194, 26];
    layers.push(
      new ScatterplotLayer<(typeof hazards)[number]>({
        id: "hazards",
        data: hazards,
        getPosition: (d) => [d.lng, d.lat],
        getRadius: (d) => (d.severity === "severe" ? 11 : 8),
        radiusUnits: "pixels",
        getFillColor: (d) => [...hazardRGB(d.severity), 235] as [number, number, number, number],
        getLineColor: [20, 8, 4, 255],
        lineWidthMinPixels: 2,
        stroked: true,
        pickable: true,
      }),
    );
    const severe = hazards.filter((h) => h.severity === "severe");
    if (severe.length) {
      layers.push(
        new TextLayer<(typeof severe)[number]>({
          id: "hazards-severe-glyph",
          data: severe,
          getPosition: (d) => [d.lng, d.lat],
          getText: () => "✕",
          getSize: 16,
          getColor: [255, 240, 235, 255],
          fontWeight: 700,
          getTextAnchor: "middle",
          getAlignmentBaseline: "center",
          characterSet: "auto",
          fontSettings: { sdf: true },
          pickable: true,
        }),
      );
    }
  }

  // Major developments (planning) — diamond markers flagging future road impact.
  if (vis.planning && data.planning.length) {
    const apps = data.planning.map((p) => ({ ...p, _t: "planning" as const }));
    layers.push(
      new ScatterplotLayer<(typeof apps)[number]>({
        id: "planning",
        data: apps,
        getPosition: (d) => [d.lng, d.lat],
        getRadius: (d) => (d.scale === "major" ? 12 : 9),
        radiusUnits: "pixels",
        getFillColor: [156, 102, 224, 220], // violet — distinct from hazards/works
        getLineColor: [24, 12, 40, 255],
        lineWidthMinPixels: 2,
        stroked: true,
        pickable: true,
      }),
    );
  }

  // Upcoming conditions — the merged forward-looking feed, coloured by severity.
  if (vis.conditions && data.conditions.length) {
    const conds = data.conditions.map((c) => ({ ...c, _t: "condition" as const }));
    const condRGB = (s?: string): [number, number, number] =>
      s === "severe" ? [232, 60, 50] : s === "moderate" ? [230, 140, 40] : [60, 170, 120];
    layers.push(
      new ScatterplotLayer<(typeof conds)[number]>({
        id: "conditions",
        data: conds,
        getPosition: (d) => [d.lng, d.lat],
        getRadius: 9,
        radiusUnits: "pixels",
        getFillColor: (d) => [...condRGB(d.severity), 210] as [number, number, number, number],
        getLineColor: [12, 20, 16, 255],
        lineWidthMinPixels: 2,
        stroked: true,
        pickable: true,
      }),
    );
  }

  // Cycle infrastructure — superhighways (cyan paths) + hire docks (small dots).
  if (vis.cycle) {
    if (data.cycleHighways.length) {
      layers.push(
        new PathLayer<CycleHighway>({
          id: "cycle-highways",
          data: data.cycleHighways,
          getPath: (d) => d.geometry.map((p) => [p.lng, p.lat] as LngLat),
          getColor: [70, 200, 210, 200],
          getWidth: 3,
          widthUnits: "pixels",
          capRounded: true,
          jointRounded: true,
          pickable: true,
        }),
      );
    }
    if (data.cycleStations.length) {
      layers.push(
        new ScatterplotLayer<CycleStation>({
          id: "cycle-stations",
          data: data.cycleStations,
          getPosition: (d) => [d.lng, d.lat],
          getRadius: 4,
          radiusUnits: "pixels",
          getFillColor: [70, 200, 210, 220],
          getLineColor: [10, 40, 42, 255],
          lineWidthMinPixels: 1,
          stroked: true,
          pickable: true,
        }),
      );
    }
  }

  return layers;
}

// Tooltip dispatcher.
function tooltipFor({ object }: PickingInfo): { html: string; className: string } | null {
  if (!object) return null;
  const o = object as Record<string, unknown>;
  if (o._t === "disr") {
    const d = object as { label: string; cls: string };
    return { className: "deck-tip", html: `<b>${d.label}</b><br/><span class="tip-dim">${d.cls} disruption</span>` };
  }
  if (o._t === "signal") {
    const s = object as SignalRec;
    const conf = `${Math.round((s.confidence ?? 0) * 100)}%`;
    const act = (SIGNAL_ACTION_LABEL[s.action] ?? s.action).toUpperCase();
    return {
      className: "deck-tip",
      html: `<b>${s.name} <span style="text-transform:uppercase">[${act}]</span></b><br/>${s.detail ?? ""}<br/><span class="tip-dim">Nemotron@GB10 · conf ${conf}</span>`,
    };
  }
  if (o._t === "cctv") {
    const c = object as CctvCamera;
    return { className: "deck-tip", html: `<b>${c.name}</b><br/><span class="tip-dim">live CCTV · click to view</span>` };
  }
  if (o._t === "focusStop") {
    const s = object as { name: string; index: number };
    const tag = s.index === 0 ? "pickup" : `stop ${s.index}`;
    return { className: "deck-tip", html: `<b>${s.name}</b><br/><span class="tip-dim">${tag} · optimized route</span>` };
  }
  if (o._t === "hazard") {
    const h = object as PointFeature & { category?: string };
    return {
      className: "deck-tip",
      html: `<b>${h.description}</b><br/><span class="tip-dim">TfL road hazard · ${h.category ?? "disruption"} · ${h.severity ?? "moderate"}</span>`,
    };
  }
  if (o._t === "planning") {
    const p = object as PlanningApp;
    return {
      className: "deck-tip",
      html: `<b>${p.description}</b><br/><span class="tip-dim">${p.authority ?? "LPA"} · ${p.scale ?? "major"} development · ${p.status ?? "pending"}</span>`,
    };
  }
  if (o._t === "condition") {
    const c = object as Condition;
    const when = c.starts ? new Date(c.starts).toLocaleString("en-GB", { hour12: false }).slice(0, 17) : "ongoing";
    return {
      className: "deck-tip",
      html: `<b>${c.title}</b><br/><span class="tip-dim">${c.category} · ${c.severity} · ${when}</span>`,
    };
  }
  if ("restriction" in o && "max_stay_min" in o) {
    const k = object as LoadingZone;
    return {
      className: "deck-tip",
      html: `<b>${k.name}</b><br/>${k.restriction} · ${k.max_stay_min} min<br/><span class="tip-dim">${k.clinical_priority.toUpperCase()} handoff zone</span>`,
    };
  }
  if ("message" in o && "severity" in o && "lat" in o && "lng" in o) {
    const s = object as RoadSign;
    return {
      className: "deck-tip",
      html: `<b>${s.name}</b><br/>${s.message}<br/><span class="tip-dim">TfL roadside sign · ${s.severity}</span>`,
    };
  }
  if ("congestion" in o && "path" in o) {
    const r = object as RoadPath;
    return { className: "deck-tip", html: `<b>Traffic ${(r.congestion * 100).toFixed(0)}%</b><br/><span class="tip-dim">road segment</span>` };
  }
  if ("type" in o && "lat" in o && "lng" in o && "name" in o && !("status" in o)) {
    const f = object as Facility;
    return { className: "deck-tip", html: `<b>${f.name}</b><br/><span class="tip-dim">${f.type} · ${f.id}</span>` };
  }
  if ("status" in o && "location" in o) {
    const c = object as Courier;
    return { className: "deck-tip", html: `<b>${c.name ?? c.id}</b><br/><span class="tip-dim">courier · ${c.status}</span>` };
  }
  if ("job" in o) {
    const e = object as { job: DeliveryJob; loc: { name?: string } };
    return {
      className: "deck-tip",
      html: `<b>${e.job.id} <span style="text-transform:uppercase">[${e.job.priority}]</span></b><br/>${e.loc?.name ?? e.job.origin.name ?? "?"}`,
    };
  }
  if ("courier_id" in o && "path" in o) {
    const seg = object as { courier_id: string; congested?: boolean };
    return {
      className: "deck-tip",
      html: `<b>route · ${seg.courier_id}</b><br/><span class="tip-dim">${seg.congested ? "congested stretch" : "free-flowing"}</span>`,
    };
  }
  return null;
}

const LEFT_LAYERS: { key: LayerKey; label: string; icon: string; testid: string }[] = [
  { key: "congestion", label: "Traffic", icon: mdiCarMultiple, testid: "layer-toggle-congestion" },
  { key: "routes", label: "Routes", icon: mdiRoutes, testid: "layer-toggle-routes" },
  { key: "incidents", label: "Incidents", icon: mdiAlertOutline, testid: "layer-toggle-incidents" },
  { key: "signals", label: "Signals", icon: mdiTrafficLight, testid: "layer-toggle-signals" },
  { key: "cctv", label: "CCTV", icon: mdiCctv, testid: "layer-toggle-cctv" },
  { key: "air", label: "Air quality", icon: mdiAirFilter, testid: "layer-toggle-air" },
  { key: "roadworks", label: "Roadworks", icon: mdiTrafficCone, testid: "layer-toggle-roadworks" },
  { key: "kerb", label: "Kerb", icon: mdiCrosshairsGps, testid: "layer-toggle-kerb" },
  { key: "roadsigns", label: "Signs", icon: mdiAlertOutline, testid: "layer-toggle-roadsigns" },
  { key: "flood", label: "Flood", icon: mdiWaves, testid: "layer-toggle-flood" },
  { key: "cycle", label: "Cycle", icon: mdiBike, testid: "layer-toggle-cycle" },
  { key: "weather", label: "Weather", icon: mdiWeatherPouring, testid: "layer-toggle-weather" },
  { key: "hazards", label: "Hazards", icon: mdiCarBrakeAlert, testid: "layer-toggle-hazards" },
  { key: "conditions", label: "Upcoming", icon: mdiCalendarClock, testid: "layer-toggle-conditions" },
  { key: "planning", label: "Works", icon: mdiCrane, testid: "layer-toggle-planning" },
];

export default function MapView() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | mapboxgl.Map | null>(null);
  const overlayRef = useRef<MapboxOverlay | null>(null);
  const phaseRef = useRef(0);
  const rafRef = useRef<number | null>(null);
  const snapRef = useRef<Snapshot>(EMPTY_SNAP);
  const dataRef = useRef<OptionalData>(EMPTY_OPTIONAL);
  const visRef = useRef<LayerVis>(DEFAULT_VIS);
  const roadPathsRef = useRef<Record<string, RoadGeom | null>>({});
  const routeSourceRef = useRef<RouteSource>(getRouteSource());
  const resolveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const boundsRef = useRef<Bounds>(null);
  // Set by an effect; the once-created overlay onClick calls it to open the popover.
  const selectCamRef = useRef<((cam: CctvCamera, x: number, y: number) => void) | null>(null);

  const [optional, setOptional] = useState<OptionalData>(EMPTY_OPTIONAL);
  const [vis, setVis] = useState<LayerVis>(DEFAULT_VIS);
  const [counts, setCounts] = useState({ jobs: 0, couriers: 0, routes: 0, congestion: 0, disruptions: 0, signals: 0 });
  // Open CCTV popover: the picked camera + its on-screen pixel position + a refresh tick.
  const [activeCam, setActiveCam] = useState<{ cam: CctvCamera; x: number; y: number } | null>(null);
  const [imgTick, setImgTick] = useState(0);

  const selectCourier = useStore((s) => s.selectCourier);

  // Bridge the imperative overlay click → React state for the CCTV popover.
  useEffect(() => {
    selectCamRef.current = (cam, x, y) => {
      setActiveCam({ cam, x, y });
      setImgTick(0);
    };
    return () => {
      selectCamRef.current = null;
    };
  }, []);

  // While the popover is open, cache-bust the live still every ~10s.
  useEffect(() => {
    if (!activeCam) return;
    const t = window.setInterval(() => setImgTick((n) => n + 1), 10000);
    return () => window.clearInterval(t);
  }, [activeCam]);

  const toggle = (key: LayerKey) => setVis((v) => ({ ...v, [key]: !v[key] }));

  // Debounced road-route resolver: signature-cached Directions API calls; results
  // land in roadPathsRef and are picked up by the imperative render loop.
  const resolveRoutes = useMemo(() => {
    const run = () => {
      // In "valhalla" mode the ROUTES layer draws straight from each
      // route.polyline (the backend road-following geometry) — no Mapbox calls.
      // buildLayers falls back to that polyline when roadPaths has no entry.
      if (routeSourceRef.current === "valhalla") {
        roadPathsRef.current = {};
        return;
      }
      const snap = snapRef.current;
      const courierById = new Map(snap.couriers.map((c) => [c.id, c]));
      const next: Record<string, RoadGeom | null> = {};
      for (const r of snap.plan?.routes ?? []) {
        const coords = routeStopCoords(snap.plan, courierById.get(r.courier_id), r.courier_id);
        if (coords.length < 2) continue;
        const sig = routeSignature(r.courier_id, coords);
        // getRoadRoute returns cached geometry or kicks off a fetch (re-resolve on done).
        next[r.courier_id] = getRoadRoute(sig, coords, schedule);
      }
      roadPathsRef.current = next;
    };
    const schedule = () => {
      if (resolveTimer.current) clearTimeout(resolveTimer.current);
      resolveTimer.current = setTimeout(run, 450);
    };
    return schedule;
  }, []);

  // Refresh live traffic colours periodically (Waze-style realtime) — drop the
  // route geometry cache so the next resolve re-fetches current Mapbox congestion.
  useEffect(() => {
    const t = window.setInterval(() => {
      clearRouteCache();
      resolveRoutes();
    }, 120_000);
    return () => window.clearInterval(t);
  }, [resolveRoutes]);

  // Keep refs in sync with the store; trigger route resolution when the plan changes.
  useEffect(() => {
    let lastPlanAt = "";
    const update = () => {
      const s = useStore.getState();
      const jobs = Object.values(s.jobs);
      const couriers = Object.values(s.couriers);
      snapRef.current = {
        jobs,
        couriers,
        plan: s.plan,
        disruptions: s.disruptions,
        congestion: s.congestion,
        signalRecs: s.signalRecs,
        cctv: s.cctv,
        selectedCourierId: s.selectedCourierId,
        focusJobId: s.focusJobId,
        focusRoute: s.focusRoute,
        focusStops: s.focusStops,
      };
      setCounts({
        jobs: jobs.length,
        couriers: couriers.length,
        routes: s.plan?.routes?.length ?? 0,
        congestion: s.congestion.cells.length,
        disruptions: s.disruptions.length,
        signals: s.signalRecs.length,
      });
      const planAt = s.plan?.generated_at ?? "";
      if (planAt !== lastPlanAt) {
        lastPlanAt = planAt;
        resolveRoutes();
      }
    };
    update();
    return useStore.subscribe(update);
  }, [resolveRoutes]);

  useEffect(() => {
    dataRef.current = optional;
    resolveRoutes();
  }, [optional, resolveRoutes]);
  useEffect(() => {
    visRef.current = vis;
  }, [vis]);

  // Re-resolve route geometry when the Mapbox/Valhalla source toggle changes.
  // The RAF render loop reads roadPathsRef each frame, so the ROUTES layer
  // re-draws from the new source on the next frame.
  useEffect(() => {
    routeSourceRef.current = getRouteSource();
    resolveRoutes();
    return onRouteSourceChange((source) => {
      routeSourceRef.current = source;
      resolveRoutes();
    });
  }, [resolveRoutes]);

  // When a new delivery focus route arrives (from /intake), frame it so the clean
  // blue A→B line is centred. Fits the route's bounds; no-op while none is active.
  useEffect(() => {
    let prev: { lat: number; lng: number }[] | null = null;
    const fit = (pts: { lat: number; lng: number }[]) => {
      const m = mapRef.current;
      if (!m || pts.length < 2) return;
      let w = Infinity, s = Infinity, e = -Infinity, n = -Infinity;
      for (const p of pts) {
        if (p.lng < w) w = p.lng;
        if (p.lng > e) e = p.lng;
        if (p.lat < s) s = p.lat;
        if (p.lat > n) n = p.lat;
      }
      if (!Number.isFinite(w) || !Number.isFinite(n)) return;
      try {
        m.fitBounds(
          [[w, s], [e, n]],
          { padding: 120, duration: 900, maxZoom: 14.5 },
        );
      } catch {
        /* map not ready — non-fatal */
      }
    };
    const route = useStore.getState().focusRoute;
    if (route && route.length >= 2) fit(route);
    prev = route;
    return useStore.subscribe(() => {
      const next = useStore.getState().focusRoute;
      if (next !== prev) {
        prev = next;
        if (next && next.length >= 2) fit(next);
      }
    });
  }, []);

  // "View route" action (Inspector 〰) → fly the map to the selected courier.
  useEffect(() => {
    const onFocus = (e: Event) => {
      const id = (e as CustomEvent).detail as string;
      const c = useStore.getState().couriers[id];
      const m = mapRef.current;
      if (c?.location && m) {
        m.flyTo({ center: [c.location.lng, c.location.lat], zoom: 13.5, duration: 800 });
      }
    };
    window.addEventListener("rlj:focus-courier", onFocus);
    return () => window.removeEventListener("rlj:focus-courier", onFocus);
  }, []);

  // Load optional datasets once (each degrades gracefully on 404 / empty).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [roadsGj, facRaw, evtRaw, aqRaw, swRaw, kerbRaw, signsRaw, fldRaw, cycRaw, hazRaw, plnRaw, cndRaw] = await Promise.all([
        fetchOptionalJson("/data/roads.geojson"),
        fetchOptional<unknown>("/data/facilities.json"),
        fetchOptional<unknown>("/data/events.json"),
        fetchOptional<{ boroughs?: AirBorough[] }>("/data/airquality.json"),
        fetchOptional<{ streetworks?: PointFeature[] }>("/data/streetworks.json"),
        fetchOptional<{ loading_zones?: LoadingZone[] }>("/data/kerbside.json"),
        fetchOptional<{ signs?: RoadSign[] }>("/data/roadsigns.json"),
        fetchOptional<{ floods?: PointFeature[] }>("/data/floodwarnings.json"),
        fetchOptional<{ stations?: CycleStation[]; highways?: CycleHighway[] }>("/data/cycleinfra.json"),
        fetchOptional<{ hazards?: PointFeature[] }>("/data/hazards.json"),
        fetchOptional<{ applications?: PlanningApp[] }>("/data/planning.json"),
        fetchOptional<{ conditions?: Condition[] }>("/data/conditions.json"),
      ]);
      if (cancelled) return;
      const roads = parseRoads(roadsGj);
      const facilities = parseFacilities(facRaw);
      const venues = parseEventVenues(evtRaw);
      const air = aqRaw?.boroughs ?? [];
      const roadworks = swRaw?.streetworks ?? [];
      const kerb = kerbRaw?.loading_zones ?? [];
      const roadsigns = signsRaw?.signs ?? [];
      const floods = fldRaw?.floods ?? [];
      const cycleStations = cycRaw?.stations ?? [];
      const cycleHighways = cycRaw?.highways ?? [];
      const hazards = hazRaw?.hazards ?? [];
      const planning = plnRaw?.applications ?? [];
      const conditions = cndRaw?.conditions ?? [];
      setOptional({ roads, facilities, venues, air, roadworks, kerb, roadsigns, floods, cycleStations, cycleHighways, hazards, planning, conditions });
      const loaded: string[] = [];
      if (roads.length) loaded.push(`${roads.length} roads`);
      if (facilities.length) loaded.push(`${facilities.length} facilities`);
      if (venues.length) loaded.push(`${venues.length} event venues`);
      if (air.length) loaded.push(`${air.length} AQ boroughs`);
      if (roadworks.length) loaded.push(`${roadworks.length} roadworks`);
      if (kerb.length) loaded.push(`${kerb.length} kerb handoffs`);
      if (roadsigns.length) loaded.push(`${roadsigns.length} roadside signs`);
      if (floods.length) loaded.push(`${floods.length} flood warnings`);
      if (cycleHighways.length) loaded.push(`${cycleHighways.length} cycle routes`);
      if (hazards.length) loaded.push(`${hazards.length} road hazards`);
      if (planning.length) loaded.push(`${planning.length} major works`);
      if (conditions.length) loaded.push(`${conditions.length} upcoming conditions`);
      if (loaded.length) {
        useStore.getState().pushLog({
          level: "info",
          source: "system",
          message: `Map datasets loaded: ${loaded.join(", ")}.`,
        });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Weather radar (RainViewer) — add/remove a semi-transparent precipitation
  // raster overlay on the basemap when the "Weather" layer is toggled. It sits
  // above the basemap but BELOW the deck.gl courier/route overlay (a separate
  // canvas control), and degrades to nothing if the RainViewer fetch fails.
  useEffect(() => {
    const SRC = "rainviewer-src";
    const LYR = "rainviewer-layer";
    const m = mapRef.current as maplibregl.Map | null;
    if (!m) return;
    let cancelled = false;

    const removeRadar = () => {
      try {
        if (m.getLayer(LYR)) m.removeLayer(LYR);
        if (m.getSource(SRC)) m.removeSource(SRC);
      } catch {
        /* layer/source absent — non-fatal */
      }
    };

    if (!vis.weather) {
      removeRadar();
      return;
    }

    const addRadar = async () => {
      const tile = await fetchLatestRadarTileUrl();
      if (cancelled || !tile) return; // fetch failed → simply no radar
      const apply = () => {
        try {
          removeRadar();
          m.addSource(SRC, {
            type: "raster",
            tiles: [tile],
            tileSize: 256,
            attribution: "© RainViewer",
          });
          m.addLayer({ id: LYR, type: "raster", source: SRC, paint: { "raster-opacity": 0.6 } });
        } catch {
          /* style not ready / add failed — non-fatal */
        }
      };
      if (m.isStyleLoaded()) apply();
      else m.once("load", apply);
    };

    void addRadar();
    // Optional refresh: pull a fresh radar frame every 5 minutes while enabled.
    const t = window.setInterval(() => void addRadar(), 5 * 60_000);
    return () => {
      cancelled = true;
      window.clearInterval(t);
      removeRadar();
    };
  }, [vis.weather]);

  // Swap the basemap live when the dark/light theme toggles. CARTO raster tiles
  // (tokenless path) swap in place; Mapbox falls back to a full setStyle.
  useEffect(() => {
    return onThemeChange((theme) => {
      const m = mapRef.current as maplibregl.Map | undefined;
      if (!m) return;
      if (USE_MAPBOX) {
        try {
          (m as unknown as mapboxgl.Map).setStyle(mapboxStyleFor(theme));
        } catch {
          /* style swap unavailable — non-fatal */
        }
        return;
      }
      try {
        const src = m.getSource("carto") as maplibregl.RasterTileSource | undefined;
        src?.setTiles?.(CARTO_TILES(theme));
        m.setPaintProperty("bg", "background-color", MAP_BG(theme));
      } catch {
        /* source not ready — non-fatal */
      }
    });
  }, []);

  // Init map + overlay once.
  useEffect(() => {
    if (!containerRef.current) return;

    const theme0 = getTheme();
    let map: maplibregl.Map | mapboxgl.Map;
    if (USE_MAPBOX) {
      mapboxgl.accessToken = MAPBOX_TOKEN;
      map = new mapboxgl.Map({
        container: containerRef.current,
        style: mapboxStyleFor(theme0),
        center: INITIAL_VIEW.center,
        zoom: INITIAL_VIEW.zoom,
        pitch: INITIAL_VIEW.pitch,
        bearing: INITIAL_VIEW.bearing,
        attributionControl: true,
        antialias: true,
      });
    } else {
      map = new maplibregl.Map({
        container: containerRef.current,
        style: mapStyle(theme0),
        center: INITIAL_VIEW.center,
        zoom: INITIAL_VIEW.zoom,
        pitch: INITIAL_VIEW.pitch,
        bearing: INITIAL_VIEW.bearing,
        attributionControl: { compact: true },
      });
    }
    mapRef.current = map;

    const m = map as maplibregl.Map;

    // Keep the viewport bounds current so the CCTV layer only draws cams in view.
    const syncBounds = () => {
      const b = m.getBounds();
      boundsRef.current = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
    };
    m.on("move", syncBounds);

    m.on("load", () => {
      syncBounds();
      // Tint the Thames into a soft glowing blue ribbon (mapbox dark-v11 has water).
      if (USE_MAPBOX) {
        try {
          const style = m.getStyle();
          for (const lyr of style?.layers ?? []) {
            if (lyr.id === "water" || lyr.id.startsWith("water")) {
              if (lyr.type === "fill") m.setPaintProperty(lyr.id, "fill-color", "#12324a");
            }
          }
        } catch {
          /* style not ready / layer absent — non-fatal */
        }
      }
      m.easeTo({ zoom: INITIAL_VIEW.zoom + 0.25, duration: 1800, pitch: INITIAL_VIEW.pitch });
    });

    const overlay = new MapboxOverlay({
      interleaved: false,
      layers: [],
      onClick: (info: PickingInfo) => {
        const o = info.object as Record<string, unknown> | null;
        if (o && o._t === "cctv") {
          selectCamRef.current?.(o as unknown as CctvCamera, info.x ?? 0, info.y ?? 0);
          return;
        }
        if (o && "status" in o && "location" in o) {
          selectCourier((o as unknown as Courier).id);
        }
      },
      getTooltip: tooltipFor,
    });
    m.addControl(overlay);
    overlayRef.current = overlay;

    let last = performance.now();
    let elapsed = 0; // monotonic seconds, drives courier movement along roads
    const LOOP_SECONDS = 14;
    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      elapsed += dt;
      phaseRef.current = (phaseRef.current + dt / LOOP_SECONDS) % 1;
      overlay.setProps({
        layers: buildLayers(
          snapRef.current,
          dataRef.current,
          visRef.current,
          phaseRef.current,
          roadPathsRef.current,
          boundsRef.current,
          elapsed,
        ),
      });
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      m.remove();
      mapRef.current = null;
      overlayRef.current = null;
    };
  }, [selectCourier]);

  // Left control-stack actions.
  const zoomBy = (delta: number) => {
    const m = mapRef.current as maplibregl.Map | null;
    if (m) m.easeTo({ zoom: m.getZoom() + delta, duration: 300 });
  };
  const recenter = () => {
    const m = mapRef.current as maplibregl.Map | null;
    if (m) m.easeTo({ center: INITIAL_VIEW.center, zoom: INITIAL_VIEW.zoom, pitch: INITIAL_VIEW.pitch, bearing: 0, duration: 700 });
  };

  const trafficOn = optional.roads.length > 0 && vis.congestion;

  return (
    <div className="map-wrap">
      <div ref={containerRef} className="map-root" />

      {/* Left layer dock — slim icon rail that expands on hover (MD icons). */}
      <div className="layer-dock glass" data-testid="layers-panel">
        {LEFT_LAYERS.map((l) => {
          const on = !!vis[l.key];
          return (
            <button
              key={l.key}
              type="button"
              className={`ld-item ${on ? "on" : ""}`}
              data-testid={l.testid}
              data-on={on ? "true" : "false"}
              title={l.label}
              onClick={() => toggle(l.key)}
            >
              <span className="ld-icon"><McIcon path={l.icon} /></span>
              <span className="ld-label">{l.label}</span>
              <span className={`ld-led ${on ? "on" : ""}`} />
            </button>
          );
        })}
        <div className="ld-divider" />
        <button type="button" className="ld-item ctrl" title="Recenter" onClick={recenter}>
          <span className="ld-icon"><McIcon path={mdiCrosshairsGps} /></span>
          <span className="ld-label">Recenter</span>
        </button>
        <button type="button" className="ld-item ctrl" title="Zoom in" onClick={() => zoomBy(0.6)}>
          <span className="ld-icon"><McIcon path={mdiPlus} /></span>
          <span className="ld-label">Zoom in</span>
        </button>
        <button type="button" className="ld-item ctrl" title="Zoom out" onClick={() => zoomBy(-0.6)}>
          <span className="ld-icon"><McIcon path={mdiMinus} /></span>
          <span className="ld-label">Zoom out</span>
        </button>
      </div>

      {/* Markers legend — what the on-map emoji stickers + ring colours mean. */}
      <div className="marker-legend glass" data-testid="marker-legend">
        <div className="ml-title">Markers</div>
        <div className="ml-row"><span className="ml-emoji">🚚</span><span className="ml-emoji">🛵</span><span className="ml-emoji">🚲</span><span className="ml-text">couriers</span></div>
        <div className="ml-row"><span className="ml-emoji">🩸</span><span className="ml-emoji">💊</span><span className="ml-text">pickup</span></div>
        <div className="ml-row"><span className="ml-emoji">🔬</span><span className="ml-emoji">🏥</span><span className="ml-text">dropoff</span></div>
        <div className="ml-row ml-rings">
          <span className="ml-dot" style={{ background: "rgb(255,77,77)" }} />stat
          <span className="ml-dot" style={{ background: "rgb(224,162,58)" }} />urgent
          <span className="ml-dot" style={{ background: "rgb(159,184,90)" }} />routine
        </div>
        <div className="ml-hint">ring colour = priority / status</div>
      </div>

      {/* Route/layer status — kept for tests + at-a-glance health */}
      <div
        className="route-status"
        data-testid="route-layer-status"
        data-route-count={counts.routes}
        data-traffic={trafficOn ? "on" : "off"}
        data-congestion={counts.congestion}
        data-signals={counts.signals}
      >
        <span className="rs-led" />
        {`routes:${counts.routes} · cong:${counts.congestion} · traffic:${trafficOn ? optional.roads.length : "off"} · sig:${counts.signals}`}
      </div>

      {/* Observable marker for the signal-recs layer (test hook). */}
      <div
        data-testid="signal-recs-layer"
        data-count={counts.signals}
        data-on={vis.signals ? "true" : "false"}
        hidden
      />

      {/* Observable marker for the CCTV layer (test hook). */}
      <div
        data-testid="cctv-layer"
        data-on={vis.cctv ? "true" : "false"}
        hidden
      />

      {/* Live CCTV popover — opens on camera click; image refreshes every ~10s. */}
      {activeCam && (
        <div
          className="cctv-popover glass"
          data-testid="cctv-popover"
          style={{
            left: Math.max(12, Math.min(activeCam.x + 14, (containerRef.current?.clientWidth ?? 9999) - 280)),
            top: Math.max(12, activeCam.y - 40),
          }}
        >
          <div className="cctv-pop-head">
            <span className="cctv-pop-name">{activeCam.cam.name}</span>
            <button
              type="button"
              className="cctv-pop-close"
              aria-label="Close camera"
              onClick={() => setActiveCam(null)}
            >
              ✕
            </button>
          </div>
          <img
            className="cctv-pop-img"
            src={`${activeCam.cam.image}${activeCam.cam.image.includes("?") ? "&" : "?"}cb=${imgTick}`}
            alt={`Live view: ${activeCam.cam.name}`}
          />
          <div className="cctv-pop-foot">
            <span className="cctv-pop-live">
              <span className="cctv-pop-dot" /> LIVE
            </span>
            <a
              className="cctv-pop-video"
              href={activeCam.cam.video}
              target="_blank"
              rel="noreferrer"
            >
              ▶ video
            </a>
          </div>
        </div>
      )}
    </div>
  );
}
