// The live operations map: token-less MapLibre dark basemap (or Mapbox dark-v11
// when VITE_MAPBOX_TOKEN is set) + a deck.gl overlay.
//
// Toggleable layers (overlaid via MapboxOverlay), all with hover tooltips:
//   - 3D BUILDINGS        — extruded polygons from /data/buildings.geojson
//   - CONGESTION FIELD    — GridCellLayer (green→amber→red) from the live /congestion
//                           flywheel; updates on WS congestion_updated
//   - TRAFFIC FLOW        — roads coloured by congestion + animated flow dashes
//   - JOBS                — origin→destination arcs + endpoints, colour by priority
//   - ROUTES              — courier plan polylines + animated trip heads
//   - NHS FACILITIES      — hospital/lab/GP/pharmacy markers (/data/facilities.json)
//   - SIGNAL JUNCTIONS    — green-wave junctions (/data/junctions.json), live phase
//   - DRIVER PROBES       — crowdsourced fleet dots, animated, grows as drivers join
//   - COURIERS            — medical couriers, status colour
//   - DISRUPTIONS         — pulsing icons, classified bridge / event / congestion / road

import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import mapboxgl from "mapbox-gl";
import { MapboxOverlay } from "@deck.gl/mapbox";
import type { Layer, PickingInfo } from "@deck.gl/core";
import {
  ScatterplotLayer,
  PathLayer,
  ArcLayer,
  PolygonLayer,
  GridCellLayer,
  TextLayer,
} from "@deck.gl/layers";
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
  SIGNAL_GREEN_RGB,
  SIGNAL_RED_RGB,
  congestionRGB,
  facilityRGB,
} from "../lib/palette";
import { pointAlong, pointAlongPath } from "../lib/geo";
import {
  fetchOptionalJson,
  parseBuildings,
  parseRoads,
  type BuildingPoly,
  type RoadPath,
} from "../lib/geojson";
import {
  classifyDisruption,
  fetchOptional,
  parseBridgeCentre,
  parseEventVenues,
  parseFacilities,
  parseJunctions,
  signalPhase,
  type EventVenue,
  type Facility,
  type Junction,
} from "../lib/datasets";
import LayersPanel, { type LayerDef } from "./LayersPanel";
import DataSourcePanel, { type SourceDef } from "./DataSourcePanel";
import MapLegend from "./MapLegend";

const INITIAL_VIEW = {
  center: [-0.118, 51.503] as [number, number],
  zoom: 11.4,
  pitch: 50,
  bearing: -14,
};

const MAPBOX_TOKEN = (import.meta.env.VITE_MAPBOX_TOKEN ?? "").trim();
const USE_MAPBOX = MAPBOX_TOKEN.length > 0;
const MAPBOX_STYLE = "mapbox://styles/mapbox/dark-v11";

// Congestion grid cell size (matches the orchestrator's ~400 m aggregation grid).
const CONG_GRID = 0.004;

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
    { id: "bg", type: "background", paint: { "background-color": "#0a0e16" } },
    { id: "carto", type: "raster", source: "carto" },
  ],
};

// Visibility flags for every toggleable layer.
type LayerKey =
  | "buildings"
  | "congestion"
  | "traffic"
  | "jobs"
  | "routes"
  | "facilities"
  | "junctions"
  | "drivers"
  | "couriers"
  | "disruptions";

type LayerVis = Record<LayerKey, boolean>;

const DEFAULT_VIS: LayerVis = {
  buildings: false,
  congestion: true,
  traffic: true,
  jobs: true,
  routes: true,
  facilities: true,
  junctions: false,
  drivers: true,
  couriers: true,
  disruptions: true,
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
  buildings: BuildingPoly[];
  facilities: Facility[];
  junctions: Junction[];
  venues: EventVenue[];
}

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

// Stable 0..1 hash from a string (FNV-1a) — for deterministic driver drift.
function hash01(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return ((h >>> 0) % 100000) / 100000;
}

// SW corner of a congestion grid cell (from its encoded "lat_lng" id).
function cellCorner(c: CongestionCell): [number, number] {
  const parts = (c.cell ?? "").split("_");
  const clat = parseFloat(parts[0]);
  const clng = parseFloat(parts[1]);
  const lat = Number.isFinite(clat) ? clat : c.lat;
  const lng = Number.isFinite(clng) ? clng : c.lng;
  return [lng - CONG_GRID / 2, lat - CONG_GRID / 2];
}

// Drivers carry no GPS in the roster, so we animate probe dots drifting around the
// congestion hotspots they feed (or central London when the field is empty).
interface DriverDot {
  _t: "driver";
  driver: Driver;
  pos: [number, number];
}
function driverDots(drivers: Driver[], cells: CongestionCell[], phase: number): DriverDot[] {
  const anchors: [number, number][] = cells.length
    ? cells.map((c) => [c.lng, c.lat])
    : [[-0.118, 51.503]];
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

function buildLayers(
  snap: Snapshot,
  data: OptionalData,
  vis: LayerVis,
  phase: number,
  nowMs: number,
): Layer[] {
  const { jobs, couriers, plan, disruptions, drivers, congestion, selectedCourierId } = snap;
  const layers: Layer[] = [];

  // 0a. 3D buildings (under everything).
  if (vis.buildings && data.buildings.length) {
    layers.push(
      new PolygonLayer<BuildingPoly>({
        id: "buildings",
        data: data.buildings,
        extruded: true,
        getPolygon: (d) => d.polygon,
        getElevation: (d) => d.height,
        getFillColor: [14, 28, 48, 225],
        getLineColor: [24, 240, 255, 70],
        lineWidthMinPixels: 1,
        material: { ambient: 0.55, diffuse: 0.7, shininess: 48, specularColor: [40, 120, 150] },
      }),
    );
  }

  // 0b. Congestion field — live flywheel made visible (GridCellLayer, flat heat).
  if (vis.congestion && congestion.cells.length) {
    layers.push(
      new GridCellLayer<CongestionCell>({
        id: "congestion-field",
        data: congestion.cells,
        cellSize: 400,
        extruded: false,
        getPosition: (c) => cellCorner(c),
        getFillColor: (c) =>
          [...congestionRGB(c.congestion), Math.round(70 + c.congestion * 130)] as [
            number,
            number,
            number,
            number,
          ],
        pickable: true,
        updateTriggers: { getFillColor: congestion.generated_at },
      }),
    );
  }

  // 0c. Traffic flow — roads coloured by congestion + animated flow dashes.
  if (vis.traffic && data.roads.length) {
    layers.push(
      new PathLayer<RoadPath>({
        id: "traffic-roads",
        data: data.roads,
        getPath: (d) => d.path,
        getColor: (d) => [...congestionRGB(d.congestion), 150] as [number, number, number, number],
        getWidth: (d) => 2 + d.congestion * 3,
        widthUnits: "pixels",
        capRounded: true,
        jointRounded: true,
      }),
    );
    const flow: { pos: [number, number]; congestion: number }[] = [];
    for (const r of data.roads) {
      const pos = pointAlongPath(r.path, (phase * 1.7) % 1);
      if (pos) flow.push({ pos, congestion: r.congestion });
    }
    layers.push(
      new ScatterplotLayer<{ pos: [number, number]; congestion: number }>({
        id: "traffic-flow",
        data: flow,
        getPosition: (d) => d.pos,
        getRadius: 2,
        radiusUnits: "pixels",
        radiusMinPixels: 1.5,
        radiusMaxPixels: 4,
        getFillColor: (d) => [...congestionRGB(d.congestion), 230] as [number, number, number, number],
        updateTriggers: { getPosition: phase },
      }),
    );
  }

  // 1. Job origin -> destination arcs + endpoints, colour by priority.
  if (vis.jobs) {
    layers.push(
      new ArcLayer<DeliveryJob>({
        id: "job-arcs",
        data: jobs,
        getSourcePosition: (j) => [j.origin.lng, j.origin.lat],
        getTargetPosition: (j) => [j.destination.lng, j.destination.lat],
        getSourceColor: (j) => [...PRIORITY_RGB[j.priority], 90] as [number, number, number, number],
        getTargetColor: (j) => [...PRIORITY_RGB[j.priority], 220] as [number, number, number, number],
        getWidth: (j) => (j.priority === "stat" ? 3 : j.priority === "urgent" ? 2 : 1.4),
        getHeight: 0.3,
        widthUnits: "pixels",
        pickable: true,
      }),
    );
    const endpoints = jobs.flatMap((j) => [
      { job: j, loc: j.origin, kind: "origin" as const },
      { job: j, loc: j.destination, kind: "dest" as const },
    ]);
    layers.push(
      new ScatterplotLayer<(typeof endpoints)[number]>({
        id: "job-endpoints",
        data: endpoints,
        getPosition: (d) => [d.loc.lng, d.loc.lat],
        getRadius: (d) => (d.kind === "dest" ? 90 : 70),
        radiusUnits: "meters",
        radiusMinPixels: 4,
        radiusMaxPixels: 15,
        stroked: true,
        lineWidthMinPixels: 1.5,
        getLineColor: [255, 255, 255, 210],
        getFillColor: (d) =>
          [...PRIORITY_RGB[d.job.priority], d.kind === "dest" ? 230 : 110] as [number, number, number, number],
        pickable: true,
      }),
    );
  }

  // 2. Plan routes + animated trip heads.
  const routePaths = (plan?.routes ?? [])
    .filter((r) => r.polyline && r.polyline.length >= 2)
    .map((r) => ({
      courier_id: r.courier_id,
      priority: routePriority(plan, r.courier_id, jobs),
      path: r.polyline!.map((p) => [p.lng, p.lat] as [number, number]),
    }));
  if (vis.routes) {
    layers.push(
      new PathLayer<(typeof routePaths)[number]>({
        id: "routes-glow",
        data: routePaths,
        getPath: (d) => d.path,
        getColor: (d) =>
          [...PRIORITY_RGB[d.priority], d.courier_id === selectedCourierId ? 90 : 55] as [number, number, number, number],
        getWidth: (d) => (d.courier_id === selectedCourierId ? 22 : 16),
        widthUnits: "pixels",
        capRounded: true,
        jointRounded: true,
        updateTriggers: { getColor: selectedCourierId, getWidth: selectedCourierId },
      }),
    );
    layers.push(
      new PathLayer<(typeof routePaths)[number]>({
        id: "routes",
        data: routePaths,
        getPath: (d) => d.path,
        getColor: (d) =>
          [...PRIORITY_RGB[d.priority], d.courier_id === selectedCourierId ? 255 : 200] as [number, number, number, number],
        getWidth: (d) => (d.courier_id === selectedCourierId ? 6 : 4),
        widthUnits: "pixels",
        capRounded: true,
        jointRounded: true,
        pickable: true,
        updateTriggers: { getColor: selectedCourierId, getWidth: selectedCourierId },
      }),
    );
    const heads = (plan?.routes ?? [])
      .filter((r) => r.polyline && r.polyline.length >= 2)
      .map((r) => ({
        courier_id: r.courier_id,
        priority: routePriority(plan, r.courier_id, jobs),
        pos: pointAlong(r.polyline!, phase),
      }))
      .filter((h) => h.pos) as { courier_id: string; priority: Priority; pos: [number, number] }[];
    layers.push(
      new ScatterplotLayer<(typeof heads)[number]>({
        id: "trip-heads-glow",
        data: heads,
        getPosition: (d) => d.pos,
        getRadius: 26,
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
        getRadius: 9,
        radiusUnits: "pixels",
        stroked: true,
        lineWidthMinPixels: 2,
        getLineColor: [255, 255, 255, 255],
        getFillColor: (d) => [...PRIORITY_RGB[d.priority], 255] as [number, number, number, number],
        updateTriggers: { getPosition: phase },
      }),
    );
  }

  // 3. NHS facilities — coloured markers + letter glyphs.
  if (vis.facilities && data.facilities.length) {
    layers.push(
      new ScatterplotLayer<Facility>({
        id: "facilities",
        data: data.facilities,
        getPosition: (f) => [f.lng, f.lat],
        getRadius: 120,
        radiusUnits: "meters",
        radiusMinPixels: 7,
        radiusMaxPixels: 16,
        stroked: true,
        lineWidthMinPixels: 1.5,
        getLineColor: [5, 10, 18, 230],
        getFillColor: (f) => [...facilityRGB(f.type), 235] as [number, number, number, number],
        pickable: true,
      }),
    );
    layers.push(
      new TextLayer<Facility>({
        id: "facilities-glyph",
        data: data.facilities,
        getPosition: (f) => [f.lng, f.lat],
        getText: (f) => FACILITY_GLYPH[f.type] ?? "•",
        getSize: 12,
        getColor: [5, 10, 18, 255],
        fontWeight: 700,
        getTextAnchor: "middle",
        getAlignmentBaseline: "center",
        pickable: false,
      }),
    );
  }

  // 4. Signal junctions — live green-wave phase.
  if (vis.junctions && data.junctions.length) {
    const jdots = data.junctions.map((j) => {
      const ph = signalPhase(j, nowMs);
      return { ...j, _t: "junction" as const, green: ph.green, secsToGreen: ph.secsToGreen, secsLeft: ph.secsLeft };
    });
    layers.push(
      new ScatterplotLayer<(typeof jdots)[number]>({
        id: "junctions",
        data: jdots,
        getPosition: (j) => [j.lng, j.lat],
        getRadius: 60,
        radiusUnits: "meters",
        radiusMinPixels: 4,
        radiusMaxPixels: 9,
        stroked: true,
        lineWidthMinPixels: 1,
        getLineColor: [5, 10, 18, 220],
        getFillColor: (j) =>
          [...(j.green ? SIGNAL_GREEN_RGB : SIGNAL_RED_RGB), 235] as [number, number, number, number],
        pickable: true,
        updateTriggers: { getFillColor: Math.floor(nowMs / 1000) },
      }),
    );
  }

  // 5. Driver probes / fleet — animated dots that grow as drivers join.
  if (vis.drivers && drivers.length) {
    const dots = driverDots(drivers, congestion.cells, phase);
    layers.push(
      new ScatterplotLayer<DriverDot>({
        id: "drivers-glow",
        data: dots,
        getPosition: (d) => d.pos,
        getRadius: 8,
        radiusUnits: "pixels",
        getFillColor: [...DRIVER_RGB, 60] as [number, number, number, number],
        updateTriggers: { getPosition: phase },
      }),
    );
    layers.push(
      new ScatterplotLayer<DriverDot>({
        id: "drivers",
        data: dots,
        getPosition: (d) => d.pos,
        getRadius: 3.4,
        radiusUnits: "pixels",
        radiusMinPixels: 2,
        stroked: true,
        lineWidthMinPixels: 0.6,
        getLineColor: [5, 10, 18, 200],
        getFillColor: [...DRIVER_RGB, 235] as [number, number, number, number],
        pickable: true,
        updateTriggers: { getPosition: phase },
      }),
    );
  }

  // 6. Couriers, colour by status; selected gets a halo.
  if (vis.couriers) {
    layers.push(
      new ScatterplotLayer<Courier>({
        id: "couriers-glow",
        data: couriers,
        getPosition: (c) => [c.location.lng, c.location.lat],
        getRadius: 320,
        radiusUnits: "meters",
        radiusMinPixels: 14,
        radiusMaxPixels: 44,
        getFillColor: (c) =>
          [...(COURIER_RGB[c.status] ?? [200, 200, 200]), c.id === selectedCourierId ? 80 : 45] as [number, number, number, number],
        updateTriggers: { getFillColor: selectedCourierId },
      }),
    );
    layers.push(
      new ScatterplotLayer<Courier>({
        id: "couriers",
        data: couriers,
        getPosition: (c) => [c.location.lng, c.location.lat],
        getRadius: 130,
        radiusUnits: "meters",
        radiusMinPixels: 7,
        radiusMaxPixels: 20,
        stroked: true,
        lineWidthMinPixels: 2,
        getLineColor: (c) => (c.id === selectedCourierId ? [255, 255, 255, 255] : [5, 7, 13, 255]),
        getFillColor: (c) =>
          [...(COURIER_RGB[c.status] ?? [200, 200, 200]), 255] as [number, number, number, number],
        pickable: true,
        updateTriggers: { getLineColor: selectedCourierId },
      }),
    );
  }

  // 7. Disruptions — pulsing markers, classified bridge / event / congestion / road.
  if (vis.disruptions) {
    const disrPts = disruptions
      .map((d) => classifyDisruption(d, data.venues))
      .filter((d): d is NonNullable<typeof d> => d !== null)
      .map((d) => ({ ...d, _t: "disr" as const }));
    if (disrPts.length) {
      const pulse = 0.5 + 0.5 * Math.sin(phase * Math.PI * 2);
      layers.push(
        new ScatterplotLayer<(typeof disrPts)[number]>({
          id: "disruptions-pulse",
          data: disrPts,
          getPosition: (d) => [d.lng, d.lat],
          getRadius: 180 + pulse * 220,
          radiusUnits: "meters",
          radiusMinPixels: 10,
          radiusMaxPixels: 48,
          getFillColor: (d) =>
            [...(DISRUPTION_CLASS_RGB[d.cls] ?? DISRUPTION_CLASS_RGB.manual), Math.round(40 + pulse * 60)] as [number, number, number, number],
          updateTriggers: { getRadius: phase, getFillColor: phase },
        }),
      );
      layers.push(
        new ScatterplotLayer<(typeof disrPts)[number]>({
          id: "disruptions",
          data: disrPts,
          getPosition: (d) => [d.lng, d.lat],
          getRadius: 140,
          radiusUnits: "meters",
          radiusMinPixels: 7,
          radiusMaxPixels: 22,
          stroked: true,
          lineWidthMinPixels: 2,
          getLineColor: [255, 255, 255, 230],
          getFillColor: (d) =>
            [...(DISRUPTION_CLASS_RGB[d.cls] ?? DISRUPTION_CLASS_RGB.manual), 190] as [number, number, number, number],
          pickable: true,
        }),
      );
    }
  }

  return layers;
}

// Tooltip dispatcher — every pickable layer resolves to a readable card.
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
  if (o._t === "cong" || ("cell" in o && "congestion" in o && "n_probes" in o)) {
    const c = object as CongestionCell;
    return {
      className: "deck-tip",
      html: `<b>Congestion ${(c.congestion * 100).toFixed(0)}%</b><br/>${(c.speed_mps ?? 0).toFixed(1)} m/s · ${c.n_probes ?? 0} probes<br/><span class="tip-dim">live flywheel cell</span>`,
    };
  }
  if (o._t === "junction") {
    const j = object as Junction & { green: boolean; secsToGreen: number; secsLeft: number };
    const state = j.green
      ? `GREEN — ${j.secsLeft}s left`
      : `RED — green in ${j.secsToGreen}s`;
    return {
      className: "deck-tip",
      html: `<b>${j.name}</b><br/>${state}<br/><span class="tip-dim">cycle ${j.cycle_s}s · green ${j.green_s}s</span>`,
    };
  }
  if (o._t === "disr") {
    const d = object as { label: string; cls: string };
    return {
      className: "deck-tip",
      html: `<b>${d.label}</b><br/><span class="tip-dim">${d.cls} disruption</span>`,
    };
  }
  if ("type" in o && "lat" in o && "lng" in o && "name" in o && !("status" in o)) {
    const f = object as Facility;
    return {
      className: "deck-tip",
      html: `<b>${f.name}</b><br/><span class="tip-dim">${f.type} · ${f.id}</span>`,
    };
  }
  if ("status" in o && "location" in o) {
    const c = object as Courier;
    return { className: "deck-tip", html: `<b>${c.name ?? c.id}</b><br/><span class="tip-dim">courier · ${c.status}</span>` };
  }
  if ("priority" in o && "origin" in o) {
    const j = object as DeliveryJob;
    return {
      className: "deck-tip",
      html: `<b>${j.id} <span style="text-transform:uppercase">[${j.priority}]</span></b><br/>${j.origin.name ?? "?"} → ${j.destination.name ?? "?"}`,
    };
  }
  if ("job" in o) {
    const e = object as { job: DeliveryJob; kind: string };
    return { className: "deck-tip", html: `<b>${e.kind}</b><br/>${e.job.id} · ${e.job.priority}` };
  }
  if ("courier_id" in o && "path" in o) {
    return { className: "deck-tip", html: `<b>route</b><br/>${(object as { courier_id: string }).courier_id}` };
  }
  return null;
}

export default function MapView() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const overlayRef = useRef<MapboxOverlay | null>(null);
  const phaseRef = useRef(0);
  const rafRef = useRef<number | null>(null);
  const snapRef = useRef<Snapshot>({
    jobs: [],
    couriers: [],
    plan: null,
    disruptions: [],
    drivers: [],
    congestion: { cells: [] },
    selectedCourierId: null,
  });
  const dataRef = useRef<OptionalData>({ roads: [], buildings: [], facilities: [], junctions: [], venues: [] });
  const visRef = useRef<LayerVis>(DEFAULT_VIS);

  const [optional, setOptional] = useState<OptionalData>({
    roads: [],
    buildings: [],
    facilities: [],
    junctions: [],
    venues: [],
  });
  const [vis, setVis] = useState<LayerVis>(DEFAULT_VIS);
  const [counts, setCounts] = useState({
    jobs: 0,
    couriers: 0,
    routes: 0,
    drivers: 0,
    congestion: 0,
    disruptions: 0,
  });

  const selectCourier = useStore((s) => s.selectCourier);

  const toggle = (key: string) =>
    setVis((v) => ({ ...v, [key as LayerKey]: !v[key as LayerKey] }));

  // Keep refs in sync with store + counts for the imperative render loop / panels.
  useEffect(() => {
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
        routes: s.plan?.routes?.filter((r) => (r.polyline?.length ?? 0) >= 2).length ?? 0,
        drivers: drivers.length,
        congestion: s.congestion.cells.length,
        disruptions: s.disruptions.length,
      });
    };
    update();
    return useStore.subscribe(update);
  }, []);

  useEffect(() => {
    dataRef.current = optional;
  }, [optional]);
  useEffect(() => {
    visRef.current = vis;
  }, [vis]);

  // Load optional datasets once (each degrades gracefully on 404 / empty).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [roadsGj, buildingsGj, facRaw, jctRaw, evtRaw, twrRaw] = await Promise.all([
        fetchOptionalJson("/data/roads.geojson"),
        fetchOptionalJson("/data/buildings.geojson"),
        fetchOptional<unknown>("/data/facilities.json"),
        fetchOptional<unknown>("/data/junctions.json"),
        fetchOptional<unknown>("/data/events.json"),
        fetchOptional<unknown>("/data/towerbridge.json"),
      ]);
      if (cancelled) return;
      const roads = parseRoads(roadsGj);
      const buildings = parseBuildings(buildingsGj);
      const facilities = parseFacilities(facRaw);
      const junctions = parseJunctions(jctRaw);
      const venues = parseEventVenues(evtRaw);
      // bridge centre folds into the venue heuristic only via id-prefix; parse for log.
      const bridge = parseBridgeCentre(twrRaw);
      setOptional({ roads, buildings, facilities, junctions, venues });
      if (buildings.length) setVis((v) => ({ ...v, buildings: true }));
      const loaded: string[] = [];
      if (roads.length) loaded.push(`${roads.length} roads`);
      if (buildings.length) loaded.push(`${buildings.length} buildings`);
      if (facilities.length) loaded.push(`${facilities.length} facilities`);
      if (junctions.length) loaded.push(`${junctions.length} junctions`);
      if (venues.length) loaded.push(`${venues.length} event venues`);
      if (bridge) loaded.push("Tower Bridge");
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
      map.addControl(new mapboxgl.NavigationControl({ showCompass: true }), "bottom-left");
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
      map.addControl(new maplibregl.NavigationControl({ showCompass: true }), "bottom-left");
    }

    const m = map as maplibregl.Map;

    m.on("load", () => {
      m.easeTo({ zoom: INITIAL_VIEW.zoom + 0.3, duration: 2200, pitch: INITIAL_VIEW.pitch });
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
    const LOOP_SECONDS = 12;
    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      phaseRef.current = (phaseRef.current + dt / LOOP_SECONDS) % 1;
      overlay.setProps({
        layers: buildLayers(snapRef.current, dataRef.current, visRef.current, phaseRef.current, Date.now()),
      });
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      m.remove();
      overlayRef.current = null;
    };
  }, [selectCourier]);

  const hasBuildings = optional.buildings.length > 0;
  const trafficOn = optional.roads.length > 0 && vis.traffic;

  const layerDefs: LayerDef[] = useMemo(
    () => [
      { key: "congestion", label: "Congestion field", count: counts.congestion, color: "#ff3b5c", testid: "layer-toggle-congestion", present: true },
      { key: "drivers", label: "Driver probes", count: counts.drivers, color: "#78f0ff", testid: "layer-toggle-drivers", present: true },
      { key: "traffic", label: "Traffic flow", count: optional.roads.length, color: "#ffc24b", present: optional.roads.length > 0 },
      { key: "buildings", label: "3D buildings", count: optional.buildings.length, color: "#1e3c64", testid: "layer-toggle-buildings", present: hasBuildings },
      { key: "routes", label: "Courier routes", count: counts.routes, color: "#18f0ff", present: true },
      { key: "jobs", label: "Jobs (priority)", count: counts.jobs, color: "#ff3b5c", present: true },
      { key: "couriers", label: "Medical couriers", count: counts.couriers, color: "#23f0c7", present: true },
      { key: "facilities", label: "NHS facilities", count: optional.facilities.length, color: "#ff5678", present: optional.facilities.length > 0 },
      { key: "junctions", label: "Signal junctions", count: optional.junctions.length, color: "#23f0c7", present: optional.junctions.length > 0 },
      { key: "disruptions", label: "Disruptions", count: counts.disruptions, color: "#ff7a18", present: true },
    ],
    [counts, optional, hasBuildings],
  );

  const sources: SourceDef[] = useMemo(
    () => [
      { key: "congestion", label: "Congestion flywheel", count: counts.congestion, claimId: "flywheel-value", live: true },
      { key: "drivers", label: "Crowdsourced drivers", count: counts.drivers, claimId: "data-probes", live: true },
      { key: "facilities", label: "NHS facilities", count: optional.facilities.length, claimId: "data-facilities-complete" },
      { key: "junctions", label: "Signal junctions", count: optional.junctions.length, claimId: "data-junctions" },
      { key: "disruptions", label: "Disruptions (bridge/event)", count: counts.disruptions, claimId: "data-signals-valid", live: true },
      { key: "roads", label: "Road graph", count: optional.roads.length, claimId: "data-roadgraph" },
    ],
    [counts, optional],
  );

  const routeStatus = useMemo(
    () =>
      [
        `routes:${counts.routes}`,
        `cong:${counts.congestion}`,
        `drivers:${counts.drivers}`,
        `traffic:${trafficOn ? optional.roads.length : "off"}`,
        `buildings:${hasBuildings ? (vis.buildings ? "on" : "off") : "absent"}`,
      ].join(" · "),
    [counts, trafficOn, optional.roads.length, hasBuildings, vis.buildings],
  );

  return (
    <div className="map-wrap">
      <div ref={containerRef} className="map-root" />

      <div className="map-overlays">
        <div
          className="map-chip route-status"
          data-testid="route-layer-status"
          data-route-count={counts.routes}
          data-traffic={trafficOn ? "on" : "off"}
          data-buildings={hasBuildings ? (vis.buildings ? "on" : "off") : "absent"}
          data-congestion={counts.congestion}
          data-drivers={counts.drivers}
        >
          <span className="chip-led" /> {routeStatus}
        </div>

        <LayersPanel layers={layerDefs} vis={vis} onToggle={toggle} />
        <DataSourcePanel sources={sources} />
      </div>

      <MapLegend />
    </div>
  );
}
