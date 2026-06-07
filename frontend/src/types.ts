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

// ---- Traffic-signal recommendation from the GB10 Nemotron agent ----
// Surfaced via GET /state (signal_recs), GET /signals/recommendations, and the
// WS "signal_recs" event. Drives the toggleable Signals layer on the map.
export type SignalAction = "green_wave" | "retime" | "hold" | "clear";

export interface SignalRec {
  name: string;
  lat: number;
  lng: number;
  action: SignalAction;
  detail: string;
  confidence: number; // 0..1
  source: string; // e.g. "Nemotron@GB10"
}

// ---- Per-driver fleet assessment (GET /fleet/assessments + WS "fleet_assessments") ----
// One verdict per courier from the GB10 Nemotron agent; drives the status pill +
// Redirect affordance on each delivery card.
export type FleetAssessmentStatus = "on_time" | "reroute_suggested" | "at_risk";

export interface FleetAssessment {
  courier_id: string;
  status: FleetAssessmentStatus;
  note: string;
}

// ---- Live CCTV camera (GET /cctv/cameras) — curated TfL JamCams ----
export interface CctvCamera {
  id: string;
  name: string;
  lat: number;
  lng: number;
  image: string; // live still JPEG (cache-bust with a query param to refresh)
  video: string; // live video stream link
}

// ---- Answer from the GB10 Nemotron agent (WS "agent_answer") ----
// ---- A proposed operator action, rendered as a Yes/No decision card. Self-describing
// so the client executes it generically against the named orchestrator endpoint. ----
export interface AgentAction {
  type: string; // "redirect" | "optimize" | "notify"
  label: string; // the question shown on the card
  confirm?: string; // affirmative button text (e.g. "Reroute")
  endpoint: string; // e.g. "/couriers/crt-1/redirect"
  method?: string; // default POST
  body?: Record<string, unknown>;
  courier_id?: string | null;
}

export interface AgentAnswer {
  task_id: string;
  answer: string;
  // The model's chain-of-thought (shown dimmed above the answer); "" / absent when none.
  reasoning?: string;
  // An optional action the operator can approve from chat.
  action?: AgentAction | null;
}

// ---- Queued question returned by POST /agent/ask ----
export interface AgentTask {
  id: string;
  question: string;
  ts: string;
  status: "pending" | "answered";
  answer?: string;
  reasoning?: string;
  action?: AgentAction | null;
}

// ---- GET /healthz — service + active-LLM provider, so the UI can show the on-prem
// DGX Spark indicator only when the model runs locally. ----
export interface Health {
  status: string;
  routing_service: boolean;
  llm_provider: "local" | "cloud" | "none";
  llm_model: string | null;
  llm_label?: string;
  llm_enabled?: boolean;
  local_model: boolean;
  cloud_model: boolean;
}

// ---- Orchestrator state snapshot (GET /state and WS "state" payload) ----
export interface StateSnapshot {
  jobs: DeliveryJob[];
  couriers: Courier[];
  plan: Plan | null;
  disruptions: DisruptionEvent[];
  drivers?: Driver[];
  congestion?: CongestionField;
  signal_recs?: SignalRec[];
}

// ---- WebSocket event envelope: every server->client message is {type,payload,ts} ----
export interface AgentLog {
  level: "info" | "warn" | "error" | string;
  message: string;
  // Origin tag on the WS payload; "nemotron" lines are tinted in the feed.
  source?: string;
}

export type WsEvent =
  | { type: "state"; payload: StateSnapshot; ts: string }
  | { type: "job_created"; payload: DeliveryJob; ts: string }
  | { type: "plan_updated"; payload: Plan; ts: string }
  | { type: "disruption"; payload: DisruptionEvent; ts: string }
  | { type: "agent_log"; payload: AgentLog; ts: string }
  | { type: "notification"; payload: Notification; ts: string }
  | { type: "congestion_updated"; payload: CongestionField; ts: string }
  | { type: "driver_joined"; payload: Driver; ts: string }
  | { type: "signal_recs"; payload: SignalRec[]; ts: string }
  | { type: "fleet_assessments"; payload: FleetAssessment[]; ts: string }
  | { type: "agent_answer"; payload: AgentAnswer; ts: string };

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
