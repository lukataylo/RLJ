// The live operations map: MapLibre GL basemap (dark, no token) + deck.gl overlay.
//
// Layers (overlaid via MapboxOverlay):
//   - job origin->destination pairs (LineLayer, colour by priority)
//   - job endpoints (ScatterplotLayer)
//   - plan routes (PathLayer from each route.polyline)
//   - couriers (ScatterplotLayer, colour by status)
//   - animated "trip head" marker interpolated along each route polyline
//   - disruption markers (road closures / affected areas)

import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import { MapboxOverlay } from "@deck.gl/mapbox";
import type { Layer } from "@deck.gl/core";
import { ScatterplotLayer, LineLayer, PathLayer } from "@deck.gl/layers";
import { useStore } from "./store";
import type { Courier, DeliveryJob, LatLng, Plan, Priority } from "./types";

// London centre.
const INITIAL_VIEW = { center: [-0.118, 51.503] as [number, number], zoom: 11.2 };

// ---- colours (RGBA 0-255) ----
const PRIORITY_RGB: Record<Priority, [number, number, number]> = {
  stat: [229, 57, 53], // red
  urgent: [255, 179, 0], // amber
  routine: [30, 136, 229], // blue
};
const COURIER_RGB: Record<string, [number, number, number]> = {
  idle: [76, 175, 80], // green
  enroute: [0, 229, 255], // cyan
  offline: [120, 120, 130], // grey
};
const ROUTE_RGB: [number, number, number] = [0, 229, 255];
const DISRUPTION_RGB: [number, number, number] = [255, 82, 82];

// Free, token-less dark raster basemap (CARTO dark). Works at the venue without an account.
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
    { id: "bg", type: "background", paint: { "background-color": "#0a0d14" } },
    { id: "carto", type: "raster", source: "carto" },
  ],
};

// ---- geometry: interpolate a position a fraction `f` (0..1) along a polyline ----
function pointAlong(poly: LatLng[], f: number): [number, number] | null {
  if (!poly || poly.length === 0) return null;
  if (poly.length === 1) return [poly[0].lng, poly[0].lat];
  const segLens: number[] = [];
  let total = 0;
  for (let i = 0; i < poly.length - 1; i++) {
    const dx = poly[i + 1].lng - poly[i].lng;
    const dy = poly[i + 1].lat - poly[i].lat;
    const len = Math.hypot(dx, dy);
    segLens.push(len);
    total += len;
  }
  if (total === 0) return [poly[0].lng, poly[0].lat];
  let target = f * total;
  for (let i = 0; i < segLens.length; i++) {
    if (target <= segLens[i] || i === segLens.length - 1) {
      const t = segLens[i] === 0 ? 0 : target / segLens[i];
      return [
        poly[i].lng + (poly[i + 1].lng - poly[i].lng) * t,
        poly[i].lat + (poly[i + 1].lat - poly[i].lat) * t,
      ];
    }
    target -= segLens[i];
  }
  const last = poly[poly.length - 1];
  return [last.lng, last.lat];
}

interface Snapshot {
  jobs: DeliveryJob[];
  couriers: Courier[];
  plan: Plan | null;
  disruptions: { id: string; kind: string; geometry?: LatLng[] }[];
}

function buildLayers(snap: Snapshot, phase: number) {
  const { jobs, couriers, plan, disruptions } = snap;
  const layers: Layer[] = [];

  // 1. Job origin -> destination pairs, colour by priority.
  layers.push(
    new LineLayer<DeliveryJob>({
      id: "job-pairs",
      data: jobs,
      getSourcePosition: (j) => [j.origin.lng, j.origin.lat],
      getTargetPosition: (j) => [j.destination.lng, j.destination.lat],
      getColor: (j) => [...PRIORITY_RGB[j.priority], 160] as [number, number, number, number],
      getWidth: (j) => (j.priority === "stat" ? 4 : j.priority === "urgent" ? 3 : 2),
      widthUnits: "pixels",
      pickable: true,
    }),
  );

  // 2. Job endpoints (origins hollow-ish small, destinations larger).
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
      radiusMaxPixels: 16,
      stroked: true,
      lineWidthMinPixels: 2,
      getLineColor: [255, 255, 255, 220],
      getFillColor: (d) =>
        [...PRIORITY_RGB[d.job.priority], d.kind === "dest" ? 230 : 110] as [
          number,
          number,
          number,
          number,
        ],
      pickable: true,
    }),
  );

  // 3. Plan routes — one PathLayer fed from each route's polyline.
  const routePaths = (plan?.routes ?? [])
    .filter((r) => r.polyline && r.polyline.length >= 2)
    .map((r) => ({
      courier_id: r.courier_id,
      path: r.polyline!.map((p) => [p.lng, p.lat] as [number, number]),
    }));
  layers.push(
    new PathLayer<(typeof routePaths)[number]>({
      id: "routes",
      data: routePaths,
      getPath: (d) => d.path,
      getColor: [...ROUTE_RGB, 200] as [number, number, number, number],
      getWidth: 5,
      widthUnits: "pixels",
      capRounded: true,
      jointRounded: true,
      pickable: true,
    }),
  );

  // 4. Animated trip-head markers moving along each route polyline.
  const heads = (plan?.routes ?? [])
    .filter((r) => r.polyline && r.polyline.length >= 2)
    .map((r) => ({
      courier_id: r.courier_id,
      pos: pointAlong(r.polyline!, phase),
    }))
    .filter((h) => h.pos) as { courier_id: string; pos: [number, number] }[];
  layers.push(
    new ScatterplotLayer<(typeof heads)[number]>({
      id: "trip-heads",
      data: heads,
      getPosition: (d) => d.pos,
      getRadius: 10,
      radiusUnits: "pixels",
      stroked: true,
      lineWidthMinPixels: 2,
      getLineColor: [255, 255, 255, 255],
      getFillColor: [...ROUTE_RGB, 255] as [number, number, number, number],
      updateTriggers: { getPosition: phase },
    }),
  );

  // 5. Couriers, colour by status.
  layers.push(
    new ScatterplotLayer<Courier>({
      id: "couriers",
      data: couriers,
      getPosition: (c) => [c.location.lng, c.location.lat],
      getRadius: 130,
      radiusUnits: "meters",
      radiusMinPixels: 7,
      radiusMaxPixels: 22,
      stroked: true,
      lineWidthMinPixels: 2,
      getLineColor: [10, 13, 20, 255],
      getFillColor: (c) =>
        [...(COURIER_RGB[c.status] ?? [200, 200, 200]), 255] as [
          number,
          number,
          number,
          number,
        ],
      pickable: true,
    }),
  );

  // 6. Disruptions — markers at the first geometry point (or whole segment).
  const disrPts = disruptions
    .filter((d) => d.geometry && d.geometry.length)
    .map((d) => ({ id: d.id, kind: d.kind, loc: d.geometry![0] }));
  if (disrPts.length) {
    layers.push(
      new ScatterplotLayer<(typeof disrPts)[number]>({
        id: "disruptions",
        data: disrPts,
        getPosition: (d) => [d.loc.lng, d.loc.lat],
        getRadius: 160,
        radiusUnits: "meters",
        radiusMinPixels: 8,
        radiusMaxPixels: 26,
        stroked: true,
        lineWidthMinPixels: 3,
        getLineColor: [255, 255, 255, 230],
        getFillColor: [...DISRUPTION_RGB, 120] as [number, number, number, number],
        pickable: true,
      }),
    );
  }

  return layers;
}

export default function MapView() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const overlayRef = useRef<MapboxOverlay | null>(null);
  const phaseRef = useRef(0);
  const rafRef = useRef<number | null>(null);

  // We read store data imperatively inside the animation loop to avoid
  // re-creating the whole deck overlay on every state change.
  const snapRef = useRef<Snapshot>({ jobs: [], couriers: [], plan: null, disruptions: [] });

  // Keep snapRef in sync with the store.
  useEffect(() => {
    const update = () => {
      const s = useStore.getState();
      snapRef.current = {
        jobs: Object.values(s.jobs),
        couriers: Object.values(s.couriers),
        plan: s.plan,
        disruptions: s.disruptions,
      };
    };
    update();
    return useStore.subscribe(update);
  }, []);

  // Init map + overlay once.
  useEffect(() => {
    if (!containerRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: MAP_STYLE,
      center: INITIAL_VIEW.center,
      zoom: INITIAL_VIEW.zoom,
      attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");

    const overlay = new MapboxOverlay({
      interleaved: false,
      layers: [],
      getTooltip: ({ object }) => {
        if (!object) return null;
        const o = object as Record<string, unknown>;
        if ("status" in o && "location" in o) {
          const c = object as Courier;
          return { text: `${c.name ?? c.id} — ${c.status}` };
        }
        if ("priority" in o) {
          const j = object as DeliveryJob;
          return {
            text: `${j.id} [${j.priority}] ${j.origin.name ?? "?"} -> ${
              j.destination.name ?? "?"
            }`,
          };
        }
        if ("job" in o) {
          const e = object as { job: DeliveryJob; kind: string };
          return { text: `${e.kind}: ${e.job.id} (${e.job.priority})` };
        }
        if ("kind" in o && "loc" in o) {
          return { text: `disruption: ${(object as { kind: string }).kind}` };
        }
        return null;
      },
    });
    map.addControl(overlay);
    overlayRef.current = overlay;

    // Animation loop: advance phase, rebuild layers.
    let last = performance.now();
    const LOOP_SECONDS = 12; // time for a courier to traverse its route once
    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      phaseRef.current = (phaseRef.current + dt / LOOP_SECONDS) % 1;
      overlay.setProps({ layers: buildLayers(snapRef.current, phaseRef.current) });
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      map.remove();
      overlayRef.current = null;
    };
  }, []);

  return <div ref={containerRef} className="map-root" />;
}
