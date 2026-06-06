// TypeScript mirror of contracts/schemas.json — keep field names EXACT.
// Canonical entities exchanged between voice, routing, frontend and the orchestrator.

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

export interface TimeWindow {
  ready_at?: string; // ISO-8601 UTC — earliest pickup
  due_by?: string; // ISO-8601 UTC — clinical deadline at destination
}

export type JobType = "sample_pickup" | "med_delivery";
export type JobStatus = "new" | "assigned" | "in_transit" | "delivered" | "failed";

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

// Courier vehicle — drives the van/scooter/bike icon in the UI (schemas.json Courier).
export type CourierVehicle = "van" | "scooter" | "bike";

export interface Courier {
  id: string;
  name?: string;
  location: Location;
  capacity?: number;
  cold_capable?: boolean;
  vehicle_type?: CourierVehicle;
  status: CourierStatus;
  assigned_route_id?: string | null;
  phone?: string;
}

export type StopKind = "pickup" | "dropoff";

export interface Stop {
  job_id: string;
  kind: StopKind;
  location: Location;
  sequence: number; // order within the route, 0-based
  eta?: string;
  window_met?: boolean;
}

export interface Route {
  courier_id: string;
  stops: Stop[];
  polyline?: LatLng[]; // decoded path for the map
  total_time_s?: number;
  total_distance_m?: number;
  feasible?: boolean;
}

export interface Objective {
  total_time_s?: number;
  windows_met?: number;
  windows_total?: number;
  solver?: string; // e.g. 'gpu-aco', 'cuopt', 'greedy-fallback'
  solve_ms?: number;
}

export interface Plan {
  routes: Route[];
  unassigned?: string[];
  objective?: Objective;
  generated_at: string;
}

export type DisruptionKind = "road_closure" | "traffic" | "courier_down";

export interface DisruptionEvent {
  id: string;
  kind: DisruptionKind;
  geometry?: LatLng[]; // closed segment / affected area
  courier_id?: string | null;
  source?: "tfl" | "manual";
  at?: string;
}

export type NotificationChannel = "voice_call" | "telegram" | "ui";

export interface Notification {
  id: string;
  channel: NotificationChannel;
  to?: string;
  job_id?: string | null;
  message: string;
}

// ---- Flywheel: crowdsourced drivers + congestion field (contracts/driver-api.md) ----
export type VehicleType = "bike" | "scooter" | "car" | "van";

export interface Driver {
  id: string;
  name?: string;
  vehicle_type: VehicleType;
  consent: boolean;
  joined_at?: string;
  points?: number;
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
  generated_at?: string | null;
}

// ---- Orchestrator state snapshot (GET /state and WS "state" payload) ----
export interface StateSnapshot {
  jobs: DeliveryJob[];
  couriers: Courier[];
  plan: Plan | null;
  disruptions: DisruptionEvent[];
  drivers?: Driver[];
  congestion?: CongestionField;
}

// ---- WebSocket event envelope: every server->client message is {type,payload,ts} ----
export interface AgentLog {
  level: "info" | "warn" | "error" | string;
  message: string;
}

export interface CourierMoved {
  courier_id: string;
  location: Location;
}

export type WsEvent =
  | { type: "state"; payload: StateSnapshot; ts: string }
  | { type: "job_created"; payload: DeliveryJob; ts: string }
  | { type: "plan_updated"; payload: Plan; ts: string }
  | { type: "courier_moved"; payload: CourierMoved; ts: string }
  | { type: "disruption"; payload: DisruptionEvent; ts: string }
  | { type: "agent_log"; payload: AgentLog; ts: string }
  | { type: "notification"; payload: Notification; ts: string }
  | { type: "congestion_updated"; payload: CongestionField; ts: string }
  | { type: "driver_joined"; payload: Driver; ts: string };

export type WsEventType = WsEvent["type"];

// ---- Verification status report (public/status.json, written by verification/run.py) ----
export type ClaimStatus = "verified" | "failing" | "unverified";

export interface VerificationClaim {
  id: string;
  statement: string;
  category: string;
  must_pass: boolean;
  test?: string;
  status: ClaimStatus;
  duration_s?: number | null;
}

export interface VerificationSummary {
  total: number;
  verified: number;
  failing: number;
  unverified: number;
  must_pass_total: number;
  must_pass_verified: number;
  must_pass_green: boolean;
}

export interface VerificationReport {
  generated_at: string;
  summary: VerificationSummary;
  claims: VerificationClaim[];
}

// ---- A single sampled point of operational metrics (for sparklines) ----
export interface MetricSample {
  ts: number;
  windowsMet: number;
  windowsTotal: number;
  windowPct: number;
  solveMs: number | null;
  totalTimeMin: number | null;
  activeCouriers: number;
  statInFlight: number;
  onTime: number;
}
