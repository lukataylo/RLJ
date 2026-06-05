"""End-to-end demo-flow tests — the real cross-process loop that we show on stage.

Boots the actual routing service and orchestrator as separate processes (no mocks, no
in-process shortcuts) and drives them over HTTP + WebSocket, exactly as the frontend
does. These bind the two must-pass e2e claims. Kept at the API/WS layer (not a browser)
so the gate is dependable; a browser smoke test lives in tests/e2e/test_ui_smoke.py.
"""
from __future__ import annotations
import json, os, socket, subprocess, sys, time
from pathlib import Path

import pytest
import httpx

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parent.parent.parent


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_health(url: str, timeout: float = 30.0):
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
    """Start routing + orchestrator on fresh ports; yield base URLs; tear down."""
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
        # confirm the orchestrator actually wired to the real routing service
        assert httpx.get(f"{base}/healthz", timeout=2).json().get("routing_service") is True
        yield {"base": base, "routing_port": routing_port, "ws": base.replace("http", "ws") + "/ws"}
    finally:
        for p in (orch, routing):
            p.terminate()
            try:
                p.wait(timeout=5)
            except Exception:  # noqa: BLE001
                p.kill()


DEPOTS = [(51.5079, -0.0877, "London Bridge depot"), (51.5246, -0.1340, "Euston depot")]
LABS = [(51.4980, -0.1188, "St Thomas' lab"), (51.5030, -0.0884, "Guy's lab")]
PICKS = [(51.5290, -0.1225, "Somers Town"), (51.5185, -0.0731, "Royal London"),
         (51.5410, -0.1430, "Camden"), (51.5141, -0.0590, "Bethnal Green"),
         (51.5203, -0.1050, "Clerkenwell")]
WINS = {"stat": 70, "urgent": 130, "routine": 190}


def _seed_couriers(base: str):
    from datetime import datetime, timezone  # noqa: F401
    couriers = [{"id": f"crt-{i+1}", "name": n, "capacity": 6, "cold_capable": True,
                 "status": "idle", "location": {"lat": la, "lng": lo, "name": n},
                 "phone": f"+44700900000{i+1}"} for i, (la, lo, n) in enumerate(DEPOTS)]
    with httpx.Client(base_url=base, timeout=10) as c:
        for crt in couriers:
            c.post("/couriers", json=crt)


def _seed_now_anchored(base: str, n_jobs: int = 5):
    """Seed couriers + now-anchored jobs so ETAs are travel-dominated (a closure visibly
    changes the plan, unlike the future-dated sample where ready_at wait dominates)."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    prios = ["stat", "urgent", "routine", "urgent", "routine"]
    _seed_couriers(base)
    jobs = []
    for i in range(n_jobs):
        p, l, pr = PICKS[i % len(PICKS)], LABS[i % len(LABS)], prios[i % len(prios)]
        jobs.append({
            "id": f"job-{i+1}", "type": "sample_pickup", "priority": pr,
            "cold_chain": True, "capacity_units": 1, "status": "new",
            "origin": {"lat": p[0], "lng": p[1], "name": p[2]},
            "destination": {"lat": l[0], "lng": l[1], "name": l[2]},
            "time_window": {"ready_at": now.isoformat(),
                            "due_by": (now + timedelta(minutes=WINS[pr])).isoformat()},
        })
    with httpx.Client(base_url=base, timeout=10) as c:
        for job in jobs:
            c.post("/jobs", json=job)


def _plan_signature(plan: dict):
    """A comparable fingerprint of a plan: per-courier ordered stop coords + total time."""
    routes = []
    for r in sorted(plan["routes"], key=lambda r: r["courier_id"]):
        routes.append((r["courier_id"],
                       tuple((s["job_id"], s["kind"]) for s in r["stops"]),
                       round(r.get("total_time_s", 0))))
    return (tuple(routes), round(plan["objective"]["total_time_s"]),
            plan["objective"]["windows_met"])


def test_voice_call_emitted(stack):
    """A new job flows through the live stack and produces a voice_call dispatch
    notification on the WebSocket (the voice agent's outbound trigger)."""
    from websockets.sync.client import connect

    _seed_couriers(stack["base"])  # dispatch needs a courier to assign + notify
    with connect(stack["ws"]) as ws:
        ws.recv()  # initial state snapshot
        job = {
            "type": "sample_pickup", "priority": "stat", "cold_chain": True,
            "origin": {"lat": 51.515, "lng": -0.14, "name": "Soho walk-in"},
            "destination": {"lat": 51.498, "lng": -0.119, "name": "St Thomas' lab"},
            "time_window": {"due_by": "2027-01-01T00:00:00Z"},
            "raw_text": "STAT troponin Soho to St Thomas now",
        }
        httpx.post(f"{stack['base']}/jobs", json=job, timeout=10)
        seen = []
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                ev = json.loads(ws.recv(timeout=2))
            except TimeoutError:
                continue
            seen.append(ev["type"])
            if ev["type"] == "notification" and ev["payload"]["channel"] == "voice_call":
                assert ev["payload"]["message"], "voice_call carries no message"
                return
        pytest.fail(f"no voice_call notification; saw {seen}")


def test_close_road_reroutes(stack):
    """Closing a road triggers a live re-optimization that the stack broadcasts, and the
    plan/scoreboard changes in response (the demo money-shot)."""
    from websockets.sync.client import connect

    _seed_now_anchored(stack["base"])
    before = httpx.get(f"{stack['base']}/plan", timeout=10).json()
    sig_before = _plan_signature(before)

    with connect(stack["ws"]) as ws:
        ws.recv()  # initial snapshot
        # close a broad corridor across central London — guaranteed to hit used legs
        closure = {
            "kind": "road_closure", "source": "manual",
            "geometry": [{"lat": 51.50, "lng": -0.14}, {"lat": 51.51, "lng": -0.12},
                         {"lat": 51.52, "lng": -0.10}, {"lat": 51.50, "lng": -0.09}],
        }
        httpx.post(f"{stack['base']}/disruptions", json=closure, timeout=10)

        got_plan_update = False
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                ev = json.loads(ws.recv(timeout=2))
            except TimeoutError:
                continue
            if ev["type"] == "plan_updated":
                got_plan_update = True
                break
        assert got_plan_update, "no plan_updated broadcast after road closure"

    after = httpx.get(f"{stack['base']}/plan", timeout=10).json()
    sig_after = _plan_signature(after)
    assert sig_after != sig_before, "plan did not change after closing a road on a used corridor"
