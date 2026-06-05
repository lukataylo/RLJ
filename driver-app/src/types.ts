// TypeScript mirror of contracts/schemas.json — keep field names EXACT.
// Only the entities the driver-app touches (driver flywheel + green-wave) plus
// the shared LatLng/Location primitives.

export interface LatLng {
  lat: number;
  lng: number;
}

export interface Location {
  lat: number;
  lng: number;
  name?: string;
  facility_id?: string;
}

// ---- Driver flywheel entities (schemas.json $defs) -------------------------

export type VehicleType = "bike" | "scooter" | "car" | "van";

/** A crowdsourced courier who shares GPS in return for green-wave routing. */
export interface Driver {
  id: string;
  name?: string;
  vehicle_type: VehicleType;
  consent: boolean; // explicit consent to share location
  joined_at?: string; // ISO-8601
  points?: number; // gamified contribution score
}

/** One GPS probe from a driver. The raw material of the congestion flywheel. */
export interface DriverPing {
  driver_id: string;
  lat: number;
  lng: number;
  speed_mps?: number;
  heading_deg?: number;
  ts: string; // ISO-8601
}

export interface CongestionCell {
  cell: string; // rounded lat_lng grid id
  lat: number;
  lng: number;
  congestion: number; // 0=free-flow, 1=jammed
  speed_mps?: number;
  n_probes?: number;
  updated_at?: string;
}

export interface CongestionField {
  cells: CongestionCell[];
  generated_at?: string;
}

/** Green-wave advice: a speed that arrives at the next junction on green. */
export interface SignalAdvice {
  driver_id?: string;
  message: string;
  target_speed_mps?: number;
  junction?: Location;
  seconds_to_green?: number;
  confidence?: number;
}

export interface DriverContribution {
  pings?: number;
  couriers_helped?: number;
}

export interface DriverGuidance {
  driver_id: string;
  status: string;
  eta?: string | null;
  route_polyline?: LatLng[];
  signal_advice?: SignalAdvice | null;
  contribution?: DriverContribution;
}

/** POST /telemetry body. */
export interface TelemetryBatch {
  pings: DriverPing[];
}

/** POST /telemetry response (contracts/driver-api.md). */
export interface TelemetryAck {
  accepted: number;
  rejected: number;
  cells_updated: number;
}

// ---- Local-only helper type (not in schemas) ------------------------------

/** A single resolved position fix from GPS or the simulator. */
export interface GpsFix {
  lat: number;
  lng: number;
  speed_mps: number;
  heading_deg: number;
}
