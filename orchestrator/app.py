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
import json
import pathlib
import asyncio
from datetime import datetime, timezone
from contextlib import suppress

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from models import (DeliveryJob, Location, Courier, DisruptionEvent, Notification,
                    Plan, OptimizeRequest, OptimizeResponse,
                    Driver, DriverPing, TelemetryBatch,
                    SignalRecommendation, SignalRecommendations,
                    AgentAsk, AgentAnswer, FleetAssessments)
from greedy import greedy_plan
import congestion as congestion_mod
import nemo_agent
import geocode
from intake import parse_delivery
import route_preview
import config
import llm
import db
import auth
from auth import require_user, current_user, CurrentUser

ROUTING_URL = os.getenv("ROUTING_URL", "http://localhost:8100")

app = FastAPI(title="RLJ orchestrator")
# CORS locked to an env allowlist (the PulseGo frontends). Dev default = local Vite ports.
# In prod set CORS_ORIGINS=https://app.pulsego.org,https://drive.pulsego.org,https://pulsego.org
_CORS_ORIGINS = [o.strip() for o in os.environ.get(
    "CORS_ORIGINS", "http://localhost:5173,http://localhost:5174").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_CORS_ORIGINS, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


class State:
    def __init__(self):
        self.jobs: dict[str, DeliveryJob] = {}
        self.couriers: dict[str, Courier] = {}
        self.disruptions: list[DisruptionEvent] = []
        self.plan: Plan | None = None
        self.drivers: dict[str, Driver] = {}
        self.pings: list[dict] = []
        self.congestion: dict = {"cells": [], "generated_at": None}
        self.signal_recs: list[dict] = []   # from the GB10 Nemotron agent
        self.agent_tasks: list[dict] = []   # questions queued for the GB10 agent
        self.fleet_assessments: dict[str, dict] = {}  # courier_id -> {status,note}
        self.couriers_helped: int = 0
        self._task_n = 0
        self._job_n = 0
        self._crt_n = 0
        self._dis_n = 0
        self._drv_n = 0

    def snapshot(self):
        return {
            "jobs": [j.model_dump(mode="json") for j in self.jobs.values()],
            "couriers": [c.model_dump(mode="json") for c in self.couriers.values()],
            "plan": self.plan.model_dump(mode="json") if self.plan else None,
            "disruptions": [d.model_dump(mode="json") for d in self.disruptions],
            "drivers": [d.model_dump(mode="json") for d in self.drivers.values()],
            "congestion": self.congestion,
            "signal_recs": self.signal_recs,
            "fleet_assessments": list(self.fleet_assessments.values()),
        }

    def all_disruptions(self) -> list[DisruptionEvent]:
        """Manual/scheduled disruptions plus those derived from the live congestion field."""
        derived = [DisruptionEvent(**d) for d in congestion_mod.field_to_disruptions(self.congestion)]
        return list(self.disruptions) + derived


S = State()


class Hub:
    """Tracks connected websockets and broadcasts events. Keeps a short replay buffer of
    narration/notification events so a client connecting AFTER they were emitted (e.g. the
    NemoClaw agent's startup lines, or any re-plan that happened before a reload) still sees
    recent history — otherwise the feed is blank until the next event."""
    HISTORY_TYPES = ("agent_log", "notification")
    HISTORY_CAP = 50

    def __init__(self):
        self.clients: set[WebSocket] = set()
        self.history: list[dict] = []

    async def join(self, ws: WebSocket):
        await ws.accept()
        self.clients.add(ws)
        await ws.send_json({"type": "state", "payload": S.snapshot(), "ts": _now_iso()})
        # replay recent narration so the feed is populated immediately on connect
        for m in self.history:
            try:
                await ws.send_json(m)
            except Exception:  # noqa: BLE001
                break

    def leave(self, ws: WebSocket):
        self.clients.discard(ws)

    async def emit(self, type_: str, payload):
        msg = {"type": type_, "payload": payload, "ts": _now_iso()}
        if type_ in self.HISTORY_TYPES:
            self.history.append(msg)
            if len(self.history) > self.HISTORY_CAP:
                self.history = self.history[-self.HISTORY_CAP:]
        dead = []
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
        disruptions=S.all_disruptions(),
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


# ----------------------------------------------------------------------------- auth
class RegisterBody(BaseModel):
    email: str
    password: str
    role: str = "dispatcher"


class LoginBody(BaseModel):
    email: str
    password: str


@app.post("/auth/register")
async def auth_register(body: RegisterBody, user: CurrentUser = Depends(require_user)):
    """Create a user. When AUTH_REQUIRED is on, only an admin may register others;
    when off, registration is open (bootstrap/dev)."""
    if auth.auth_required() and getattr(user, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="admin role required to register users")
    try:
        u = auth.create_user(body.email, body.password, role=body.role or "dispatcher")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"id": u.id, "email": u.email, "role": u.role}


@app.post("/auth/login")
async def auth_login(body: LoginBody):
    u = auth.authenticate(body.email, body.password)
    if u is None:
        raise HTTPException(status_code=401, detail="invalid email or password")
    token = auth.create_access_token(u)
    return {"access_token": token, "token_type": "bearer", "role": u.role}


@app.get("/auth/me")
async def auth_me(user: CurrentUser = Depends(current_user)):
    return {"id": user.uid, "email": user.email, "role": user.role}


@app.post("/auth/logout")
async def auth_logout():
    """Stateless JWT: the client simply drops the token. Endpoint exists for symmetry."""
    return {"ok": True}


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


async def _add_job(job: DeliveryJob) -> DeliveryJob:
    """Assign an id, store the job and emit job_created + agent_log — WITHOUT
    re-optimising. Shared by POST /jobs and the multi-drop /intake so the latter
    can add several jobs and re-optimise only ONCE."""
    if not job.id:
        S._job_n += 1
        job.id = f"job-{S._job_n}"
    job.created_at = job.created_at or datetime.now(timezone.utc)
    S.jobs[job.id] = job
    await HUB.emit("job_created", job.model_dump(mode="json"))
    await HUB.emit("agent_log", {"level": "info",
                                 "message": f"New {job.priority.upper()} job {job.id}: {job.origin.name or '?'} → {job.destination.name or '?'}."})
    return job


@app.post("/jobs")
async def create_job(job: DeliveryJob, _user: CurrentUser = Depends(require_user)):
    job = await _add_job(job)
    await run_optimize()
    await emit_dispatch_notification(job.id)
    return job.model_dump(mode="json")


class AgentIntake(BaseModel):
    text: str


@app.post("/intake")
async def intake(body: AgentIntake, _user: CurrentUser = Depends(require_user)):
    """Offline natural-language delivery intake — MULTI-DROP.

    Free text -> parse (local Nemotron, regex fallback) into one pickup + one or
    more drops -> resolve every place against the offline London gazetteer ->
    create ONE DeliveryJob per drop (origin -> drop), re-optimising ONCE -> draw
    the optimised pickup->drops road route (visiting order chosen via Valhalla).
    """
    text = (body.text or "").strip()
    if not text:
        return {"ok": False, "error": "empty request", "suggestions": []}

    parsed = parse_delivery(text, geocode.place_names())

    origin = geocode.resolve(parsed["origin"])
    if origin is None:
        return {"ok": False,
                "error": f"could not resolve '{parsed['origin']}'",
                "suggestions": geocode.suggest(parsed["origin"])}

    resolved_dests: list[dict] = []
    for name in parsed["destinations"]:
        d = geocode.resolve(name)
        if d is None:
            return {"ok": False,
                    "error": f"could not resolve '{name}'",
                    "suggestions": geocode.suggest(name)}
        resolved_dests.append(d)

    drop_names = ", ".join(d["name"] for d in resolved_dests)
    await HUB.emit("agent_log", {"level": "info", "source": "intake",
                                 "message": f"Intake: \"{text[:100]}\" -> "
                                            f"{parsed['priority'].upper()} {parsed['type']} "
                                            f"{origin['name']} -> {drop_names}."})

    # One job per drop (origin -> drop), all added first, then a single re-optimise.
    origin_loc = Location(lat=origin["lat"], lng=origin["lng"], name=origin["name"])
    created_jobs: list[dict] = []
    job_ids: list[str] = []
    for d in resolved_dests:
        job = await _add_job(DeliveryJob(
            type=parsed["type"],
            priority=parsed["priority"],
            cold_chain=parsed["cold_chain"],
            origin=origin_loc,
            destination=Location(lat=d["lat"], lng=d["lng"], name=d["name"]),
            raw_text=text,
        ))
        created_jobs.append(job.model_dump(mode="json"))
        job_ids.append(job.id)
    await run_optimize()
    for jid in job_ids:
        await emit_dispatch_notification(jid)

    # Optimised multi-hop route: [origin] + drops, visiting order chosen by Valhalla.
    pts = [origin] + resolved_dests
    opt = route_preview.optimized_route([p["lat"] for p in pts], [p["lng"] for p in pts])
    order_names = [pts[i]["name"] for i in opt["order"]]

    n = len(created_jobs)
    return {"ok": True, "jobs": created_jobs,
            "resolved": {"origin": origin, "destinations": resolved_dests},
            "order": order_names, "route": opt["polyline"],
            "message": f"Created {n} delivery(ies): {origin['name']} → {drop_names}"
                       "  · route optimized"}


@app.get("/couriers")
async def list_couriers():
    return [c.model_dump(mode="json") for c in S.couriers.values()]


@app.post("/couriers")
async def upsert_courier(courier: Courier, _user: CurrentUser = Depends(require_user)):
    if not courier.id:
        S._crt_n += 1
        courier.id = f"crt-{S._crt_n}"
    S.couriers[courier.id] = courier
    return courier.model_dump(mode="json")


@app.post("/disruptions")
async def add_disruption(d: DisruptionEvent, _user: CurrentUser = Depends(require_user)):
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
async def optimize(_user: CurrentUser = Depends(require_user)):
    plan = await run_optimize()
    return plan.model_dump(mode="json")


# Demo scenario (couriers + jobs) used by the "Demo mode" button so a fresh prod
# instance shows active routes + deliveries, identical to the local dev scenario.
# Bundled next to app.py so it ships inside the orchestrator container (whose build
# root is orchestrator/). Falls back to the repo sample for local dev.
_DEMO_SCENARIO = pathlib.Path(__file__).resolve().parent / "demo_scenario.json"
if not _DEMO_SCENARIO.exists():
    _DEMO_SCENARIO = pathlib.Path(__file__).resolve().parent.parent / "contracts/samples/demo_scenario.json"


@app.post("/demo/seed")
async def demo_seed(_user: CurrentUser = Depends(require_user)):
    """Populate the in-memory state with the bundled demo scenario and optimise.
    Idempotent (same ids overwrite). Broadcasts a fresh state so every client
    re-hydrates with couriers, jobs and the resulting plan."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    # Clinical due windows by priority — set relative to NOW so the demo fleet is
    # genuinely on-time (and the efficiency gauge reflects real window compliance).
    due_min = {"stat": 50, "urgent": 95, "routine": 180}
    data = json.loads(_DEMO_SCENARIO.read_text())
    for c in data.get("couriers", []):
        crt = Courier(**c)
        crt.status = "enroute"  # show an active fleet for the demo
        S.couriers[crt.id] = crt
    for j in data.get("jobs", []):
        job = DeliveryJob(**j)
        job.created_at = now
        mins = due_min.get(job.priority, 120)
        job.time_window.ready_at = now
        job.time_window.due_by = now + timedelta(minutes=mins)
        S.jobs[job.id] = job
    plan = await run_optimize()
    await HUB.emit("state", S.snapshot())
    await HUB.emit("agent_log", {"level": "info", "source": "system",
                                 "message": f"Demo mode on — {len(data.get('couriers', []))} couriers, {len(data.get('jobs', []))} jobs dispatched."})
    return {"couriers": len(S.couriers), "jobs": len(S.jobs),
            "routes": len(plan.routes) if plan else 0}


@app.post("/demo/clear")
async def demo_clear(_user: CurrentUser = Depends(require_user)):
    """Empty the demo scenario (couriers + jobs + plan) and broadcast — lets the
    Demo-mode toggle turn off."""
    S.couriers.clear()
    S.jobs.clear()
    S.plan = None
    await HUB.emit("state", S.snapshot())
    await HUB.emit("agent_log", {"level": "info", "source": "system",
                                 "message": "Demo mode off — scenario cleared."})
    return {"couriers": 0, "jobs": 0, "routes": 0}


@app.get("/plan")
async def get_plan():
    return S.plan.model_dump(mode="json") if S.plan else None


@app.post("/notifications")
async def notify(n: Notification):
    if not n.id:
        n.id = f"ntf-{datetime.now(timezone.utc).timestamp()}"
    await HUB.emit("notification", n.model_dump(mode="json"))
    return n.model_dump(mode="json")


# ----------------------------------------------------------------------------- flywheel
@app.get("/drivers")
async def list_drivers():
    return [d.model_dump(mode="json") for d in S.drivers.values()]


@app.post("/drivers")
async def create_driver(driver: Driver, _user: CurrentUser = Depends(require_user)):
    if not driver.consent:
        raise HTTPException(status_code=422, detail="consent required to join the flywheel")
    if not driver.id:
        S._drv_n += 1
        driver.id = f"drv-{S._drv_n}"
    driver.joined_at = driver.joined_at or datetime.now(timezone.utc)
    S.drivers[driver.id] = driver
    await HUB.emit("driver_joined", driver.model_dump(mode="json"))
    return driver.model_dump(mode="json")


@app.post("/telemetry")
async def telemetry(batch: TelemetryBatch, _user: CurrentUser = Depends(require_user)):
    raw = [p.model_dump(mode="json") for p in batch.pings]
    # only consenting, known drivers contribute
    consenting = {d.id for d in S.drivers.values() if d.consent}
    raw = [p for p in raw if not S.drivers or p["driver_id"] in consenting]
    accepted, rejected = congestion_mod.validate_pings(raw)
    S.pings.extend(accepted)
    S.pings = S.pings[-20000:]  # bound memory
    for p in accepted:
        d = S.drivers.get(p["driver_id"])
        if d:
            d.points += 1
    before = {d["cell"] for d in S.congestion.get("cells", [])}
    S.congestion = congestion_mod.estimate_field(S.pings, datetime.now(timezone.utc))
    after = {d["cell"] for d in S.congestion.get("cells", [])}
    await HUB.emit("congestion_updated", S.congestion)
    if S.jobs:  # re-plan medical couriers around newly-detected congestion
        await run_optimize()
        S.couriers_helped = len(S.plan.routes) if S.plan else 0
    return {"accepted": len(accepted), "rejected": len(rejected),
            "cells_updated": len(after - before) + len(after & before)}


@app.get("/congestion")
async def get_congestion():
    return S.congestion


# ----------------------------------------------------------------------------- CCTV (JamCams)
_CCTV_CACHE: dict = {"at": 0.0, "cams": []}
_CCTV_BBOX = (51.45, 51.56, -0.25, 0.05)  # central-ish London, curated


@app.get("/cctv/cameras")
async def cctv_cameras():
    """Curated live TfL JamCams (proxied + cached ~5 min, so the browser avoids CORS and
    we don't render 882 icons). Each: {id,name,lat,lng,image,video,available}."""
    import time as _t
    if _CCTV_CACHE["cams"] and (_t.time() - _CCTV_CACHE["at"] < 300):
        return _CCTV_CACHE["cams"]
    cams = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            data = (await client.get("https://api.tfl.gov.uk/Place/Type/JamCam")).json()
        a, b, c, d = _CCTV_BBOX
        for cam in data if isinstance(data, list) else []:
            lat, lng = cam.get("lat"), cam.get("lon")
            if lat is None or not (a <= lat <= b and c <= lng <= d):
                continue
            props = {p["key"]: p["value"] for p in cam.get("additionalProperties", [])}
            if str(props.get("available", "true")).lower() == "false":
                continue
            cams.append({"id": cam.get("id"), "name": cam.get("commonName"),
                         "lat": lat, "lng": lng, "image": props.get("imageUrl"),
                         "video": props.get("videoUrl")})
        cams = cams[:120]
    except Exception:  # noqa: BLE001 - offline: return whatever we had (possibly empty)
        return _CCTV_CACHE["cams"]
    _CCTV_CACHE["at"] = _t.time()
    _CCTV_CACHE["cams"] = cams
    return cams


@app.get("/signals/recommendations")
async def get_signal_recs():
    return S.signal_recs


@app.post("/signals/recommendations")
async def post_signal_recs(body: SignalRecommendations, _user: CurrentUser = Depends(require_user)):
    """The GB10 Nemotron NemoClaw agent posts traffic-signal recommendations here; they
    render on the map (junction markers) and narrate in the NemoClaw feed."""
    S.signal_recs = [r.model_dump(mode="json") for r in body.recommendations]
    await HUB.emit("signal_recs", S.signal_recs)
    if S.signal_recs:
        top = S.signal_recs[0]
        await HUB.emit("agent_log", {"level": "info", "source": "nemotron",
                                     "message": f"Nemotron@GB10: {len(S.signal_recs)} signal rec(s) — "
                                                f"{top['action']} at {top.get('name') or 'junction'}: {top['detail'][:80]}"})
    return {"accepted": len(S.signal_recs)}


# ----------------------------------------------------------------------------- agent channel
async def _record_agent_answer(task_id: str, answer: str):
    """Mark a queued task answered + emit the NemoClaw-feed events. Shared by the GB10
    worker path (POST /agent/answer) and the prod OpenAI auto-answer path below."""
    for t in S.agent_tasks:
        if t["id"] == task_id:
            t["status"] = "answered"
            t["answer"] = answer
            break
    await HUB.emit("agent_log", {"level": "info", "source": "nemotron",
                                 "message": f"Nemotron@GB10: {answer[:240]}"})
    await HUB.emit("agent_answer", {"task_id": task_id, "answer": answer})


def _fleet_context() -> str:
    """A light fleet-context system prompt for the LLM (no heavy state dumps)."""
    parts = [
        "You are PulseGo's dispatch assistant for a time-critical medical courier "
        "fleet in London. Answer the operator's question concisely.",
        f"Fleet now: {len(S.couriers)} courier(s), {len(S.jobs)} job(s), "
        f"{len(S.drivers)} signed-up driver(s).",
    ]
    if S.plan and S.plan.objective:
        obj = S.plan.objective
        parts.append(
            f"Current plan ({obj.solver}): {obj.windows_met}/{obj.windows_total} "
            f"time windows met across {len(S.plan.routes)} route(s).")
    return " ".join(parts)


async def _openai_auto_answer(task_id: str, question: str):
    """Prod path: with no on-box worker, the orchestrator answers via OpenAI."""
    try:
        answer = await asyncio.to_thread(llm.chat, question, system=_fleet_context())
    except Exception as e:  # noqa: BLE001 - llm.chat shouldn't raise, but be safe
        answer = None
        await HUB.emit("agent_log", {"level": "warn", "source": "nemotron",
                                     "message": f"Agent answer failed ({type(e).__name__})."})
        return
    if answer:
        await _record_agent_answer(task_id, answer)
    else:
        await HUB.emit("agent_log", {"level": "warn", "source": "nemotron",
                                     "message": "Agent could not produce an answer."})


@app.post("/agent/ask")
async def agent_ask(body: AgentAsk, _user: CurrentUser = Depends(require_user)):
    """Queue a question for the NemoClaw agent.

    LOCAL (GB10): the on-box worker polls /agent/tasks and posts to /agent/answer.
    PRODUCTION (no DGX): the orchestrator answers itself via OpenAI in the background.
    """
    S._task_n += 1
    task = {"id": f"task-{S._task_n}", "question": body.question,
            "ts": _now_iso(), "status": "pending"}
    S.agent_tasks.append(task)
    S.agent_tasks = S.agent_tasks[-50:]
    await HUB.emit("agent_log", {"level": "info", "source": "operator",
                                 "message": f"Asked NemoClaw: {body.question[:120]}"})
    # In prod (no on-box worker) answer ourselves via OpenAI; locally the DGX worker
    # handles it, so we must NOT auto-answer or the feed gets double answers.
    if not config.is_local() and config.openai_key():
        asyncio.create_task(_openai_auto_answer(task["id"], body.question))
    return task


@app.get("/agent/tasks")
async def agent_tasks():
    return [t for t in S.agent_tasks if t["status"] == "pending"]


@app.post("/agent/answer")
async def agent_answer(body: AgentAnswer, _user: CurrentUser = Depends(require_user)):
    """The GB10 agent posts its Nemotron answer here; it lands in the NemoClaw feed."""
    await _record_agent_answer(body.task_id, body.answer)
    return {"ok": True}


# ----------------------------------------------------------------------------- per-driver
@app.get("/fleet/assessments")
async def get_fleet_assessments():
    return list(S.fleet_assessments.values())


@app.post("/fleet/assessments")
async def post_fleet_assessments(body: FleetAssessments, _user: CurrentUser = Depends(require_user)):
    """The agent's per-driver assessment (on_time / reroute_suggested / at_risk) shown on cards."""
    for a in body.assessments:
        S.fleet_assessments[a.courier_id] = a.model_dump(mode="json")
    await HUB.emit("fleet_assessments", list(S.fleet_assessments.values()))
    flagged = [a for a in body.assessments if a.status != "on_time"]
    if flagged:
        await HUB.emit("agent_log", {"level": "warn", "source": "nemotron",
                                     "message": f"Nemotron@GB10 flagged {len(flagged)} driver(s) for reroute."})
    return {"accepted": len(body.assessments)}


@app.post("/couriers/{courier_id}/redirect")
async def redirect_courier(courier_id: str, _user: CurrentUser = Depends(require_user)):
    """Operator-triggered redirect: re-optimise (routes avoid live congestion) and narrate."""
    courier = S.couriers.get(courier_id)
    if courier is None:
        raise HTTPException(status_code=404, detail="unknown courier")
    await HUB.emit("agent_log", {"level": "info", "source": "operator",
                                 "message": f"Redirecting {courier.name or courier_id} around current congestion."})
    plan = await run_optimize()
    return {"ok": True, "courier_id": courier_id,
            "windows_met": plan.objective.windows_met, "solver": plan.objective.solver}


@app.get("/driver/{driver_id}/guidance")
async def driver_guidance(driver_id: str):
    driver = S.drivers.get(driver_id)
    pings = sum(1 for p in S.pings if p["driver_id"] == driver_id)
    advice = None
    # naive green-wave placeholder; the data stream's junctions service refines this
    if S.congestion.get("cells"):
        worst = max(S.congestion["cells"], key=lambda c: c["congestion"], default=None)
        if worst and worst["congestion"] >= congestion_mod.BUSY:
            advice = {"driver_id": driver_id,
                      "message": f"Heavy traffic near ({worst['lat']:.3f},{worst['lng']:.3f}); easing to 25 km/h smooths your run.",
                      "target_speed_mps": 7.0, "junction": {"lat": worst["lat"], "lng": worst["lng"]},
                      "seconds_to_green": 20.0, "confidence": 0.5}
    return {"driver_id": driver_id, "status": "active" if driver else "unknown",
            "eta": None, "route_polyline": [], "signal_advice": advice,
            "contribution": {"pings": pings, "couriers_helped": S.couriers_helped}}


@app.get("/signals/advice")
async def signals_advice(driver_id: str = "", lat: float = 0.0, lng: float = 0.0, heading: float = 0.0):
    # lightweight green-wave hint; the junctions dataset provides the precise cycle model
    return {"driver_id": driver_id,
            "message": "Maintain ~28 km/h to catch the next green.",
            "target_speed_mps": 7.8, "junction": {"lat": lat, "lng": lng},
            "seconds_to_green": 18.0, "confidence": 0.4}



async def _nemo_inject(d: dict):
    """Adapter so the NemoClaw agent can post a disruption (and trigger a re-plan)."""
    await add_disruption(DisruptionEvent(**d))


@app.on_event("startup")
async def _start_background():
    # Auth/DB: create tables and (optionally) seed the admin from env. Best-effort so a
    # transient DB hiccup never stops the demo stack from booting.
    try:
        db.init_db()
        auth.seed_admin()
    except Exception as e:  # noqa: BLE001
        await HUB.emit("agent_log", {"level": "warn",
                                     "message": f"Auth DB init skipped: {type(e).__name__}: {e}"})
    asyncio.create_task(nemo_agent.run(HUB.emit, _nemo_inject, interval_s=14))


# ----------------------------------------------------------------------------- WS
@app.websocket("/ws")
async def ws(ws: WebSocket):
    await HUB.join(ws)
    try:
        while True:
            await ws.receive_text()  # we don't expect client messages; keepalive only
    except WebSocketDisconnect:
        HUB.leave(ws)
