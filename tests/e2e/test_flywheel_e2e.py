"""End-to-end happy-path tests for the crowdsourced-driver data flywheel.

Boots the real routing service and orchestrator as separate processes (same pattern as
tests/e2e/test_demo_flow.py) and drives the flywheel over HTTP + WebSocket exactly as
the driver-app / dashboard would:

  driver signup -> telemetry (jammed probes) -> congestion field -> derived disruption
  -> medical re-optimise (plan_updated) -> driver gets green-wave guidance back.

All WS reads use bounded recv(timeout=...) so the gate can never hang.
"""
from __future__ import annotations
import json, os, socket, subprocess, sys, time
from pathlib import Path

import pytest
import httpx

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parent.parent.parent

# Tower of London-ish point; all jammed probes land in one ~400 m grid cell.
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


@pytest.fixture(scope="module")
def stack():
    """Routing + orchestrator on fresh ports, wired together; yield URLs; tear down."""
    routing_port = _free_port()
    orch_port = _free_port()
    venv_python = str(ROOT / ".venv" / "bin" / "python")
    py = venv_python if Path(venv_python).exists() else sys.executable

    routing = subprocess.Popen(
        [py, "-m", "uvicorn", "app:app", "--app-dir", "routing", "--port", str(routing_port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    env = {**os.environ, "ROUTING_URL": f"http://127.0.0.1:{routing_port}"}
    orch = subprocess.Popen(
        [py, "-m", "uvicorn", "app:app", "--app-dir", "orchestrator", "--port", str(orch_port)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{orch_port}"
    try:
        _wait_health(f"http://127.0.0.1:{routing_port}/healthz")
        _wait_health(f"{base}/healthz")
        assert httpx.get(f"{base}/healthz", timeout=2).json().get("routing_service") is True
        yield {"base": base, "ws": base.replace("http", "ws") + "/ws"}
    finally:
        for p in (orch, routing):
            p.terminate()
            try:
                p.wait(timeout=5)
            except Exception:  # noqa: BLE001
                p.kill()


# --------------------------------------------------------------------------- helpers
def _collect_ws(ws, want_types: set[str], overall_timeout: float = 20.0) -> dict:
    """Read events until every type in want_types has been seen (or we time out).
    Returns {type: last_payload_event}. Never blocks longer than overall_timeout."""
    got: dict = {}
    deadline = time.time() + overall_timeout
    while time.time() < deadline and not want_types.issubset(got.keys()):
        try:
            ev = json.loads(ws.recv(timeout=2))
        except TimeoutError:
            continue
        got[ev["type"]] = ev
    return got


def _seed_medical(base: str):
    """A cold-capable courier + a cold-chain medical job so telemetry triggers a re-plan."""
    with httpx.Client(base_url=base, timeout=10) as c:
        c.post("/couriers", json={
            "id": "crt-fly", "name": "Medic", "capacity": 6, "cold_capable": True,
            "status": "idle", "location": {"lat": 51.50, "lng": -0.12, "name": "depot"},
            "phone": "+447700900111"})
        c.post("/jobs", json={
            "id": "job-fly", "type": "sample_pickup", "priority": "stat", "cold_chain": True,
            "capacity_units": 1, "status": "new",
            "origin": {"lat": 51.515, "lng": -0.08, "name": "pickup"},
            "destination": {"lat": 51.498, "lng": -0.119, "name": "St Thomas' lab"},
            "time_window": {"due_by": "2027-01-01T00:00:00Z"}})


def _jammed_batch(driver_id: str, n: int = 8) -> dict:
    return {"pings": [
        {"driver_id": driver_id, "lat": TOWER[0], "lng": TOWER[1],
         "speed_mps": 0.4, "heading_deg": 90.0, "ts": "2026-06-05T10:00:00Z"}
        for _ in range(n)]}


# --------------------------------------------------------------------------- tests
def test_driver_signup_with_consent(stack):
    """Consenting signup returns an id, shows up in GET /drivers, and fires driver_joined."""
    from websockets.sync.client import connect

    with connect(stack["ws"]) as ws:
        assert json.loads(ws.recv(timeout=5))["type"] == "state"  # initial snapshot
        r = httpx.post(f"{stack['base']}/drivers",
                       json={"name": "Rider Jo", "vehicle_type": "bike", "consent": True},
                       timeout=10)
        assert r.status_code == 200, r.text
        driver = r.json()
        assert driver["id"], "server did not assign a driver id"
        assert driver["consent"] is True

        got = _collect_ws(ws, {"driver_joined"})
        assert "driver_joined" in got, "no driver_joined WS event"
        assert got["driver_joined"]["payload"]["id"] == driver["id"]

    listed = httpx.get(f"{stack['base']}/drivers", timeout=10).json()
    assert any(d["id"] == driver["id"] for d in listed)


def test_telemetry_flywheel_loop(stack):
    """Jammed probes -> congested cell -> congestion_updated + plan_updated broadcast."""
    from websockets.sync.client import connect

    _seed_medical(stack["base"])
    drv = httpx.post(f"{stack['base']}/drivers",
                     json={"name": "Probe", "vehicle_type": "car", "consent": True},
                     timeout=10).json()

    with connect(stack["ws"]) as ws:
        assert json.loads(ws.recv(timeout=5))["type"] == "state"
        r = httpx.post(f"{stack['base']}/telemetry",
                       json=_jammed_batch(drv["id"], 8), timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["accepted"] == 8 and body["rejected"] == 0
        assert body["cells_updated"] >= 1

        got = _collect_ws(ws, {"congestion_updated", "plan_updated"})
        assert "congestion_updated" in got, "no congestion_updated event"
        assert "plan_updated" in got, "no plan_updated (re-optimise) event"

    field = httpx.get(f"{stack['base']}/congestion", timeout=10).json()
    assert field["cells"], "congestion field is empty"
    assert max(c["congestion"] for c in field["cells"]) >= 0.5, "no congested cell"


def test_driver_guidance_reflects_contribution(stack):
    """A driver's guidance reports the pings it contributed and a sane status."""
    drv = httpx.post(f"{stack['base']}/drivers",
                     json={"name": "Contributor", "vehicle_type": "scooter", "consent": True},
                     timeout=10).json()
    httpx.post(f"{stack['base']}/telemetry", json=_jammed_batch(drv["id"], 6), timeout=10)

    g = httpx.get(f"{stack['base']}/driver/{drv['id']}/guidance", timeout=10).json()
    assert g["driver_id"] == drv["id"]
    assert g["status"] == "active"
    assert g["contribution"]["pings"] >= 6, g["contribution"]
    assert g["contribution"]["couriers_helped"] >= 0


def test_signals_advice_shape(stack):
    """/signals/advice returns a SignalAdvice with a message + numeric speed target."""
    r = httpx.get(f"{stack['base']}/signals/advice",
                  params={"driver_id": "drv-x", "lat": TOWER[0], "lng": TOWER[1],
                          "heading": 90.0}, timeout=10)
    assert r.status_code == 200, r.text
    adv = r.json()
    assert adv["message"], "SignalAdvice has no message"
    assert isinstance(adv["target_speed_mps"], (int, float))
    assert 0.0 <= adv["confidence"] <= 1.0
    assert adv["junction"]["lat"] == pytest.approx(TOWER[0])
