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
import sys
import math
from datetime import datetime, timezone, timedelta
from contextlib import suppress
from typing import Optional

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response as HTTPResponse
from pydantic import BaseModel, Field

# Load ElevenLabs key (and other voice config) from voice/.env when not already set in
# the shell environment. override=False means a real env var always wins.
try:
    from dotenv import load_dotenv as _load_dotenv
    _voice_env = pathlib.Path(__file__).parent.parent / "voice" / ".env"
    if _voice_env.exists():
        _load_dotenv(_voice_env, override=False)
except ImportError:
    pass

from models import (DeliveryJob, Location, Courier, DisruptionEvent, Notification,
                    Plan, OptimizeRequest, OptimizeResponse, LatLng,
                    Driver, DriverPing, TelemetryBatch,
                    SignalRecommendation, SignalRecommendations,
                    AgentAsk, AgentAnswer, FleetAssessments)
from greedy import greedy_plan
import congestion as congestion_mod
import nemo_agent
import geocode
from nl_intake import parse_delivery
import route_preview
import config
import llm
import agent_actions
import db
import auth
from auth import require_user, current_user, CurrentUser

ROUTING_URL = os.getenv("ROUTING_URL", "http://localhost:8100")
# NemoClaw operator Q&A uses the shared llm.chat seam (config.py / llm.py).

app = FastAPI(title="RLJ orchestrator")
# CORS locked to an env allowlist (the PulseGo frontends). Dev default = local Vite ports.
# In prod set CORS_ORIGINS=https://app.pulsego.org,https://drive.pulsego.org,https://pulsego.org
_CORS_ORIGINS = [o.strip() for o in os.environ.get(
    "CORS_ORIGINS",
    "http://localhost:5173,http://localhost:5174,"
    "http://127.0.0.1:5173,http://127.0.0.1:5174").split(",") if o.strip()]
# Also allow any localhost / private-LAN origin on any port, so the console + driver PWA
# work when opened from a phone/another machine on the same network during the demo
# (e.g. http://10.x.x.x:5173). Prod still uses the explicit CORS_ORIGINS allowlist.
_CORS_ORIGIN_REGEX = os.environ.get(
    "CORS_ORIGIN_REGEX",
    r"https?://(localhost|127\.0\.0\.1|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(:\d+)?")
app.add_middleware(CORSMiddleware, allow_origins=_CORS_ORIGINS,
                   allow_origin_regex=_CORS_ORIGIN_REGEX, allow_credentials=True,
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
    # Which LLM is in play, so the UI can show the on-prem DGX Spark indicator only when
    # the model truly runs locally and hide it when a cloud model is active.
    local = config.is_local()
    has_cloud_key = bool(config.openai_key())
    provider = "local" if local else ("cloud" if has_cloud_key else "none")
    return {
        "status": "ok",
        "routing_service": routing_ok,
        "llm_provider": provider,           # "local" | "cloud" | "none"
        "llm_model": (config.model() if local else (config.openai_model() if has_cloud_key else None)),
        "local_model": local,               # local Ollama/Nemotron on the DGX Spark
        "cloud_model": (not local) and has_cloud_key,  # OpenAI-compatible cloud provider
    }


@app.get("/state")
async def get_state():
    return S.snapshot()


@app.get("/jobs")
async def list_jobs():
    return [j.model_dump(mode="json") for j in S.jobs.values()]


@app.post("/jobs")
async def create_job(job: DeliveryJob, _user: CurrentUser = Depends(require_user)):
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


class AgentIntake(BaseModel):
    text: str


@app.post("/intake")
async def intake(body: AgentIntake, _user: CurrentUser = Depends(require_user)):
    """Offline natural-language delivery intake.

    Free text -> parse (local Nemotron, regex fallback) -> resolve both places
    against the offline London gazetteer -> create a job through the SAME path as
    POST /jobs (so it re-optimizes and the route renders live).
    """
    text = (body.text or "").strip()
    if not text:
        return {"ok": False, "error": "empty request", "suggestions": []}

    parsed = parse_delivery(text, geocode.place_names())
    origin = geocode.resolve(parsed["origin"])
    destination = geocode.resolve(parsed["destination"])

    if origin is None or destination is None:
        unresolved = parsed["origin"] if origin is None else parsed["destination"]
        return {"ok": False,
                "error": f"could not resolve {'origin' if origin is None else 'destination'}: "
                         f"'{unresolved}'",
                "suggestions": geocode.suggest(unresolved)}

    job = DeliveryJob(
        type=parsed["type"],
        priority=parsed["priority"],
        cold_chain=parsed["cold_chain"],
        origin=Location(lat=origin["lat"], lng=origin["lng"], name=origin["name"]),
        destination=Location(lat=destination["lat"], lng=destination["lng"],
                             name=destination["name"]),
        raw_text=text,
    )
    await HUB.emit("agent_log", {"level": "info", "source": "intake",
                                 "message": f"Intake: \"{text[:100]}\" -> "
                                            f"{job.priority.upper()} {job.type} "
                                            f"{origin['name']} -> {destination['name']}."})
    # Same path as POST /jobs: assigns id, emits job_created + agent_log, re-optimizes,
    # then dispatch notification.
    created = await create_job(job, _user)
    job_id = created.get("id")
    # This delivery's own clean pickup->dropoff road route (for the UI to draw/highlight
    # in blue), instead of the courier's full multi-stop tour. [] if Valhalla is down.
    route = route_preview.valhalla_route_shape(
        [origin["lat"], destination["lat"]], [origin["lng"], destination["lng"]])
    return {"ok": True, "job": created,
            "resolved": {"origin": origin, "destination": destination},
            "route": route,
            "message": f"Created {job_id}: {origin['name']} → {destination['name']}"}


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
def _fleet_for_actions() -> list[dict]:
    """Light courier view (id/name/phone) for grounding proposed decision-card actions."""
    return [{"id": c.id, "name": c.name, "phone": c.phone} for c in S.couriers.values()]


async def _record_agent_answer(task_id: str, answer: str, reasoning: str = "",
                               action: Optional[dict] = None):
    """Mark a queued task answered + emit the NemoClaw-feed events. Shared by the GB10
    worker path (POST /agent/answer) and the direct answer path below. ``reasoning`` is
    the model's chain-of-thought (shown dimmed in chat); ``action`` is an optional
    operator action rendered as a Yes/No decision card."""
    for t in S.agent_tasks:
        if t["id"] == task_id:
            t["status"] = "answered"
            t["answer"] = answer
            t["reasoning"] = reasoning
            t["action"] = action
            break
    await HUB.emit("agent_log", {"level": "info", "source": "nemotron",
                                 "message": f"NemoClaw: {answer[:280]}"})
    payload = {"task_id": task_id, "answer": answer}
    if reasoning:
        payload["reasoning"] = reasoning
    if action:
        payload["action"] = action
    await HUB.emit("agent_answer", payload)


def _fleet_context() -> str:
    """A light fleet-context system prompt for the LLM (no heavy state dumps)."""
    parts = [
        "You are PulseGo's on-prem dispatch assistant for a time-critical medical "
        "courier fleet in London, running locally on an NVIDIA DGX Spark (zero cloud "
        "egress). Answer the operator's question concisely in 1-3 sentences.",
        f"Fleet now: {len(S.couriers)} courier(s), {len(S.jobs)} job(s), "
        f"{len(S.drivers)} signed-up driver(s).",
    ]
    if S.plan and S.plan.objective:
        obj = S.plan.objective
        parts.append(
            f"Current plan ({obj.solver}): {obj.windows_met}/{obj.windows_total} "
            f"time windows met across {len(S.plan.routes)} route(s).")
    return " ".join(parts)


def _fallback_agent_answer(question: str) -> str:
    """Deterministic answer when the configured LLM/worker is unavailable."""
    low = question.lower()
    courier_count = len(S.couriers)
    job_count = len(S.jobs)
    route_count = len(S.plan.routes) if S.plan else 0
    if any(word in low for word in ("route", "window", "plan", "on time")):
        if S.plan:
            obj = S.plan.objective
            return (
                f"{route_count} routes are active. "
                f"{obj.windows_met} of {obj.windows_total} delivery windows are currently met."
            )
        return "No route plan is active yet. Seed or create deliveries to start planning."
    if any(word in low for word in ("courier", "driver", "job", "delivery", "fleet")):
        return (
            f"The fleet currently has {courier_count} couriers and {job_count} active jobs "
            f"across {route_count} planned routes."
        )
    if any(word in low for word in ("traffic", "congestion", "disruption", "road")):
        return (
            f"There are {len(S.disruptions)} recorded disruptions and "
            f"{len(S.congestion.get('cells', []))} live congestion cells."
        )
    return (
        f"NemoClaw is online. I am monitoring {courier_count} couriers, "
        f"{job_count} jobs and {route_count} routes."
    )


async def _answer_question(question: str) -> tuple[str, str]:
    """Answer via the LLM seam (OpenAI/Ollama per config), returning ``(answer, reasoning)``.

    Reasoning models (local Nemotron) wrap their chain-of-thought in ``<think>…</think>``;
    we lift that out so the spoken/markdown answer stays clean while the UI can still show
    it. Falls back to a deterministic keyword-aware summary (no reasoning) so Ask NemoClaw
    always responds, even with no model and no on-box worker."""
    raw = None
    try:
        raw = await asyncio.to_thread(llm.chat, question, system=_fleet_context())
    except Exception:  # noqa: BLE001 - never let the chat hang the request
        raw = None
    if raw:
        reasoning, answer = agent_actions.split_reasoning(raw)
        if answer:
            return answer, reasoning
    return _fallback_agent_answer(question), ""


@app.post("/agent/ask")
async def agent_ask(body: AgentAsk, _user: CurrentUser = Depends(require_user)):
    """Answer an operator question directly (LLM seam → deterministic fallback) so the
    chat always responds. The answer is also recorded for the optional GB10 worker."""
    S._task_n += 1
    task = {"id": f"task-{S._task_n}", "question": body.question,
            "ts": _now_iso(), "status": "pending"}
    S.agent_tasks.append(task)
    S.agent_tasks = S.agent_tasks[-50:]
    await HUB.emit("agent_log", {"level": "info", "source": "operator",
                                 "message": f"Asked NemoClaw: {body.question[:120]}"})
    answer, reasoning = await _answer_question(body.question)
    action = agent_actions.propose_action(body.question, answer, _fleet_for_actions())
    await _record_agent_answer(task["id"], answer, reasoning, action)
    return task


@app.get("/agent/tasks")
async def agent_tasks():
    return [t for t in S.agent_tasks if t["status"] == "pending"]


@app.post("/agent/answer")
async def agent_answer(body: AgentAnswer, _user: CurrentUser = Depends(require_user)):
    """The GB10 agent posts its Nemotron answer here; it lands in the NemoClaw feed.

    The worker may post a plain answer (older clients) or include ``reasoning``/``action``.
    Either way we strip any ``<think>`` chain-of-thought and, if no action was supplied,
    derive one from the original question + answer so the chat still offers a decision card."""
    reasoning, answer = agent_actions.split_reasoning(body.answer)
    answer = answer or body.answer
    reasoning = body.reasoning or reasoning
    question = next((t.get("question", "") for t in S.agent_tasks if t["id"] == body.task_id), "")
    action = body.action or agent_actions.propose_action(question, answer, _fleet_for_actions())
    await _record_agent_answer(body.task_id, answer, reasoning, action)
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


# ----------------------------------------------------------------- upcoming conditions
_CONDITIONS_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "conditions.json"


def _parse_iso(ts: str) -> datetime:
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _haversine_km(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = math.radians(b_lat - a_lat)
    dl = math.radians(b_lng - a_lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


@app.get("/conditions/upcoming")
async def conditions_upcoming(
    within_hours: float = 6.0,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    radius_km: float = 3.0,
    now: Optional[str] = None,
):
    """Forward-looking conditions on a courier's horizon: planned works, bridge lifts,
    events, floods (time-windowed) plus standing major developments. Reads the merged
    data/conditions.json pipeline; optionally filters to those near a point. Public (the
    driver app calls it). Never 5xx — returns an empty feed if the artifact is missing."""
    try:
        payload = json.loads(_CONDITIONS_PATH.read_text())
    except Exception:  # noqa: BLE001 - artifact missing/unreadable → empty, never crash
        return {"now": now, "within_hours": within_hours, "count": 0, "conditions": []}

    base_now = now or payload.get("scenario_now") or _now_iso()
    now_dt = _parse_iso(base_now)
    until = now_dt + timedelta(hours=within_hours)

    out: list[dict] = []
    for c in payload.get("conditions", []):
        starts = c.get("starts")
        ends = c.get("ends")
        if starts:  # time-windowed: keep only those overlapping [now, now+within]
            s = _parse_iso(starts)
            e = _parse_iso(ends) if ends else until
            if not (s < until and e > now_dt):
                continue
        # developments (no start) are standing context — always included
        if lat is not None and lng is not None:
            if _haversine_km(lat, lng, c["lat"], c["lng"]) > radius_km:
                continue
        item = dict(c)
        item["starts_in_min"] = (
            int((_parse_iso(starts) - now_dt).total_seconds() // 60) if starts else None
        )
        out.append(item)

    # Soonest first; standing developments (no start) last.
    out.sort(key=lambda x: (x["starts_in_min"] is None, x["starts_in_min"] or 0))
    return {"now": now_dt.isoformat(), "within_hours": within_hours, "count": len(out), "conditions": out}


# Tower Bridge bascule-lift closure across the A100 river crossing (north→south span).
_TOWER_BRIDGE_GEOM = [
    {"lat": 51.5072, "lng": -0.0757},
    {"lat": 51.5055, "lng": -0.0754},
    {"lat": 51.5039, "lng": -0.0750},
]
_TOWER_BRIDGE_CENTRE = (51.5055, -0.0754)


def _courier_nearest_bridge() -> Optional[Courier]:
    """The courier currently closest to Tower Bridge — the one a closure most affects."""
    best, best_d = None, float("inf")
    for c in S.couriers.values():
        loc = getattr(c, "location", None)
        if not loc:
            continue
        d = _haversine_km(_TOWER_BRIDGE_CENTRE[0], _TOWER_BRIDGE_CENTRE[1], loc.lat, loc.lng)
        if d < best_d:
            best, best_d = c, d
    return best


@app.post("/scenario/bridge-closure")
async def scenario_bridge_closure(_user: CurrentUser = Depends(require_user)):
    """Demo scenario: Tower Bridge lifts and closes the A100 crossing.

    Injects the closure into live state (so the planner will avoid it), then narrates it
    through NemoClaw's reasoning chain and offers a *reroute decision card*. The plan is
    deliberately NOT re-optimised here — confirming the card calls the redirect endpoint,
    which re-plans via the routing service (now avoiding the bridge) so the fleet visibly
    updates in real time."""
    S._dis_n += 1
    disr = DisruptionEvent(
        id=f"bridge-closure-{S._dis_n}",
        kind="road_closure",
        geometry=[LatLng(**p) for p in _TOWER_BRIDGE_GEOM],
        source="manual",
        at=datetime.now(timezone.utc),
    )
    S.disruptions.append(disr)
    await HUB.emit("disruption", disr.model_dump(mode="json"))

    courier = _courier_nearest_bridge()
    S._task_n += 1
    task = {"id": f"task-{S._task_n}", "question": "Tower Bridge closure",
            "ts": _now_iso(), "status": "pending"}
    S.agent_tasks.append(task)
    S.agent_tasks = S.agent_tasks[-50:]

    if courier is not None:
        who = courier.name or courier.id
        reasoning = (
            "Tower Bridge has just lifted and closed the A100 river crossing. "
            f"{who} is the courier nearest the bridge and their route relies on it; "
            "waiting for the bascules to lower could add 12–18 minutes. Rerouting now via "
            "the next downstream crossing protects the STAT delivery window."
        )
        answer = f"**Tower Bridge has closed.** I recommend rerouting **{who}** around it now."
        action = {
            "type": "redirect",
            "courier_id": courier.id,
            "label": f"Reroute {who} around the Tower Bridge closure?",
            "confirm": "Reroute",
            "endpoint": f"/couriers/{courier.id}/redirect",
            "method": "POST",
        }
    else:
        reasoning = (
            "Tower Bridge has just lifted and closed the A100 river crossing. "
            "Re-optimising the fleet now routes every courier around it."
        )
        answer = "**Tower Bridge has closed.** I recommend re-optimising the fleet to route around it."
        action = {
            "type": "optimize",
            "label": "Re-optimise the fleet around the Tower Bridge closure?",
            "confirm": "Re-plan",
            "endpoint": "/optimize",
            "method": "POST",
        }

    await _record_agent_answer(task["id"], answer, reasoning, action)
    return {"ok": True, "disruption_id": disr.id,
            "courier_id": (courier.id if courier else None), "task_id": task["id"]}


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


# ----------------------------------------------------------------------------- in-cab Q&A
def _driver_route(courier_id: str):
    """The route a driver is on: their courier's route, else the first active route."""
    if not S.plan or not S.plan.routes:
        return None
    if courier_id:
        return next((r for r in S.plan.routes if r.courier_id == courier_id), None)
    return S.plan.routes[0]


def _driver_next_stops(courier_id: str, n: int = 4) -> list[str]:
    route = _driver_route(courier_id)
    if not route:
        return []
    out = []
    for s in sorted(route.stops, key=lambda s: s.sequence)[:n]:
        where = s.location.name or f"({s.location.lat:.3f},{s.location.lng:.3f})"
        eta = f" by {s.eta.strftime('%H:%M')}" if s.eta else ""
        out.append(f"{s.kind} at {where}{eta}")
    return out


def _driver_context(courier_id: str, lat: float, lng: float) -> str:
    """System prompt grounding the in-cab assistant in this driver's live run."""
    parts = [
        "You are NemoClaw, the in-cab navigation assistant for a London medical courier.",
        "Answer the driver's question in 1-2 short, practical sentences, like a co-pilot.",
        "Use ONLY the live facts below; if something isn't given, say you don't have it yet.",
    ]
    stops = _driver_next_stops(courier_id)
    if stops:
        parts.append("Upcoming stops: " + "; ".join(stops) + ".")
    cells = S.congestion.get("cells", [])
    if cells:
        worst = max(cells, key=lambda c: c["congestion"])
        if worst["congestion"] >= congestion_mod.BUSY:
            parts.append(
                f"Heavy traffic near ({worst['lat']:.3f},{worst['lng']:.3f}) — easing off smooths the run.")
    if S.disruptions:
        parts.append(f"{len(S.disruptions)} disruption(s) are active on the network.")
    if lat or lng:
        parts.append(f"Driver position: ({lat:.4f},{lng:.4f}).")
    return " ".join(parts)


def _driver_directions_fallback(question: str, courier_id: str) -> str:
    """Deterministic in-cab answer when no model is available (never silent)."""
    low = question.lower()
    if any(w in low for w in ("speed", "green", "light", "signal", "fast", "slow down")):
        return "Hold around 28 km/h to catch the next green wave."
    if any(w in low for w in ("traffic", "congestion", "busy", "jam")):
        cells = S.congestion.get("cells", [])
        if cells:
            worst = max(cells, key=lambda c: c["congestion"])
            return (f"Busiest cell is near ({worst['lat']:.3f},{worst['lng']:.3f}); "
                    "ease your speed and I'll smooth the green wave.")
        return "Traffic looks clear on your route right now."
    if any(w in low for w in ("closed", "closure", "blocked", "bridge")):
        return (f"There are {len(S.disruptions)} reported closures; "
                "I'll keep your route clear of them.")
    stops = _driver_next_stops(courier_id, 1)
    if stops:
        return f"Your next stop is {stops[0]}."
    return "I'm your in-cab guide — ask about your next stop, traffic, or the best speed."


class DriverAsk(BaseModel):
    question: str = Field(min_length=1, max_length=300)
    courier_id: str = ""
    driver_id: str = ""
    lat: float = 0.0
    lng: float = 0.0
    heading: float = 0.0


@app.post("/driver/ask")
async def driver_ask(body: DriverAsk):
    """In-cab directions Q&A. Answers via the local-model LLM seam (Ollama on the
    GB10, OpenAI in prod) grounded in the driver's live route + congestion, with a
    deterministic fallback so it always replies. No operator auth — drivers ask
    straight from the cab; pair with /tts for a spoken answer."""
    q = body.question.strip()
    answer = None
    try:
        answer = await asyncio.to_thread(
            llm.chat, q, system=_driver_context(body.courier_id, body.lat, body.lng))
    except Exception:  # noqa: BLE001 - never let the cab assistant hang
        answer = None
    if not answer:
        answer = _driver_directions_fallback(q, body.courier_id)
    await HUB.emit("agent_log", {"level": "info", "source": "driver",
                                 "message": f"Driver asked: {q[:80]}"})
    return {"answer": answer, "driver_id": body.driver_id, "courier_id": body.courier_id}



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


# ----------------------------------------------------------------------------- TTS proxy
class TtsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)

@app.post("/tts")
async def tts_proxy(body: TtsRequest, _user: CurrentUser = Depends(require_user)):
    """Proxy ElevenLabs TTS so the API key never leaves the server.
    Returns audio/mpeg on success; 503 if no key is configured."""
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="text required")
    api_key = os.getenv("ELEVENLABS_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=503, detail="ElevenLabs not configured — set ELEVENLABS_API_KEY")
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    payload = {
        "text": text,
        "model_id": os.getenv("ELEVENLABS_MODEL_ID", "eleven_turbo_v2_5"),
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                url,
                headers={"xi-api-key": api_key, "accept": "audio/mpeg", "content-type": "application/json"},
                json=payload,
            )
            r.raise_for_status()
            return HTTPResponse(content=r.content, media_type="audio/mpeg")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"ElevenLabs TTS failed: {type(e).__name__}")


# ----------------------------------------------------------------------------- WS
@app.websocket("/ws")
async def ws(ws: WebSocket):
    await HUB.join(ws)
    try:
        while True:
            await ws.receive_text()  # we don't expect client messages; keepalive only
    except WebSocketDisconnect:
        HUB.leave(ws)
