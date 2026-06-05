// Minimal GeoJSON parsing for the optional traffic-roads and 3D-building layers.
// Everything here degrades gracefully: malformed / missing data yields [].

export interface RoadPath {
  path: [number, number][];
  congestion: number; // 0..1
}

export interface BuildingPoly {
  polygon: [number, number][];
  height: number;
}

type GJ = { type?: string; features?: GJFeature[] };
type GJFeature = { geometry?: GJGeom; properties?: Record<string, unknown> };
type GJGeom = { type?: string; coordinates?: unknown };

// Deterministic pseudo-congestion when a feature carries no traffic property,
// so the layer still reads as a green/amber/red network.
function hashCongestion(coord: [number, number]): number {
  const v = Math.abs(Math.sin(coord[0] * 12.9898 + coord[1] * 78.233) * 43758.5453);
  return v - Math.floor(v);
}

function readCongestion(props: Record<string, unknown> | undefined, sample: [number, number]): number {
  if (props) {
    for (const key of ["congestion", "level", "load"]) {
      const v = props[key];
      if (typeof v === "number") return Math.max(0, Math.min(1, v > 1 ? v / 100 : v));
    }
    const jam = props["jamFactor"] ?? props["jam_factor"];
    if (typeof jam === "number") return Math.max(0, Math.min(1, jam / 10));
    const speed = props["speed"] ?? props["speed_kph"];
    if (typeof speed === "number") return Math.max(0, Math.min(1, 1 - speed / 60));
  }
  return hashCongestion(sample);
}

export function parseRoads(gj: GJ | null): RoadPath[] {
  if (!gj?.features) return [];
  const out: RoadPath[] = [];
  for (const f of gj.features) {
    const g = f.geometry;
    if (!g?.coordinates) continue;
    const lines: [number, number][][] = [];
    if (g.type === "LineString") {
      lines.push(g.coordinates as [number, number][]);
    } else if (g.type === "MultiLineString") {
      for (const l of g.coordinates as [number, number][][]) lines.push(l);
    }
    for (const line of lines) {
      if (!Array.isArray(line) || line.length < 2) continue;
      const path = line
        .filter((c) => Array.isArray(c) && c.length >= 2)
        .map((c) => [c[0], c[1]] as [number, number]);
      if (path.length < 2) continue;
      out.push({ path, congestion: readCongestion(f.properties, path[0]) });
    }
  }
  return out;
}

function readHeight(props: Record<string, unknown> | undefined): number {
  if (props) {
    for (const key of ["height", "render_height", "building_height"]) {
      const v = props[key];
      if (typeof v === "number" && v > 0) return v;
      if (typeof v === "string" && parseFloat(v) > 0) return parseFloat(v);
    }
    const levels = props["building:levels"] ?? props["levels"];
    const n = typeof levels === "number" ? levels : typeof levels === "string" ? parseFloat(levels) : NaN;
    if (!Number.isNaN(n) && n > 0) return n * 3;
  }
  return 12;
}

export function parseBuildings(gj: GJ | null): BuildingPoly[] {
  if (!gj?.features) return [];
  const out: BuildingPoly[] = [];
  for (const f of gj.features) {
    const g = f.geometry;
    if (!g?.coordinates) continue;
    const height = readHeight(f.properties);
    const rings: [number, number][][] = [];
    if (g.type === "Polygon") {
      const ring = (g.coordinates as [number, number][][])[0];
      if (ring) rings.push(ring);
    } else if (g.type === "MultiPolygon") {
      for (const poly of g.coordinates as [number, number][][][]) {
        if (poly[0]) rings.push(poly[0]);
      }
    }
    for (const ring of rings) {
      if (!Array.isArray(ring) || ring.length < 3) continue;
      const polygon = ring
        .filter((c) => Array.isArray(c) && c.length >= 2)
        .map((c) => [c[0], c[1]] as [number, number]);
      if (polygon.length >= 3) out.push({ polygon, height });
    }
  }
  return out;
}

/** Fetch JSON from public/, returning null on 404 / non-JSON / parse error. */
export async function fetchOptionalJson(url: string): Promise<GJ | null> {
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) return null;
    const ct = res.headers.get("content-type") ?? "";
    if (!ct.includes("json") && !ct.includes("octet-stream")) return null;
    return (await res.json()) as GJ;
  } catch {
    return null;
  }
}
