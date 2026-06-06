// Point-cloud builders for the Three.js LiDAR scene (ported verbatim from Square
// Mile Pulse). `buildPointCloud` synthesises a scan from OSM footprints (used as
// a fallback when the real LiDAR asset is missing); `buildFacades` extrudes
// building walls to fill the vertical faces that aerial LiDAR misses.

import { project, type GeoPoint } from "./scene-geo";

export interface Building {
  id?: string;
  name?: string;
  height: number;
  footprint: GeoPoint[];
}

export interface BuildingsResponse {
  center: GeoPoint;
  buildings: Building[];
  count?: number;
}

// Deterministic pseudo-random so the scan looks stable across renders.
function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Cyberpunk teal gradient: deep base -> bright cyan crown.
const BASE = [0.05, 0.32, 0.42]; // #0e5f6e-ish
const TOP = [0.56, 0.97, 1.0]; // #8ff7ff
const ACCENT = [0.95, 0.25, 0.55]; // magenta sparks

function colorAt(yFrac: number, spark: boolean, out: number[], i: number) {
  const t = Math.min(1, yFrac);
  if (spark) {
    out[i] = ACCENT[0];
    out[i + 1] = ACCENT[1];
    out[i + 2] = ACCENT[2];
    return;
  }
  out[i] = BASE[0] + (TOP[0] - BASE[0]) * t;
  out[i + 1] = BASE[1] + (TOP[1] - BASE[1]) * t;
  out[i + 2] = BASE[2] + (TOP[2] - BASE[2]) * t;
}

export interface PointCloud {
  positions: Float32Array;
  colors: Float32Array;
  count: number;
  bounds: { x: number; z: number }; // half-extents
}

const WALL_STEP = 4.5; // metres between scan points
const COLOR_CAP = 140; // height (m) at which the crown colour saturates
const MAX_POINTS = 520_000;

export function buildPointCloud(buildings: Building[], center: GeoPoint): PointCloud {
  const pos: number[] = [];
  const col: number[] = [];
  const tmp = [0, 0, 0];
  let maxX = 1;
  let maxZ = 1;

  const rng = mulberry32(1337);

  for (const b of buildings) {
    if (pos.length / 3 > MAX_POINTS) break;
    const ring = b.footprint.map((p) => project(p, center));
    if (ring.length < 2) continue;
    const h = b.height;
    const vSteps = Math.max(2, Math.min(60, Math.round(h / WALL_STEP)));

    for (let e = 0; e < ring.length - 1; e++) {
      const [x1, z1] = ring[e];
      const [x2, z2] = ring[e + 1];
      const len = Math.hypot(x2 - x1, z2 - z1);
      const hSteps = Math.max(1, Math.min(40, Math.round(len / WALL_STEP)));
      for (let i = 0; i <= hSteps; i++) {
        const fx = i / hSteps;
        const px = x1 + (x2 - x1) * fx;
        const pz = z1 + (z2 - z1) * fx;
        for (let v = 0; v <= vSteps; v++) {
          const fy = v / vSteps;
          const y = fy * h;
          // LiDAR-style jitter
          const jx = (rng() - 0.5) * 1.2;
          const jz = (rng() - 0.5) * 1.2;
          const jy = (rng() - 0.5) * 1.2;
          pos.push(px + jx, y + jy, pz + jz);
          const spark = rng() > 0.992;
          colorAt((y / COLOR_CAP) * (0.6 + 0.4 * rng()), spark, tmp, 0);
          col.push(tmp[0], tmp[1], tmp[2]);
          maxX = Math.max(maxX, Math.abs(px));
          maxZ = Math.max(maxZ, Math.abs(pz));
        }
      }
    }

    // Sparse roof fill for larger footprints — gives the "scanned rooftop" look.
    let minrx = Infinity, maxrx = -Infinity, minrz = Infinity, maxrz = -Infinity;
    for (const [x, z] of ring) {
      minrx = Math.min(minrx, x); maxrx = Math.max(maxrx, x);
      minrz = Math.min(minrz, z); maxrz = Math.max(maxrz, z);
    }
    const area = (maxrx - minrx) * (maxrz - minrz);
    if (area > 250) {
      const n = Math.min(60, Math.round(area / 60));
      for (let k = 0; k < n; k++) {
        const rx = minrx + rng() * (maxrx - minrx);
        const rz = minrz + rng() * (maxrz - minrz);
        if (pointInRing(rx, rz, ring)) {
          pos.push(rx, h + (rng() - 0.5) * 1.2, rz);
          colorAt((h / COLOR_CAP) * (0.7 + 0.3 * rng()), rng() > 0.99, tmp, 0);
          col.push(tmp[0], tmp[1], tmp[2]);
        }
      }
    }
  }

  return {
    positions: new Float32Array(pos),
    colors: new Float32Array(col),
    count: pos.length / 3,
    bounds: { x: maxX, z: maxZ },
  };
}

/**
 * Facade-only point sampler. Aerial LiDAR misses vertical walls, so we extrude
 * the OSM building footprints up to their real heights to fill in skyscraper
 * faces. Tall buildings get denser vertical sampling so they read as solid.
 */
export function buildFacades(buildings: Building[], center: GeoPoint): PointCloud {
  const pos: number[] = [];
  const col: number[] = [];
  const tmp = [0, 0, 0];
  const rng = mulberry32(99);
  const STEP = 3.2;

  for (const b of buildings) {
    if (b.height < 6) continue; // skip low clutter
    const ring = b.footprint.map((p) => project(p, center));
    if (ring.length < 2) continue;
    const h = b.height;
    const tall = h > 55;
    const vSteps = Math.max(3, Math.min(90, Math.round(h / (tall ? 2.4 : STEP))));

    for (let e = 0; e < ring.length - 1; e++) {
      const [x1, z1] = ring[e];
      const [x2, z2] = ring[e + 1];
      const len = Math.hypot(x2 - x1, z2 - z1);
      const hSteps = Math.max(1, Math.min(48, Math.round(len / STEP)));
      for (let i = 0; i <= hSteps; i++) {
        const fx = i / hSteps;
        const px = x1 + (x2 - x1) * fx;
        const pz = z1 + (z2 - z1) * fx;
        for (let v = 1; v <= vSteps; v++) {
          const y = (v / vSteps) * h;
          pos.push(
            px + (rng() - 0.5) * 0.8,
            y + (rng() - 0.5) * 0.8,
            pz + (rng() - 0.5) * 0.8,
          );
          colorAt((y / COLOR_CAP) * (0.7 + 0.3 * rng()), false, tmp, 0);
          col.push(tmp[0], tmp[1], tmp[2]);
        }
      }
    }
  }

  return {
    positions: new Float32Array(pos),
    colors: new Float32Array(col),
    count: pos.length / 3,
    bounds: { x: 1, z: 1 },
  };
}

function pointInRing(x: number, z: number, ring: [number, number][]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, zi] = ring[i];
    const [xj, zj] = ring[j];
    const intersect =
      zi > z !== zj > z && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}
