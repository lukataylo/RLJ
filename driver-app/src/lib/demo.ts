// Demo data so the app is fully usable with NO orchestrator running.
// (The driver endpoints in contracts/driver-api.md are not yet implemented
//  server-side, so these keep the green-wave / heat / stats screens alive.)

import type {
  CongestionCell,
  DriverGuidance,
  GpsFix,
  LatLng,
  SignalAdvice,
} from "../types";
import { LONDON_LOOP } from "../api";

/** A grid of congestion cells around central London, deterministic per tick. */
export function demoCongestion(tick = 0): CongestionCell[] {
  const cells: CongestionCell[] = [];
  const lat0 = 51.49;
  const lng0 = -0.15;
  const step = 0.006;
  for (let i = 0; i < 8; i++) {
    for (let j = 0; j < 8; j++) {
      const lat = lat0 + i * step;
      const lng = lng0 + j * step;
      // smooth pseudo-field + slow drift so the heat "breathes"
      const base =
        0.5 +
        0.45 *
          Math.sin(i * 0.9 + tick * 0.15) *
          Math.cos(j * 0.7 - tick * 0.1);
      const congestion = Math.max(0, Math.min(1, base));
      cells.push({
        cell: `${lat.toFixed(3)}_${lng.toFixed(3)}`,
        lat,
        lng,
        congestion,
        speed_mps: 12 * (1 - congestion) + 1,
        n_probes: 3 + Math.round(congestion * 40),
        updated_at: new Date().toISOString(),
      });
    }
  }
  return cells;
}

/** Green-wave advice derived from the driver's current fix. */
export function demoAdvice(driverId: string, fix: GpsFix | null): SignalAdvice {
  const target = 7.8; // ~28 km/h, the classic green-wave speed
  const secs = 8 + Math.round(Math.random() * 14);
  const here = fix ?? { lat: 51.5033, lng: -0.1195 };
  return {
    driver_id: driverId,
    message: `Ease to ${Math.round(target * 3.6)} km/h to catch the next green`,
    target_speed_mps: target,
    junction: { lat: here.lat + 0.004, lng: here.lng + 0.002, name: "Next signal" },
    seconds_to_green: secs,
    confidence: 0.82,
  };
}

/** Guidance (route + contribution) — contribution grows with pings sent. */
export function demoGuidance(
  driverId: string,
  pings: number,
  fix: GpsFix | null,
): DriverGuidance {
  return {
    driver_id: driverId,
    status: "rolling",
    eta: null,
    route_polyline: LONDON_LOOP as LatLng[],
    signal_advice: demoAdvice(driverId, fix),
    contribution: {
      pings,
      couriers_helped: Math.floor(pings / 4),
    },
  };
}
