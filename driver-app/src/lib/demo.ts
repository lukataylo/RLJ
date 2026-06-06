// Demo data so the app is fully usable with NO orchestrator running.
// (The driver endpoints in contracts/driver-api.md are not yet implemented
//  server-side, so these keep the green-wave / heat / stats screens alive.)

import type {
  CongestionCell,
  DeliveryJob,
  DriverGuidance,
  GpsFix,
  LatLng,
  Plan,
  SignalAdvice,
} from "../types";
import { LONDON_LOOP } from "../api";

const iso = (minsFromNow: number) =>
  new Date(Date.now() + minsFromNow * 60_000).toISOString();

// A plausible day of medical-courier jobs around central London. One is in
// transit (the active delivery), two are upcoming, three are completed.
export function demoJobs(): DeliveryJob[] {
  return [
    {
      id: "job-active",
      type: "sample_pickup",
      origin: { lat: 51.4995, lng: -0.1248, name: "St Thomas' Hospital lab" },
      destination: { lat: 51.5081, lng: -0.117, name: "The Doctors Laboratory" },
      priority: "stat",
      time_window: { ready_at: iso(-12), due_by: iso(18) },
      cold_chain: true,
      status: "in_transit",
      created_at: iso(-22),
    },
    {
      id: "job-up1",
      type: "med_delivery",
      origin: { lat: 51.5074, lng: -0.1278, name: "UCLH Pharmacy" },
      destination: { lat: 51.5033, lng: -0.1195, name: "St Guy's Day Unit" },
      priority: "urgent",
      time_window: { due_by: iso(52) },
      cold_chain: false,
      status: "assigned",
      created_at: iso(-8),
    },
    {
      id: "job-up2",
      type: "sample_pickup",
      origin: { lat: 51.5012, lng: -0.1419, name: "Victoria GP surgery" },
      destination: { lat: 51.5108, lng: -0.122, name: "Royal Free Histopathology" },
      priority: "routine",
      time_window: { due_by: iso(120) },
      status: "new",
      created_at: iso(-4),
    },
    {
      id: "job-done1",
      type: "med_delivery",
      origin: { lat: 51.5052, lng: -0.1153, name: "Holborn Pharmacy" },
      destination: { lat: 51.4975, lng: -0.1357, name: "Pimlico Clinic" },
      priority: "urgent",
      status: "delivered",
      created_at: iso(-95),
    },
    {
      id: "job-done2",
      type: "sample_pickup",
      origin: { lat: 51.5108, lng: -0.122, name: "Covent Garden GP" },
      destination: { lat: 51.4995, lng: -0.1248, name: "St Thomas' Hospital lab" },
      priority: "routine",
      status: "delivered",
      created_at: iso(-140),
    },
    {
      id: "job-failed1",
      type: "med_delivery",
      origin: { lat: 51.5081, lng: -0.117, name: "The Doctors Laboratory" },
      destination: { lat: 51.5074, lng: -0.1278, name: "Soho Walk-in" },
      priority: "routine",
      status: "failed",
      created_at: iso(-180),
    },
  ];
}

// A single-courier plan whose route threads the active + upcoming jobs along
// the central-London loop (so the map + turn-by-turn have a real path).
export function demoPlan(): Plan {
  return {
    routes: [
      {
        courier_id: "drv-demo",
        polyline: LONDON_LOOP,
        total_time_s: 1850,
        total_distance_m: 5200,
        feasible: true,
        stops: [
          { job_id: "job-active", kind: "pickup", location: { lat: 51.4995, lng: -0.1248 }, sequence: 0, eta: iso(-2) },
          { job_id: "job-active", kind: "dropoff", location: { lat: 51.5081, lng: -0.117 }, sequence: 1, eta: iso(16), window_met: true },
          { job_id: "job-up1", kind: "pickup", location: { lat: 51.5074, lng: -0.1278 }, sequence: 2, eta: iso(24) },
          { job_id: "job-up1", kind: "dropoff", location: { lat: 51.5033, lng: -0.1195 }, sequence: 3, eta: iso(40), window_met: true },
          { job_id: "job-up2", kind: "pickup", location: { lat: 51.5012, lng: -0.1419 }, sequence: 4, eta: iso(58) },
          { job_id: "job-up2", kind: "dropoff", location: { lat: 51.5108, lng: -0.122 }, sequence: 5, eta: iso(86), window_met: true },
        ],
      },
    ],
    generated_at: new Date().toISOString(),
  };
}

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
