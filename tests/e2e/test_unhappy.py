"""End-to-end UNHAPPY-path tests — the priority suite.

Drives the real orchestrator (and routing service, where relevant) as separate processes
and proves the system degrades gracefully: bad input is rejected with 4xx (never 5xx),
infeasible/empty work returns sane plans, and the routing service being DOWN still yields
a plan via the greedy fallback. All WS reads use bounded recv(timeout=...) so nothing
can hang.
"""
from __future__ import annotations
import json, os, socket, subprocess, sys, time
from pathlib import Path

import pytest
import httpx

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parent.parent.parent
TOWER = (51.5081, -0.0759)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_health(url: str, timeout: float = 40.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=1.0).status_code == 200:
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.3)
    raise RuntimeError(f"service at {url} never became healthy")


def _venv_py() -> str:
    venv_python = str(ROOT / ".venv" / "bin" / "python")
    return venv_python if Path(venv_python).exists() else sys.executable


def _boot_routing(port: int):
    return subprocess.Popen(
        [_venv_py(), "-m", "uvicorn", "app:app", "--app-dir", "routing", "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _boot_orch(port: int, routing_url: str):
    env = {**os.environ, "ROUTING_URL": routing_url}
    return subprocess.Popen(
        [_venv_py(), "-m", "uvicorn", "app:app", "--app-dir", "orchestrator", "--port", str(port)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _terminate(*procs):
    for p in procs:
        if p is None:
            continue
        p.terminate()
        try:
            p.wait(timeout=5)
        except Exception:  # noqa: BLE001
            p.kill()


@pytest.fixture(scope="module")
def stack():
    """Routing + orchestrator both up (module-scoped: shared across most unhappy tests)."""
    routing_port, orch_port = _free_port(), _free_port()
    routing = _boot_routing(routing_port)
    orch = _boot_orch(orch_port, f"http://127.0.0.1:{routing_port}")
    base = f"http://127.0.0.1:{orch_port}"
    try:
        _wait_health(f"http://127.0.0.1:{routing_port}/healthz")
        _wait_health(f"{base}/healthz")
        yield {"base": base, "ws": base.replace("http", "ws") + "/ws"}
    finally:
        _terminate(orch, routing)


@pytest.fixture()
def fresh_stack():
    """A clean routing + orchestrator pair (function-scoped) for tests that need an
    isolated courier/job set (cold-chain feasibility, all-offline)."""
    routing_port, orch_port = _free_port(), _free_port()
    routing = _boot_routing(routing_port)
    orch = _boot_orch(orch_port, f"http://127.0.0.1:{routing_port}")
    base = f"http://127.0.0.1:{orch_port}"
    try:
        _wait_health(f"http://127.0.0.1:{routing_port}/healthz")
        _wait_health(f"{base}/healthz")
        yield {"base": base, "ws": base.replace("http", "ws") + "/ws"}
    finally:
        _terminate(orch, routing)


@pytest.fixture(scope="module")
def orch_no_routing():
    """Orchestrator only; ROUTING_URL points at a dead port -> greedy fallback path."""
    orch_port = _free_port()
    dead_port = _free_port()  # nothing is ever bound here
    orch = _boot_orch(orch_port, f"http://127.0.0.1:{dead_port}")
    base = f"http://127.0.0.1:{orch_port}"
    try:
        _wait_health(f"{base}/healthz")
        yield {"base": base, "ws": base.replace("http", "ws") + "/ws"}
    finally:
        _terminate(orch)


def _ok_ping(driver_id: str, lat=TOWER[0], lng=TOWER[1], speed=1.0) -> dict:
    return {"driver_id": driver_id, "lat": lat, "lng": lng, "speed_mps": speed,
            "heading_deg": 90.0, "ts": "2026-06-05T10:00:00Z"}


# =========================================================================== signup
def test_signup_without_consent_is_422(stack):
    r = httpx.post(f"{stack['base']}/drivers",
                   json={"name": "No Consent", "vehicle_type": "bike", "consent": False},
                   timeout=10)
    assert r.status_code == 422, r.text
    # system stays healthy
    assert httpx.get(f"{stack['base']}/healthz", timeout=5).status_code == 200


# =========================================================================== telemetry
def test_bad_pings_rejected_good_accepted(stack):
    """Out-of-London and over-speed (>40 m/s) pings are rejected; valid ones still ingest."""
    drv = httpx.post(f"{stack['base']}/drivers",
                     json={"name": "Mixed", "vehicle_type": "car", "consent": True},
                     timeout=10).json()
    batch = {"pings": [
        _ok_ping(drv["id"]),                                  # valid
        _ok_ping(drv["id"], lat=0.0, lng=0.0),               # out of London bbox
        _ok_ping(drv["id"], speed=99.0),                     # over-speed > 40 m/s
    ]}
    r = httpx.post(f"{stack['base']}/telemetry", json=batch, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rejected"] >= 2, body
    assert body["accepted"] >= 1, body


def test_unknown_driver_not_counted(stack):
    """With drivers present, telemetry from an unknown/non-consenting id is not counted."""
    known = httpx.post(f"{stack['base']}/drivers",
                       json={"name": "Known", "vehicle_type": "bike", "consent": True},
                       timeout=10).json()
    batch = {"pings": [_ok_ping(known["id"]), _ok_ping("ghost-driver-xyz")]}
    r = httpx.post(f"{stack['base']}/telemetry", json=batch, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    # the ghost ping is filtered before validation: only the known driver's ping counts
    assert body["accepted"] == 1, body
    assert body["rejected"] == 0, body


def test_empty_telemetry_is_sane(stack):
    r = httpx.post(f"{stack['base']}/telemetry", json={"pings": []}, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["accepted"] == 0 and body["rejected"] == 0


# =========================================================================== jobs
def test_malformed_job_is_422_and_system_healthy(stack):
    """A job missing the required 'type' field -> 422; orchestrator still serves traffic."""
    bad = {"origin": {"lat": 51.51, "lng": -0.13},
           "destination": {"lat": 51.49, "lng": -0.11}, "priority": "stat"}
    r = httpx.post(f"{stack['base']}/jobs", json=bad, timeout=10)
    assert r.status_code == 422, r.text
    # still healthy + still serving
    assert httpx.get(f"{stack['base']}/healthz", timeout=5).status_code == 200
    assert httpx.get(f"{stack['base']}/jobs", timeout=5).status_code == 200


def test_infeasible_cold_job_unassigned_no_crash(fresh_stack):
    """Cold-chain job but only a non-cold courier -> job is unassigned, plan still returned."""
    base = fresh_stack["base"]
    httpx.post(f"{base}/couriers", json={
        "id": "crt-warm", "name": "NoFridge", "capacity": 6, "cold_capable": False,
        "status": "idle", "location": {"lat": 51.50, "lng": -0.12}}, timeout=10)
    job = httpx.post(f"{base}/jobs", json={
        "id": "job-cold", "type": "sample_pickup", "priority": "stat", "cold_chain": True,
        "capacity_units": 1, "status": "new",
        "origin": {"lat": 51.515, "lng": -0.08},
        "destination": {"lat": 51.498, "lng": -0.119},
        "time_window": {"due_by": "2027-01-01T00:00:00Z"}}, timeout=10)
    assert job.status_code == 200, job.text

    plan = httpx.get(f"{base}/plan", timeout=10).json()
    assert plan is not None, "no plan returned"
    assert "job-cold" in plan["unassigned"], f"cold job should be unassigned: {plan}"
    # no courier was given the impossible cold job
    assigned_ids = {s["job_id"] for r in plan["routes"] for s in r["stops"]}
    assert "job-cold" not in assigned_ids


# =========================================================================== optimize
def test_all_couriers_offline_returns_empty_plan(fresh_stack):
    """Every courier offline -> /optimize returns a valid plan with no routes, no 500."""
    base = fresh_stack["base"]
    httpx.post(f"{base}/couriers", json={
        "id": "crt-off", "name": "Off", "capacity": 6, "cold_capable": True,
        "status": "offline", "location": {"lat": 51.50, "lng": -0.12}}, timeout=10)
    httpx.post(f"{base}/jobs", json={
        "id": "job-orphan", "type": "sample_pickup", "priority": "urgent",
        "capacity_units": 1, "status": "new",
        "origin": {"lat": 51.515, "lng": -0.08},
        "destination": {"lat": 51.498, "lng": -0.119},
        "time_window": {"due_by": "2027-01-01T00:00:00Z"}}, timeout=10)

    r = httpx.post(f"{base}/optimize", timeout=10)
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["routes"] == [], f"offline couriers should yield no routes: {plan}"
    assert "job-orphan" in plan["unassigned"]


def test_empty_optimize_is_sane(fresh_stack):
    """No couriers, no jobs -> /optimize returns an empty plan (200, not 500)."""
    r = httpx.post(f"{fresh_stack['base']}/optimize", timeout=10)
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["routes"] == []
    assert plan["unassigned"] == []


# =========================================================================== routing down
def test_routing_down_uses_greedy_fallback(orch_no_routing):
    """Routing service unreachable -> orchestrator still plans (greedy) and healthz says so."""
    base = orch_no_routing["base"]
    h = httpx.get(f"{base}/healthz", timeout=5).json()
    assert h["routing_service"] is False, h

    httpx.post(f"{base}/couriers", json={
        "id": "crt-1", "name": "A", "capacity": 6, "cold_capable": True,
        "status": "idle", "location": {"lat": 51.50, "lng": -0.12}}, timeout=10)
    job = httpx.post(f"{base}/jobs", json={
        "id": "job-1", "type": "sample_pickup", "priority": "stat", "cold_chain": True,
        "capacity_units": 1, "status": "new",
        "origin": {"lat": 51.515, "lng": -0.08},
        "destination": {"lat": 51.498, "lng": -0.119},
        "time_window": {"due_by": "2027-01-01T00:00:00Z"}}, timeout=10)
    assert job.status_code == 200, job.text

    plan = httpx.get(f"{base}/plan", timeout=10).json()
    assert plan is not None, "greedy fallback produced no plan"
    assert plan["objective"]["solver"] == "greedy-fallback"
    assert len(plan["routes"]) == 1


# =========================================================================== guidance
def test_unknown_driver_guidance_status(stack):
    """Guidance for an unknown driver -> status 'unknown', no 500."""
    r = httpx.get(f"{stack['base']}/driver/does-not-exist/guidance", timeout=10)
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["status"] == "unknown"
    assert g["driver_id"] == "does-not-exist"
    assert g["contribution"]["pings"] == 0


# =========================================================================== websocket
def test_ws_reconnect_still_gets_state(stack):
    """Connect, disconnect, reconnect -> a fresh state snapshot arrives each time."""
    from websockets.sync.client import connect

    with connect(stack["ws"]) as ws:
        first = json.loads(ws.recv(timeout=5))
        assert first["type"] == "state"
        assert "jobs" in first["payload"]

    # reconnect on a brand-new socket
    with connect(stack["ws"]) as ws2:
        again = json.loads(ws2.recv(timeout=5))
        assert again["type"] == "state"
        assert "couriers" in again["payload"]
