"""RLJ orchestrator — the hub all three streams integrate through.

- In-memory state (jobs, couriers, plan, disruptions).
- WebSocket /ws broadcasts live events to the frontend (and anyone else).
- POST /optimize prefers the real routing service at ROUTING_URL; falls back to the
  built-in greedy router so the system is always demoable.

Run:  uvicorn app:app --reload --port 8000
Env:  ROUTING_URL=http://localhost:8100   (optional; greedy fallback if unreachable)
"""
from __future__ import annotations
import os
from datetime import datetime, timezone
from contextlib import suppress

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from models import (DeliveryJob, Courier, DisruptionEvent, Notification,
                    Plan, OptimizeRequest, OptimizeResponse)
from greedy import greedy_plan

ROUTING_URL = os.getenv("ROUTING_URL", "http://localhost:8100")

app = FastAPI(title="RLJ orchestrator")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class State:
    def __init__(self):
        self.jobs: dict[str, DeliveryJob] = {}
        self.couriers: dict[str, Courier] = {}
        self.disruptions: list[DisruptionEvent] = []
        self.plan: Plan | None = None
        self._job_n = 0
        self._crt_n = 0
        self._dis_n = 0

    def snapshot(self):
        return {
            "jobs": [j.model_dump(mode="json") for j in self.jobs.values()],
            "couriers": [c.model_dump(mode="json") for c in self.couriers.values()],
            "plan": self.plan.model_dump(mode="json") if self.plan else None,
            "disruptions": [d.model_dump(mode="json") for d in self.disruptions],
        }


S = State()


class Hub:
    """Tracks connected websockets and broadcasts events."""
    def __init__(self):
        self.clients: set[WebSocket] = set()

    async def join(self, ws: WebSocket):
        await ws.accept()
        self.clients.add(ws)
        await ws.send_json({"type": "state", "payload": S.snapshot(), "ts": _now_iso()})

    def leave(self, ws: WebSocket):
        self.clients.discard(ws)

    async def emit(self, type_: str, payload):
        dead = []
        msg = {"type": type_, "payload": payload, "ts": _now_iso()}
        for ws in self.clients:
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.leave(ws)


HUB = Hub()


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# ----------------------------------------------------------------------------- routing
async def run_optimize() -> Plan:
    req = OptimizeRequest(
        jobs=list(S.jobs.values()),
        couriers=list(S.couriers.values()),
        disruptions=S.disruptions,
        now=datetime.now(timezone.utc),
    )
    # Prefer the real routing service; fall back to greedy on any failure.
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(f"{ROUTING_URL}/optimize", json=req.model_dump(mode="json"))
            r.raise_for_status()
            plan = OptimizeResponse(**r.json()).plan
    except Exception as e:  # noqa: BLE001 - fallback is intentional
        plan = greedy_plan(req)
        await HUB.emit("agent_log", {"level": "warn",
                                     "message": f"Routing service unavailable ({type(e).__name__}); used greedy fallback."})
    S.plan = plan
    obj = plan.objective
    await HUB.emit("plan_updated", plan.model_dump(mode="json"))
    await HUB.emit("agent_log", {"level": "info",
                                 "message": f"Re-planned with {obj.solver}: {obj.windows_met}/{obj.windows_total} windows met across {len(plan.routes)} routes."})
    return plan


async def emit_dispatch_notification(job_id: str):
    """After a (re)plan, tell the voice stream to call the assigned courier with the ETA.
    This is the producer of channel=='voice_call' events the voice agent listens for."""
    if not S.plan:
        return
    for route in S.plan.routes:
        for stop in route.stops:
            if stop.job_id == job_id and stop.kind == "dropoff":
                courier = S.couriers.get(route.courier_id)
                job = S.jobs.get(job_id)
                eta = stop.eta.strftime("%H:%M") if stop.eta else "soon"
                msg = (f"{job.priority.upper()} job {job_id}: collect from "
                       f"{job.origin.name or 'origin'}, deliver to {job.destination.name or 'destination'}. "
                       f"ETA {eta}." if job else f"New job {job_id}, ETA {eta}.")
                n = Notification(channel="voice_call",
                                 to=(courier.phone if courier else None),
                                 job_id=job_id, message=msg)
                await HUB.emit("notification", n.model_dump(mode="json"))
                return


# ----------------------------------------------------------------------------- REST
@app.get("/healthz")
async def healthz():
    routing_ok = False
    with suppress(Exception):
        async with httpx.AsyncClient(timeout=2.0) as c:
            routing_ok = (await c.get(f"{ROUTING_URL}/healthz")).status_code == 200
    return {"status": "ok", "routing_service": routing_ok}


@app.get("/state")
async def get_state():
    return S.snapshot()


@app.get("/jobs")
async def list_jobs():
    return [j.model_dump(mode="json") for j in S.jobs.values()]


@app.post("/jobs")
async def create_job(job: DeliveryJob):
    if not job.id:
        S._job_n += 1
        job.id = f"job-{S._job_n}"
    job.created_at = job.created_at or datetime.now(timezone.utc)
    S.jobs[job.id] = job
    await HUB.emit("job_created", job.model_dump(mode="json"))
    await HUB.emit("agent_log", {"level": "info",
                                 "message": f"New {job.priority.upper()} job {job.id}: {job.origin.name or '?'} → {job.destination.name or '?'}."})
    await run_optimize()
    await emit_dispatch_notification(job.id)
    return job.model_dump(mode="json")


@app.get("/couriers")
async def list_couriers():
    return [c.model_dump(mode="json") for c in S.couriers.values()]


@app.post("/couriers")
async def upsert_courier(courier: Courier):
    if not courier.id:
        S._crt_n += 1
        courier.id = f"crt-{S._crt_n}"
    S.couriers[courier.id] = courier
    return courier.model_dump(mode="json")


@app.post("/disruptions")
async def add_disruption(d: DisruptionEvent):
    if not d.id:
        S._dis_n += 1
        d.id = f"dis-{S._dis_n}"
    d.at = d.at or datetime.now(timezone.utc)
    S.disruptions.append(d)
    if d.kind == "courier_down" and d.courier_id in S.couriers:
        S.couriers[d.courier_id].status = "offline"
    await HUB.emit("disruption", d.model_dump(mode="json"))
    await HUB.emit("agent_log", {"level": "warn", "message": f"Disruption: {d.kind}. Re-planning to protect at-risk windows."})
    await run_optimize()
    return d.model_dump(mode="json")


@app.post("/optimize")
async def optimize():
    plan = await run_optimize()
    return plan.model_dump(mode="json")


@app.get("/plan")
async def get_plan():
    return S.plan.model_dump(mode="json") if S.plan else None


@app.post("/notifications")
async def notify(n: Notification):
    if not n.id:
        n.id = f"ntf-{datetime.now(timezone.utc).timestamp()}"
    await HUB.emit("notification", n.model_dump(mode="json"))
    return n.model_dump(mode="json")


# ----------------------------------------------------------------------------- WS
@app.websocket("/ws")
async def ws(ws: WebSocket):
    await HUB.join(ws)
    try:
        while True:
            await ws.receive_text()  # we don't expect client messages; keepalive only
    except WebSocketDisconnect:
        HUB.leave(ws)
