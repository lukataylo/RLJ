"""End-to-end tests for the NemoClaw agent + courier vehicle_type, against the real
cross-process stack (routing + orchestrator on fresh ports). The boot/teardown
fixture mirrors tests/e2e/test_demo_flow.py exactly (no mocks, no in-process app).

All WebSocket reads use recv(timeout=...) and every wait is deadline-bounded so the
suite can never hang.
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
        assert httpx.get(f"{base}/healthz", timeout=2).json().get("routing_service") is True
        yield {"base": base, "routing_port": routing_port, "ws": base.replace("http", "ws") + "/ws"}
    finally:
        for p in (orch, routing):
            p.terminate()
            try:
                p.wait(timeout=5)
            except Exception:  # noqa: BLE001
                p.kill()


def test_nemoclaw_online_narration(stack):
    """The NemoClaw agent wired at orchestrator startup emits its 'online' line on
    the agent_log channel with source 'nemoclaw' shortly after boot."""
    from websockets.sync.client import connect

    saw_nemoclaw = None
    seen_sources: list = []
    deadline = time.time() + 12
    with connect(stack["ws"]) as ws:
        # first frame is the initial state snapshot
        try:
            ws.recv(timeout=5)
        except TimeoutError:
            pass
        while time.time() < deadline:
            try:
                ev = json.loads(ws.recv(timeout=2))
            except TimeoutError:
                continue
            if ev.get("type") == "agent_log":
                src = (ev.get("payload") or {}).get("source")
                seen_sources.append(src)
                if src == "nemoclaw":
                    saw_nemoclaw = ev["payload"]
                    break

    assert saw_nemoclaw is not None, (
        f"no agent_log with source='nemoclaw' within 12s; saw sources={seen_sources}"
    )
    assert "online" in saw_nemoclaw.get("message", "").lower()


def test_courier_vehicle_type_roundtrips(stack):
    """A courier's vehicle_type persists through POST /couriers -> GET /couriers, and
    omitting it defaults to 'van' (drives the van/scooter icon in the UI)."""
    base = stack["base"]
    with httpx.Client(base_url=base, timeout=10) as c:
        scooter = {
            "id": "crt-scoot", "name": "Scooter One", "capacity": 4,
            "cold_capable": True, "status": "idle", "vehicle_type": "scooter",
            "location": {"lat": 51.51, "lng": -0.12, "name": "Soho"},
            "phone": "+447009000001",
        }
        r = c.post("/couriers", json=scooter)
        assert r.status_code == 200, r.text
        assert r.json().get("vehicle_type") == "scooter"

        default = {
            "id": "crt-default", "name": "Default Van", "capacity": 6,
            "cold_capable": True, "status": "idle",
            "location": {"lat": 51.52, "lng": -0.10, "name": "Clerkenwell"},
            "phone": "+447009000002",
        }
        r2 = c.post("/couriers", json=default)
        assert r2.status_code == 200, r2.text
        assert r2.json().get("vehicle_type") == "van"

        got = c.get("/couriers")
        assert got.status_code == 200, got.text
        by_id = {x["id"]: x for x in got.json()}
        assert by_id["crt-scoot"]["vehicle_type"] == "scooter"
        assert by_id["crt-default"]["vehicle_type"] == "van"
