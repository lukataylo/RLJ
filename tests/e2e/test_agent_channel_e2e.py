"""End-to-end tests for the operator<->NemoClaw agent channel, fleet assessments,
courier redirect, and the CCTV (TfL JamCam) proxy — against the real cross-process
stack (routing + orchestrator on fresh ports).

The boot/teardown `stack` fixture mirrors tests/e2e/test_nemoclaw_e2e.py exactly
(free ports, ROUTING_URL, /healthz poll). Every WebSocket read uses recv(timeout=...)
and every wait is deadline-bounded so the suite can never hang.
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


def _collect_ws(ws, predicate, deadline_s: float = 12.0):
    """Drain WS frames until `predicate(event)` is truthy (return that event) or the
    deadline elapses (return None). Also returns the list of all event types seen."""
    seen_types: list = []
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        try:
            ev = json.loads(ws.recv(timeout=2))
        except TimeoutError:
            continue
        seen_types.append(ev.get("type"))
        if predicate(ev):
            return ev, seen_types
    return None, seen_types


def test_ask_tasks_answer_flow(stack):
    """POST /agent/ask -> the orchestrator answers directly (LLM seam, or deterministic
    fleet-summary fallback when no LLM is configured): the returned task is 'answered'
    with a non-empty answer, and an 'agent_answer' frame (plus an agent_log line with
    source 'nemotron') is broadcast. The /agent/answer box-agent path still works."""
    from websockets.sync.client import connect

    base = stack["base"]
    with connect(stack["ws"]) as ws:
        # drain the initial state snapshot + any replayed history
        _collect_ws(ws, lambda ev: False, deadline_s=1.5)

        with httpx.Client(base_url=base, timeout=15) as c:
            r = c.post("/agent/ask", json={"question": "Which junctions are worst right now?"})
            assert r.status_code == 200, r.text
            task = r.json()
            assert task.get("status") == "answered", task
            assert task.get("answer"), "no direct answer returned"
            task_id = task["id"]
            assert task_id

            # the optional GB10 box path is still accepted (idempotent)
            ans = c.post("/agent/answer", json={"task_id": task_id, "answer": "Bank and Aldgate are hottest."})
            assert ans.status_code == 200, ans.text
            assert ans.json().get("ok") is True

        # an agent_answer frame (and/or an agent_log nemotron line) must arrive
        def _is_answer(ev):
            if ev.get("type") == "agent_answer":
                return True
            if ev.get("type") == "agent_log":
                return (ev.get("payload") or {}).get("source") == "nemotron"
            return False

        hit, seen = _collect_ws(ws, _is_answer, deadline_s=12.0)
        assert hit is not None, f"no agent_answer/agent_log(nemotron) after ask; saw {seen}"


def test_fleet_assessments_roundtrip_and_broadcast(stack):
    """POST /fleet/assessments stores per-driver assessments: GET returns them, they land
    in /state.fleet_assessments, and a 'fleet_assessments' WS frame fires."""
    from websockets.sync.client import connect

    base = stack["base"]
    payload = {"assessments": [
        {"courier_id": "fa-1", "status": "at_risk", "note": "Heavy congestion near Bank."},
        {"courier_id": "fa-2", "status": "on_time", "note": "Clear run."},
    ]}
    with connect(stack["ws"]) as ws:
        _collect_ws(ws, lambda ev: False, deadline_s=1.5)

        with httpx.Client(base_url=base, timeout=10) as c:
            r = c.post("/fleet/assessments", json=payload)
            assert r.status_code == 200, r.text
            assert r.json().get("accepted") == 2

            got = c.get("/fleet/assessments")
            assert got.status_code == 200, got.text
            by_id = {a["courier_id"]: a for a in got.json()}
            assert by_id["fa-1"]["status"] == "at_risk"
            assert by_id["fa-1"]["note"] == "Heavy congestion near Bank."
            assert by_id["fa-2"]["status"] == "on_time"

            state = c.get("/state").json()
            st_ids = {a["courier_id"] for a in state.get("fleet_assessments", [])}
            assert {"fa-1", "fa-2"} <= st_ids, f"assessments missing from /state: {state.get('fleet_assessments')}"

        def _is_fleet(ev):
            if ev.get("type") != "fleet_assessments":
                return False
            ids = {a.get("courier_id") for a in (ev.get("payload") or [])}
            return {"fa-1", "fa-2"} <= ids

        hit, seen = _collect_ws(ws, _is_fleet, deadline_s=10.0)
        assert hit is not None, f"no fleet_assessments WS frame; saw {seen}"


def test_redirect_known_and_unknown(stack):
    """Seeding a courier then POSTing /couriers/{id}/redirect returns 200 {ok:true} (it
    re-optimises); an unknown courier id returns 404."""
    base = stack["base"]
    with httpx.Client(base_url=base, timeout=20) as c:
        courier = {
            "id": "rd-1", "name": "Redirect Rider", "capacity": 4,
            "cold_capable": True, "status": "idle", "vehicle_type": "van",
            "location": {"lat": 51.5142, "lng": -0.0755, "name": "Aldgate"},
            "phone": "+447009000099",
        }
        seed = c.post("/couriers", json=courier)
        assert seed.status_code == 200, seed.text

        r = c.post("/couriers/rd-1/redirect")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert body.get("courier_id") == "rd-1"

        missing = c.post("/couriers/does-not-exist/redirect")
        assert missing.status_code == 404, missing.text


def test_cctv_cameras_shape(stack):
    """GET /cctv/cameras returns 200 + a JSON list. TfL may be unreachable in CI, so an
    empty list is acceptable; if non-empty, each item carries id/lat/lng/image."""
    base = stack["base"]
    with httpx.Client(base_url=base, timeout=15) as c:
        r = c.get("/cctv/cameras")
        assert r.status_code == 200, r.text
        cams = r.json()
        assert isinstance(cams, list), f"expected a list, got {type(cams)}"
        for cam in cams:
            assert "id" in cam
            assert "lat" in cam and "lng" in cam
            assert "image" in cam
