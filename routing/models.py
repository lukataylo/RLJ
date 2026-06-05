"""Pydantic mirror of contracts/schemas.json, scoped to the routing service.

This is a deliberate *re-implementation* (not a cross-folder import of
``orchestrator/models.py``) so the routing stream stays self-contained and can be
developed / deployed on its own. Keep field names byte-for-byte identical to
``contracts/schemas.json`` — the orchestrator deserialises whatever we emit.
"""
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


class LatLng(BaseModel):
    lat: float
    lng: float


class TimeWindow(BaseModel):
    ready_at: Optional[datetime] = None  # earliest pickup
    due_by: Optional[datetime] = None    # clinical deadline at destination


class DeliveryJob(BaseModel):
    id: str
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
    id: str
    name: Optional[str] = None
    location: Location
    capacity: float = 6
    status: Literal["idle", "enroute", "offline"] = "idle"
    assigned_route_id: Optional[str] = None
    phone: Optional[str] = None
    # Not in the shared schema: lets a deployment flag vans without a cold box.
    # Defaults to True so every courier is cold-capable unless told otherwise.
    cold_capable: bool = True


class Stop(BaseModel):
    job_id: str
    kind: Literal["pickup", "dropoff"]
    location: Location
    sequence: int  # order within the route, 0-based
    eta: Optional[datetime] = None
    window_met: Optional[bool] = None


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
    solver: str = "aco-numpy"
    solve_ms: float = 0


class Plan(BaseModel):
    routes: list[Route] = []
    unassigned: list[str] = []
    objective: Objective = Field(default_factory=Objective)
    generated_at: Optional[datetime] = None


class DisruptionEvent(BaseModel):
    id: str
    kind: Literal["road_closure", "traffic", "courier_down"]
    geometry: list[LatLng] = []
    courier_id: Optional[str] = None
    source: Literal["tfl", "manual"] = "manual"
    at: Optional[datetime] = None


class OptimizeRequest(BaseModel):
    jobs: list[DeliveryJob]
    couriers: list[Courier]
    disruptions: list[DisruptionEvent] = []
    now: Optional[datetime] = None


class OptimizeResponse(BaseModel):
    plan: Plan
