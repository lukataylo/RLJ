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
import { ScatterplotLayer, PathLayer, TextLayer } from "@deck.gl/layers";
import { useStore } from "../store";
import type {
  CongestionCell,
  CongestionField,
  Courier,
  DeliveryJob,
  DisruptionEvent,
  Plan,
  SignalRec,
} from "../types";
import {
  COURIER_RGB,
  DISRUPTION_CLASS_RGB,
  PRIORITY_RGB,
  ROUTE_CONGESTED_RGB,
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
import { getRoadRoute, routeSignature, type LngLat } from "../lib/routing";

// Lower pitch than before (~0–30°, near top-down) so road-following routes read.
const INITIAL_VIEW = {
  center: [-0.095, 51.508] as [number, number],
  zoom: 12.1,
  pitch: 24,
  bearing: 0,
};

const MAPBOX_TOKEN = (import.meta.env.VITE_MAPBOX_TOKEN ?? "").trim();
const USE_MAPBOX = MAPBOX_TOKEN.length > 0;
const MAPBOX_STYLE = "mapbox://styles/mapbox/dark-v11";

const MAP_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    carto: {
      type: "raster",
      tiles: [
        "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
      ],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors © CARTO",
    },
  },
  layers: [
    { id: "bg", type: "background", paint: { "background-color": "#05090b" } },
    { id: "carto", type: "raster", source: "carto" },
  ],
};

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
type LayerKey = "congestion" | "routes" | "incidents" | "signals";
type LayerVis = Record<LayerKey, boolean>;

const DEFAULT_VIS: LayerVis = {
  congestion: true, // "Traffic"
  routes: true,
  incidents: true,
  signals: true, // GB10 Nemotron signal recs — default ON
};

interface Snapshot {
  jobs: DeliveryJob[];
  couriers: Courier[];
  plan: Plan | null;
  disruptions: DisruptionEvent[];
  congestion: CongestionField;
  signalRecs: SignalRec[];
  selectedCourierId: string | null;
}

interface OptionalData {
  roads: RoadPath[];
  facilities: Facility[];
  venues: EventVenue[];
}

const EMPTY_SNAP: Snapshot = {
  jobs: [],
  couriers: [],
  plan: null,
  disruptions: [],
  congestion: { cells: [] },
  signalRecs: [],
  selectedCourierId: null,
};

// Short uppercase glyph per signal action for the on-map label.
const SIGNAL_ACTION_LABEL: Record<string, string> = {
  green_wave: "GREEN WAVE",
  retime: "RETIME",
  hold: "HOLD",
  clear: "CLEAR",
};

const FACILITY_GLYPH: Record<string, string> = {
  hospital: "H",
  lab: "L",
  gp: "G",
  clinic: "C",
  pharmacy: "P",
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

function buildLayers(
  snap: Snapshot,
  data: OptionalData,
  vis: LayerVis,
  phase: number,
  roadPaths: Record<string, LngLat[] | null>,
): Layer[] {
  const { jobs, couriers, plan, disruptions, congestion, signalRecs, selectedCourierId } = snap;
  const layers: Layer[] = [];
  const courierById = new Map(couriers.map((c) => [c.id, c]));

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
  const selActive = selectedCourierId != null;
  const congSources = congestionSources(data.roads, congestion.cells, congestion.generated_at ?? "static");

  const routeLines = (plan?.routes ?? [])
    .map((r) => {
      const courier = courierById.get(r.courier_id);
      const stopCoords = routeStopCoords(plan, courier, r.courier_id);
      if (stopCoords.length < 2) return null;
      const road = roadPaths[r.courier_id];
      const path = road && road.length >= 2 ? road : fallbackPath(plan, r.courier_id, stopCoords);
      if (path.length < 2) return null;
      return { courier_id: r.courier_id, selected: r.courier_id === selectedCourierId, path };
    })
    .filter((r): r is { courier_id: string; selected: boolean; path: LngLat[] } => r !== null);

  // One record per drawn segment so each can be neutral or red independently.
  interface RouteSeg { courier_id: string; selected: boolean; congested: boolean; path: LngLat[] }
  const routeSegs: RouteSeg[] = [];
  for (const rl of routeLines) {
    for (let i = 0; i < rl.path.length - 1; i++) {
      const a = rl.path[i];
      const b = rl.path[i + 1];
      routeSegs.push({
        courier_id: rl.courier_id,
        selected: rl.selected,
        congested: segmentCongested(a, b, congSources),
        path: [a, b],
      });
    }
  }

  // Alpha ramps: when a route is selected, it brightens and the rest dim away.
  const segGlowAlpha = (s: RouteSeg) => (!selActive ? 60 : s.selected ? 100 : 16);
  const segMainAlpha = (s: RouteSeg) => (!selActive ? 215 : s.selected ? 255 : 55);
  const segColor = (s: RouteSeg) => (s.congested ? ROUTE_CONGESTED_RGB : ROUTE_NEUTRAL_RGB);

  if (vis.routes && routeSegs.length) {
    layers.push(
      new PathLayer<RouteSeg>({
        id: "routes-glow",
        data: routeSegs,
        getPath: (d) => d.path,
        getColor: (d) => [...segColor(d), segGlowAlpha(d)] as [number, number, number, number],
        getWidth: (d) => (d.selected ? 16 : 10),
        widthUnits: "pixels",
        capRounded: true,
        jointRounded: true,
        updateTriggers: { getColor: selectedCourierId, getWidth: selectedCourierId },
      }),
    );
    layers.push(
      new PathLayer<RouteSeg>({
        id: "routes",
        data: routeSegs,
        getPath: (d) => d.path,
        getColor: (d) => [...segColor(d), segMainAlpha(d)] as [number, number, number, number],
        getWidth: (d) => (d.selected ? 5.5 : 3.4),
        widthUnits: "pixels",
        capRounded: true,
        jointRounded: true,
        pickable: true,
        updateTriggers: { getColor: selectedCourierId, getWidth: selectedCourierId },
      }),
    );
    // (Removed the animated "trip-head" dots that raced along every route — they read as
    // noise / made it look like nothing was settling. Routes are static lines; the courier
    // markers below show real position.)
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
    const dimA = (jobId: string, base: number) =>
      !selActive || selectedJobIds.has(jobId) ? base : Math.round(base * 0.18);
    const pickups = jobs.map((j) => ({ job: j, loc: j.origin }));
    const drops = jobs.map((j) => ({ job: j, loc: j.destination }));
    layers.push(
      new ScatterplotLayer<(typeof pickups)[number]>({
        id: "job-pickups",
        data: pickups,
        getPosition: (d) => [d.loc.lng, d.loc.lat],
        getRadius: 7,
        radiusUnits: "pixels",
        radiusMinPixels: 5,
        stroked: true,
        lineWidthMinPixels: 2,
        getLineColor: (d) => [...PRIORITY_RGB[d.job.priority], dimA(d.job.id, 230)] as [number, number, number, number],
        getFillColor: (d) => [...PRIORITY_RGB[d.job.priority], dimA(d.job.id, 90)] as [number, number, number, number],
        pickable: true,
        updateTriggers: { getLineColor: selectedCourierId, getFillColor: selectedCourierId },
      }),
    );
    layers.push(
      new ScatterplotLayer<(typeof drops)[number]>({
        id: "job-drops",
        data: drops,
        getPosition: (d) => [d.loc.lng, d.loc.lat],
        getRadius: 6,
        radiusUnits: "pixels",
        radiusMinPixels: 4,
        stroked: true,
        lineWidthMinPixels: 1,
        getLineColor: (d) => [5, 9, 11, dimA(d.job.id, 220)] as [number, number, number, number],
        getFillColor: (d) => [191, 227, 107, dimA(d.job.id, 235)] as [number, number, number, number],
        pickable: true,
        updateTriggers: { getLineColor: selectedCourierId, getFillColor: selectedCourierId },
      }),
    );
  }

  // 5. NHS facilities — subtle markers + glyph (atmosphere / context).
  if (data.facilities.length) {
    layers.push(
      new ScatterplotLayer<Facility>({
        id: "facilities",
        data: data.facilities,
        getPosition: (f) => [f.lng, f.lat],
        getRadius: 90,
        radiusUnits: "meters",
        radiusMinPixels: 5,
        radiusMaxPixels: 12,
        stroked: true,
        lineWidthMinPixels: 1,
        getLineColor: [5, 9, 11, 220],
        getFillColor: (f) => [...facilityRGB(f.type), 200] as [number, number, number, number],
        pickable: true,
      }),
    );
    layers.push(
      new TextLayer<Facility>({
        id: "facilities-glyph",
        data: data.facilities,
        getPosition: (f) => [f.lng, f.lat],
        getText: (f) => FACILITY_GLYPH[f.type] ?? "•",
        getSize: 10,
        getColor: [5, 9, 11, 255],
        fontWeight: 700,
        getTextAnchor: "middle",
        getAlignmentBaseline: "center",
      }),
    );
  }

  // 6. (Random driver/probe dots removed — drivers still feed congestion server-side.)

  // 7. Couriers — glowing markers, colour by status; selected gets a halo.
  layers.push(
    new ScatterplotLayer<Courier>({
      id: "couriers-glow",
      data: couriers,
      getPosition: (c) => [c.location.lng, c.location.lat],
      getRadius: 280,
      radiusUnits: "meters",
      radiusMinPixels: 12,
      radiusMaxPixels: 38,
      getFillColor: (c) =>
        [...(COURIER_RGB[c.status] ?? [200, 200, 200]), c.id === selectedCourierId ? 90 : selActive ? 14 : 45] as [number, number, number, number],
      updateTriggers: { getFillColor: selectedCourierId },
    }),
  );
  layers.push(
    new ScatterplotLayer<Courier>({
      id: "couriers",
      data: couriers,
      getPosition: (c) => [c.location.lng, c.location.lat],
      getRadius: 110,
      radiusUnits: "meters",
      radiusMinPixels: 6,
      radiusMaxPixels: 16,
      stroked: true,
      lineWidthMinPixels: 2,
      getLineColor: (c) => (c.id === selectedCourierId ? [232, 237, 230, 255] : [5, 9, 11, 255]),
      getFillColor: (c) =>
        [...(COURIER_RGB[c.status] ?? [200, 200, 200]), selActive && c.id !== selectedCourierId ? 70 : 255] as [number, number, number, number],
      pickable: true,
      updateTriggers: { getLineColor: selectedCourierId, getFillColor: selectedCourierId },
    }),
  );

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

const LEFT_LAYERS: { key: LayerKey; label: string; glyph: string; testid: string }[] = [
  { key: "congestion", label: "Traffic", glyph: "🚦", testid: "layer-toggle-congestion" },
  { key: "routes", label: "Routes", glyph: "〰", testid: "layer-toggle-routes" },
  { key: "incidents", label: "Incidents", glyph: "⚠", testid: "layer-toggle-incidents" },
  { key: "signals", label: "Signals", glyph: "◈", testid: "layer-toggle-signals" },
];

export default function MapView() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | mapboxgl.Map | null>(null);
  const overlayRef = useRef<MapboxOverlay | null>(null);
  const phaseRef = useRef(0);
  const rafRef = useRef<number | null>(null);
  const snapRef = useRef<Snapshot>(EMPTY_SNAP);
  const dataRef = useRef<OptionalData>({ roads: [], facilities: [], venues: [] });
  const visRef = useRef<LayerVis>(DEFAULT_VIS);
  const roadPathsRef = useRef<Record<string, LngLat[] | null>>({});
  const resolveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [optional, setOptional] = useState<OptionalData>({ roads: [], facilities: [], venues: [] });
  const [vis, setVis] = useState<LayerVis>(DEFAULT_VIS);
  const [counts, setCounts] = useState({ jobs: 0, couriers: 0, routes: 0, congestion: 0, disruptions: 0, signals: 0 });

  const selectCourier = useStore((s) => s.selectCourier);

  const toggle = (key: LayerKey) => setVis((v) => ({ ...v, [key]: !v[key] }));

  // Debounced road-route resolver: signature-cached Directions API calls; results
  // land in roadPathsRef and are picked up by the imperative render loop.
  const resolveRoutes = useMemo(() => {
    const run = () => {
      const snap = snapRef.current;
      const courierById = new Map(snap.couriers.map((c) => [c.id, c]));
      const next: Record<string, LngLat[] | null> = {};
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
        selectedCourierId: s.selectedCourierId,
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
      const [roadsGj, facRaw, evtRaw] = await Promise.all([
        fetchOptionalJson("/data/roads.geojson"),
        fetchOptional<unknown>("/data/facilities.json"),
        fetchOptional<unknown>("/data/events.json"),
      ]);
      if (cancelled) return;
      const roads = parseRoads(roadsGj);
      const facilities = parseFacilities(facRaw);
      const venues = parseEventVenues(evtRaw);
      setOptional({ roads, facilities, venues });
      const loaded: string[] = [];
      if (roads.length) loaded.push(`${roads.length} roads`);
      if (facilities.length) loaded.push(`${facilities.length} facilities`);
      if (venues.length) loaded.push(`${venues.length} event venues`);
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

  // Init map + overlay once.
  useEffect(() => {
    if (!containerRef.current) return;

    let map: maplibregl.Map | mapboxgl.Map;
    if (USE_MAPBOX) {
      mapboxgl.accessToken = MAPBOX_TOKEN;
      map = new mapboxgl.Map({
        container: containerRef.current,
        style: MAPBOX_STYLE,
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
        style: MAP_STYLE,
        center: INITIAL_VIEW.center,
        zoom: INITIAL_VIEW.zoom,
        pitch: INITIAL_VIEW.pitch,
        bearing: INITIAL_VIEW.bearing,
        attributionControl: { compact: true },
      });
    }
    mapRef.current = map;

    const m = map as maplibregl.Map;

    m.on("load", () => {
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
        if (o && "status" in o && "location" in o) {
          selectCourier((o as unknown as Courier).id);
        }
      },
      getTooltip: tooltipFor,
    });
    m.addControl(overlay);
    overlayRef.current = overlay;

    let last = performance.now();
    const LOOP_SECONDS = 14;
    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      phaseRef.current = (phaseRef.current + dt / LOOP_SECONDS) % 1;
      overlay.setProps({
        layers: buildLayers(snapRef.current, dataRef.current, visRef.current, phaseRef.current, roadPathsRef.current),
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

      {/* Left floating control stack */}
      <div className="control-stack glass" data-testid="layers-panel">
        {LEFT_LAYERS.map((l) => {
          const on = !!vis[l.key];
          return (
            <button
              key={l.key}
              type="button"
              className={`cs-toggle ${on ? "on" : ""}`}
              data-testid={l.testid}
              data-on={on ? "true" : "false"}
              onClick={() => toggle(l.key)}
            >
              <span className="cs-glyph">{l.glyph}</span>
              <span className="cs-label">{l.label}</span>
              <span className={`cs-led ${on ? "on" : ""}`} />
            </button>
          );
        })}
        <div className="cs-divider" />
        <button type="button" className="cs-icon" title="Recenter" onClick={recenter}>◎</button>
        <button type="button" className="cs-icon" title="Zoom in" onClick={() => zoomBy(0.6)}>+</button>
        <button type="button" className="cs-icon" title="Zoom out" onClick={() => zoomBy(-0.6)}>−</button>
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
    </div>
  );
}
