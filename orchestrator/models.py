"""Pydantic mirror of contracts/schemas.json. Keep the two in sync."""
from __future__ import annotations
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field

Priority = Literal["stat", "urgent", "routine"]


class Location(BaseModel):
    lat: float
    lng: float
    name: Optional[str] = None
    facility_id: Optional[str] = None


class TimeWindow(BaseModel):
    ready_at: Optional[datetime] = None
    due_by: Optional[datetime] = None


class DeliveryJob(BaseModel):
    id: Optional[str] = None
    type: Literal["sample_pickup", "med_delivery"]
    origin: Location
    destination: Location
    priority: Priority = "routine"
    time_window: TimeWindow = Field(default_factory=TimeWindow)
    cold_chain: bool = False
    capacity_units: float = 1
    status: Literal["new", "assigned", "in_transit", "delivered", "failed"] = "new"
    raw_text: Optional[str] = None
    created_at: Optional[datetime] = None


class Courier(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    location: Location
    capacity: float = 6
    cold_capable: bool = True
    vehicle_type: Literal["van", "scooter", "bike"] = "van"
    status: Literal["idle", "enroute", "offline"] = "idle"
    assigned_route_id: Optional[str] = None
    phone: Optional[str] = None


class Stop(BaseModel):
    job_id: str
    kind: Literal["pickup", "dropoff"]
    location: Location
    sequence: int
    eta: Optional[datetime] = None
    window_met: Optional[bool] = None


class LatLng(BaseModel):
    lat: float
    lng: float


class Route(BaseModel):
    courier_id: str
    stops: list[Stop] = []
    polyline: list[LatLng] = []
    total_time_s: float = 0
    total_distance_m: float = 0
    feasible: bool = True


class Objective(BaseModel):
    total_time_s: float = 0
    windows_met: int = 0
    windows_total: int = 0
    solver: str = "greedy-fallback"
    solve_ms: float = 0


class Plan(BaseModel):
    routes: list[Route] = []
    unassigned: list[str] = []
    objective: Objective = Field(default_factory=Objective)
    generated_at: Optional[datetime] = None


class DisruptionEvent(BaseModel):
    id: Optional[str] = None
    kind: Literal["road_closure", "traffic", "courier_down"]
    geometry: list[LatLng] = []
    courier_id: Optional[str] = None
    source: Literal["tfl", "manual"] = "manual"
    at: Optional[datetime] = None


class Notification(BaseModel):
    id: Optional[str] = None
    channel: Literal["voice_call", "telegram", "ui"]
    to: Optional[str] = None
    job_id: Optional[str] = None
    message: str


class OptimizeRequest(BaseModel):
    jobs: list[DeliveryJob]
    couriers: list[Courier]
    disruptions: list[DisruptionEvent] = []
    now: Optional[datetime] = None


class OptimizeResponse(BaseModel):
    plan: Plan


# ---- driver flywheel (contracts/driver-api.md) ------------------------------------
class Driver(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    vehicle_type: Literal["bike", "scooter", "car", "van"]
    consent: bool
    joined_at: Optional[datetime] = None
    points: int = 0


class DriverPing(BaseModel):
    driver_id: str
    lat: float
    lng: float
    speed_mps: float = 0.0
    heading_deg: Optional[float] = None
    ts: Optional[datetime] = None


class TelemetryBatch(BaseModel):
    pings: list[DriverPing]


# ---- traffic-signal recommendations (from the GB10 Nemotron NemoClaw agent) --------
class SignalRecommendation(BaseModel):
    junction_id: Optional[str] = None
    name: Optional[str] = None
    lat: float
    lng: float
    action: Literal["retime", "green_wave", "hold", "clear"] = "retime"
    detail: str
    confidence: float = 0.5
    source: str = "nemotron@scan-11"


class SignalRecommendations(BaseModel):
    recommendations: list[SignalRecommendation]
