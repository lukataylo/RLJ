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

// ---- Jobs / routing entities (schemas.json $defs) --------------------------

export type Priority = "stat" | "urgent" | "routine";
export type JobType = "sample_pickup" | "med_delivery";
export type JobStatus = "new" | "assigned" | "in_transit" | "delivered" | "failed";

export interface TimeWindow {
  ready_at?: string;
  due_by?: string;
}

export interface DeliveryJob {
  id: string;
  type: JobType;
  origin: Location;
  destination: Location;
  priority: Priority;
  time_window?: TimeWindow;
  cold_chain?: boolean;
  capacity_units?: number;
  status: JobStatus;
  raw_text?: string;
  created_at?: string;
}

export type CourierStatus = "idle" | "enroute" | "offline";

export interface Courier {
  id: string;
  name?: string;
  location: Location;
  capacity?: number;
  cold_capable?: boolean;
  vehicle_type?: "van" | "scooter" | "bike";
  status: CourierStatus;
  assigned_route_id?: string | null;
  phone?: string;
}

export interface Stop {
  job_id: string;
  kind: "pickup" | "dropoff";
  location: Location;
  sequence: number;
  eta?: string;
  window_met?: boolean | null;
}

export interface Route {
  courier_id: string;
  stops: Stop[];
  polyline?: LatLng[];
  total_time_s?: number;
  total_distance_m?: number;
  feasible?: boolean;
}

export interface Plan {
  routes: Route[];
  unassigned?: string[];
  generated_at?: string;
}

/** A turn-by-turn maneuver (Mapbox Directions or derived from the polyline). */
export interface Maneuver {
  instruction: string;
  type: string;
  modifier?: string;
  location: LatLng;
  distanceM: number;
}

export interface DirectionsResult {
  geometry: LatLng[];
  maneuvers: Maneuver[];
  source: "mapbox" | "polyline";
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
