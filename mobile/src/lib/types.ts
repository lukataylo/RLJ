// TypeScript mirror of contracts/schemas.json — field names kept EXACT so the
// payloads round-trip with the FastAPI orchestrator (orchestrator/models.py).

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

export type Priority = "stat" | "urgent" | "routine";
export type JobType = "sample_pickup" | "med_delivery";
export type JobStatus =
  | "new"
  | "assigned"
  | "in_transit"
  | "delivered"
  | "failed";

export interface TimeWindow {
  ready_at?: string; // ISO-8601, earliest pickup
  due_by?: string; // ISO-8601, clinical deadline at destination
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

export type VehicleType = "van" | "scooter" | "bike";
export type CourierStatus = "idle" | "enroute" | "offline";

export interface Courier {
  id: string;
  name?: string;
  location: Location;
  capacity?: number;
  cold_capable?: boolean;
  vehicle_type?: VehicleType;
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

export interface Objective {
  total_time_s?: number;
  windows_met?: number;
  windows_total?: number;
  solver?: string;
  solve_ms?: number;
}

export interface Plan {
  routes: Route[];
  unassigned?: string[];
  objective?: Objective;
  generated_at?: string;
}

export interface DisruptionEvent {
  id?: string;
  kind: "road_closure" | "traffic" | "courier_down";
  geometry?: LatLng[];
  courier_id?: string | null;
  source?: "tfl" | "manual";
  at?: string;
}

// ---- Driver flywheel (telemetry + green-wave) -----------------------------

export type DriverVehicle = "bike" | "scooter" | "car" | "van";

export interface Driver {
  id: string;
  name?: string;
  vehicle_type: DriverVehicle;
  consent: boolean;
  joined_at?: string;
  points?: number;
}

export interface DriverPing {
  driver_id: string;
  lat: number;
  lng: number;
  speed_mps?: number;
  heading_deg?: number;
  ts: string; // ISO-8601
}

export interface TelemetryBatch {
  pings: DriverPing[];
}

export interface TelemetryAck {
  accepted: number;
  rejected: number;
  cells_updated: number;
}

export interface SignalAdvice {
  driver_id?: string;
  message: string;
  target_speed_mps?: number;
  junction?: Location;
  seconds_to_green?: number;
  confidence?: number;
}

export interface CongestionCell {
  cell: string;
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

// ---- Auth -----------------------------------------------------------------

export interface LoginResponse {
  access_token: string;
  token_type: string;
  role: string;
}

export interface Me {
  id: number;
  email: string;
  role: string;
}

// ---- Local-only helpers (not in schemas) ----------------------------------

export interface GpsFix {
  lat: number;
  lng: number;
  speed_mps: number;
  heading_deg: number;
}

/** A turn-by-turn maneuver, either from Mapbox Directions or derived locally. */
export interface Maneuver {
  instruction: string; // spoken / displayed text
  type: string; // turn | continue | arrive | depart | …
  modifier?: string; // left | right | straight | …
  location: LatLng; // where the maneuver happens
  distanceM: number; // length of the step leading to this maneuver
}

export interface DirectionsResult {
  geometry: LatLng[]; // path to draw on the map
  maneuvers: Maneuver[];
  source: "mapbox" | "polyline";
}
