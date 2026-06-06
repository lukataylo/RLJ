"""End-to-end tests for the GB10 Nemotron signal-recommendation pipeline, against the
real cross-process stack (routing + orchestrator on fresh ports). The boot/teardown
fixture mirrors tests/e2e/test_demo_flow.py / test_nemoclaw_e2e.py exactly (no mocks,
no in-process app).

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


def _rec(name, lat, lng, action, detail, confidence=0.7):
    return {"name": name, "lat": lat, "lng": lng, "action": action,
            "detail": detail, "confidence": confidence, "source": "nemotron@scan-11"}


def test_signals_post_get_roundtrip(stack):
    """POST 2 valid recs -> {accepted:2}; GET returns them with fields intact; and they
    appear in GET /state.signal_recs."""
    base = stack["base"]
    recs = [
        _rec("Bank junction", 51.5134, -0.0886, "green_wave",
             "Extend N-S green to clear courier corridor."),
        _rec("Aldgate gyratory", 51.5142, -0.0755, "retime",
             "Shorten cycle to 84s to ease congestion.", 0.62),
    ]
    with httpx.Client(base_url=base, timeout=10) as c:
        r = c.post("/signals/recommendations", json={"recommendations": recs})
        assert r.status_code == 200, r.text
        assert r.json() == {"accepted": 2}

        got = c.get("/signals/recommendations")
        assert got.status_code == 200, got.text
        body = got.json()
        assert isinstance(body, list) and len(body) == 2, body
        by_name = {x["name"]: x for x in body}
        assert set(by_name) == {"Bank junction", "Aldgate gyratory"}
        bank = by_name["Bank junction"]
        assert bank["lat"] == 51.5134 and bank["lng"] == -0.0886
        assert bank["action"] == "green_wave"
        assert bank["detail"] == "Extend N-S green to clear courier corridor."
        assert bank["confidence"] == 0.7
        assert bank["source"] == "nemotron@scan-11"

        state = c.get("/state")
        assert state.status_code == 200, state.text
        srecs = state.json().get("signal_recs")
        assert isinstance(srecs, list) and len(srecs) == 2, srecs
        assert {x["name"] for x in srecs} == {"Bank junction", "Aldgate gyratory"}


def test_signals_broadcast(stack):
    """Connecting a WS client and POSTing a rec broadcasts a 'signal_recs' event
    (and an agent_log line naming the recommendation) within ~8s."""
    from websockets.sync.client import connect

    base = stack["base"]
    with connect(stack["ws"]) as ws:
        # first frame is the initial state snapshot; drain anything buffered (e.g. the
        # NemoClaw agent's startup narration replay) without blocking the test.
        try:
            ws.recv(timeout=5)
        except TimeoutError:
            pass

        rec = _rec("Elephant & Castle", 51.4946, -0.0997, "hold",
                   "Hold W approach 6s for inbound STAT courier.")
        r = httpx.post(f"{base}/signals/recommendations",
                       json={"recommendations": [rec]}, timeout=10)
        assert r.status_code == 200, r.text

        saw_signal_recs = False
        saw_agent_log = False
        seen_types: list = []
        deadline = time.time() + 8
        while time.time() < deadline and not (saw_signal_recs and saw_agent_log):
            try:
                ev = json.loads(ws.recv(timeout=2))
            except TimeoutError:
                continue
            seen_types.append(ev.get("type"))
            if ev.get("type") == "signal_recs":
                payload = ev.get("payload") or []
                if any(x.get("name") == "Elephant & Castle" for x in payload):
                    saw_signal_recs = True
            if ev.get("type") == "agent_log":
                msg = (ev.get("payload") or {}).get("message", "")
                if "Elephant & Castle" in msg or "signal rec" in msg.lower():
                    saw_agent_log = True

    assert saw_signal_recs, f"no 'signal_recs' broadcast within 8s; saw types={seen_types}"
    assert saw_agent_log, f"no agent_log mentioning the rec within 8s; saw types={seen_types}"


def test_signals_malformed_422(stack):
    """A rec missing required lat/lng is rejected with 422 and the system stays healthy."""
    base = stack["base"]
    with httpx.Client(base_url=base, timeout=10) as c:
        bad = {"recommendations": [{"name": "No coords junction", "action": "retime",
                                    "detail": "missing lat/lng"}]}
        r = c.post("/signals/recommendations", json=bad)
        assert r.status_code == 422, r.text

        # system still healthy and serving
        h = c.get("/healthz")
        assert h.status_code == 200, h.text
        assert h.json().get("status") == "ok"
        # GET still works
        assert c.get("/signals/recommendations").status_code == 200
