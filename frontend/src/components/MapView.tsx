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
//                         glowing lines coloured by dominant job priority.
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
  Driver,
  Plan,
  Priority,
} from "../types";
import {
  COURIER_RGB,
  DISRUPTION_CLASS_RGB,
  DRIVER_RGB,
  PRIORITY_RGB,
  congestionRGB,
  facilityRGB,
} from "../lib/palette";
import { pointAlong } from "../lib/geo";
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
type LayerKey = "congestion" | "routes" | "incidents" | "drivers" | "buildings";
type LayerVis = Record<LayerKey, boolean>;

const DEFAULT_VIS: LayerVis = {
  congestion: true, // "Traffic"
  routes: true,
  incidents: true,
  drivers: true,
  buildings: false, // removed (clean basemap) — kept for testid compatibility
};

interface Snapshot {
  jobs: DeliveryJob[];
  couriers: Courier[];
  plan: Plan | null;
  disruptions: DisruptionEvent[];
  drivers: Driver[];
  congestion: CongestionField;
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
  drivers: [],
  congestion: { cells: [] },
  selectedCourierId: null,
};

const FACILITY_GLYPH: Record<string, string> = {
  hospital: "H",
  lab: "L",
  gp: "G",
  clinic: "C",
  pharmacy: "P",
};

// Highest-priority job served by a route -> route colour.
function routePriority(plan: Plan | null, courierId: string, jobs: DeliveryJob[]): Priority {
  const route = plan?.routes?.find((r) => r.courier_id === courierId);
  if (!route) return "routine";
  const jobById = new Map(jobs.map((j) => [j.id, j]));
  const order: Priority[] = ["stat", "urgent", "routine"];
  let best: Priority = "routine";
  for (const s of route.stops ?? []) {
    const p = jobById.get(s.job_id)?.priority;
    if (p && order.indexOf(p) < order.indexOf(best)) best = p;
  }
  return best;
}

function hash01(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return ((h >>> 0) % 100000) / 100000;
}

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

interface DriverDot {
  _t: "driver";
  driver: Driver;
  pos: [number, number];
}
function driverDots(drivers: Driver[], cells: CongestionCell[], phase: number): DriverDot[] {
  const anchors: [number, number][] = cells.length
    ? cells.map((c) => [c.lng, c.lat])
    : [[-0.095, 51.508]];
  return drivers.map((d, i) => {
    const a = anchors[i % anchors.length];
    const r = hash01(d.id || String(i));
    const ang = r * Math.PI * 2 + phase * Math.PI * 2 * (0.4 + r * 0.6);
    const rad = 0.0016 + r * 0.0028;
    return {
      _t: "driver" as const,
      driver: d,
      pos: [a[0] + Math.cos(ang) * rad, a[1] + Math.sin(ang) * rad * 0.7],
    };
  });
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
  const { jobs, couriers, plan, disruptions, drivers, congestion, selectedCourierId } = snap;
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

  // 2. Routes — road-following geometry (Directions API) or straight fallback.
  const routeLines = (plan?.routes ?? [])
    .map((r) => {
      const courier = courierById.get(r.courier_id);
      const stopCoords = routeStopCoords(plan, courier, r.courier_id);
      if (stopCoords.length < 2) return null;
      const road = roadPaths[r.courier_id];
      const path = road && road.length >= 2 ? road : fallbackPath(plan, r.courier_id, stopCoords);
      if (path.length < 2) return null;
      return { courier_id: r.courier_id, priority: routePriority(plan, r.courier_id, jobs), path };
    })
    .filter((r): r is { courier_id: string; priority: Priority; path: LngLat[] } => r !== null);

  if (vis.routes && routeLines.length) {
    layers.push(
      new PathLayer<(typeof routeLines)[number]>({
        id: "routes-glow",
        data: routeLines,
        getPath: (d) => d.path,
        getColor: (d) =>
          [...PRIORITY_RGB[d.priority], d.courier_id === selectedCourierId ? 95 : 55] as [number, number, number, number],
        getWidth: (d) => (d.courier_id === selectedCourierId ? 18 : 12),
        widthUnits: "pixels",
        capRounded: true,
        jointRounded: true,
        updateTriggers: { getColor: selectedCourierId, getWidth: selectedCourierId },
      }),
    );
    layers.push(
      new PathLayer<(typeof routeLines)[number]>({
        id: "routes",
        data: routeLines,
        getPath: (d) => d.path,
        getColor: (d) =>
          [...PRIORITY_RGB[d.priority], d.courier_id === selectedCourierId ? 255 : 200] as [number, number, number, number],
        getWidth: (d) => (d.courier_id === selectedCourierId ? 5 : 3.4),
        widthUnits: "pixels",
        capRounded: true,
        jointRounded: true,
        pickable: true,
        updateTriggers: { getColor: selectedCourierId, getWidth: selectedCourierId },
      }),
    );
    // Animated heads riding the road-following path.
    const heads = routeLines
      .map((r) => ({
        courier_id: r.courier_id,
        priority: r.priority,
        pos: pointAlong(r.path.map(([lng, lat]) => ({ lat, lng })), phase),
      }))
      .filter((h): h is { courier_id: string; priority: Priority; pos: [number, number] } => h.pos !== null);
    layers.push(
      new ScatterplotLayer<(typeof heads)[number]>({
        id: "trip-heads-glow",
        data: heads,
        getPosition: (d) => d.pos,
        getRadius: 22,
        radiusUnits: "pixels",
        getFillColor: (d) => [...PRIORITY_RGB[d.priority], 70] as [number, number, number, number],
        updateTriggers: { getPosition: phase },
      }),
    );
    layers.push(
      new ScatterplotLayer<(typeof heads)[number]>({
        id: "trip-heads",
        data: heads,
        getPosition: (d) => d.pos,
        getRadius: 6,
        radiusUnits: "pixels",
        stroked: true,
        lineWidthMinPixels: 1.5,
        getLineColor: [232, 237, 230, 230],
        getFillColor: (d) => [...PRIORITY_RGB[d.priority], 255] as [number, number, number, number],
        updateTriggers: { getPosition: phase },
      }),
    );
  }

  // 3. Dashed connectors from each courier to its next stop.
  if (vis.routes) {
    const connectors: { path: LngLat[]; priority: Priority }[] = [];
    for (const r of plan?.routes ?? []) {
      const courier = courierById.get(r.courier_id);
      if (!courier?.location) continue;
      const next = [...(r.stops ?? [])].sort((a, b) => a.sequence - b.sequence)[0];
      if (!next?.location) continue;
      const a: LngLat = [courier.location.lng, courier.location.lat];
      const b: LngLat = [next.location.lng, next.location.lat];
      const prio = routePriority(plan, r.courier_id, jobs);
      for (const seg of dashSegments(a, b)) connectors.push({ path: seg, priority: prio });
    }
    if (connectors.length) {
      layers.push(
        new PathLayer<(typeof connectors)[number]>({
          id: "courier-connectors",
          data: connectors,
          getPath: (d) => d.path,
          getColor: (d) => [...PRIORITY_RGB[d.priority], 150] as [number, number, number, number],
          getWidth: 1.4,
          widthUnits: "pixels",
        }),
      );
    }
  }

  // 4. Job nodes — pickup (priority colour + ring) and dropoff (lime) glowing dots.
  if (vis.routes) {
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
        getLineColor: (d) => [...PRIORITY_RGB[d.job.priority], 230] as [number, number, number, number],
        getFillColor: (d) => [...PRIORITY_RGB[d.job.priority], 90] as [number, number, number, number],
        pickable: true,
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
        getLineColor: [5, 9, 11, 220],
        getFillColor: [191, 227, 107, 235],
        pickable: true,
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

  // 6. Driver probes — animated lime dots.
  if (vis.drivers && drivers.length) {
    const dots = driverDots(drivers, congestion.cells, phase);
    layers.push(
      new ScatterplotLayer<DriverDot>({
        id: "drivers-glow",
        data: dots,
        getPosition: (d) => d.pos,
        getRadius: 7,
        radiusUnits: "pixels",
        getFillColor: [...DRIVER_RGB, 55] as [number, number, number, number],
        updateTriggers: { getPosition: phase },
      }),
    );
    layers.push(
      new ScatterplotLayer<DriverDot>({
        id: "drivers",
        data: dots,
        getPosition: (d) => d.pos,
        getRadius: 3,
        radiusUnits: "pixels",
        radiusMinPixels: 2,
        stroked: true,
        lineWidthMinPixels: 0.6,
        getLineColor: [5, 9, 11, 200],
        getFillColor: [...DRIVER_RGB, 235] as [number, number, number, number],
        pickable: true,
        updateTriggers: { getPosition: phase },
      }),
    );
  }

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
        [...(COURIER_RGB[c.status] ?? [200, 200, 200]), c.id === selectedCourierId ? 90 : 45] as [number, number, number, number],
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
        [...(COURIER_RGB[c.status] ?? [200, 200, 200]), 255] as [number, number, number, number],
      pickable: true,
      updateTriggers: { getLineColor: selectedCourierId },
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
  if (o._t === "driver") {
    const d = (object as DriverDot).driver;
    return {
      className: "deck-tip",
      html: `<b>${d.name ?? d.id}</b><br/>${d.vehicle_type} probe · ${d.points ?? 0} pts<br/><span class="tip-dim">crowdsourced driver</span>`,
    };
  }
  if (o._t === "disr") {
    const d = object as { label: string; cls: string };
    return { className: "deck-tip", html: `<b>${d.label}</b><br/><span class="tip-dim">${d.cls} disruption</span>` };
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
    return { className: "deck-tip", html: `<b>route</b><br/>${(object as { courier_id: string }).courier_id}` };
  }
  return null;
}

const LEFT_LAYERS: { key: LayerKey; label: string; glyph: string; testid: string; present: boolean }[] = [
  { key: "congestion", label: "Traffic", glyph: "🚦", testid: "layer-toggle-congestion", present: true },
  { key: "routes", label: "Routes", glyph: "〰", testid: "layer-toggle-routes", present: true },
  { key: "incidents", label: "Incidents", glyph: "⚠", testid: "layer-toggle-incidents", present: true },
  { key: "drivers", label: "Probes", glyph: "◍", testid: "layer-toggle-drivers", present: true },
  { key: "buildings", label: "Buildings", glyph: "▦", testid: "layer-toggle-buildings", present: false },
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
  const [counts, setCounts] = useState({ jobs: 0, couriers: 0, routes: 0, drivers: 0, congestion: 0, disruptions: 0 });

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
      const drivers = Object.values(s.drivers);
      snapRef.current = {
        jobs,
        couriers,
        plan: s.plan,
        disruptions: s.disruptions,
        drivers,
        congestion: s.congestion,
        selectedCourierId: s.selectedCourierId,
      };
      setCounts({
        jobs: jobs.length,
        couriers: couriers.length,
        routes: s.plan?.routes?.length ?? 0,
        drivers: drivers.length,
        congestion: s.congestion.cells.length,
        disruptions: s.disruptions.length,
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
          const on = !!vis[l.key] && l.present;
          return (
            <button
              key={l.key}
              type="button"
              className={`cs-toggle ${on ? "on" : ""} ${l.present ? "" : "absent"}`}
              data-testid={l.testid}
              data-on={on ? "true" : "false"}
              disabled={!l.present}
              onClick={() => l.present && toggle(l.key)}
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
        data-buildings="absent"
        data-congestion={counts.congestion}
        data-drivers={counts.drivers}
      >
        <span className="rs-led" />
        {`routes:${counts.routes} · cong:${counts.congestion} · drivers:${counts.drivers} · traffic:${trafficOn ? optional.roads.length : "off"}`}
      </div>
    </div>
  );
}
