"""End-to-end demo flow checks over the orchestrator FastAPI app.

These are intentionally in-process. They verify the public REST flow and emitted
events without needing a browser, a routing service, or external voice provider.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent.parent
ORCH_DIR = ROOT / "orchestrator"


def _load_orchestrator():
    for module in ("app", "models", "greedy"):
        sys.modules.pop(module, None)
    with pytest.MonkeyPatch.context() as mp:
        try:
            sys.path.remove(str(ORCH_DIR))
        except ValueError:
            pass
        sys.path.insert(0, str(ORCH_DIR))
        spec = importlib.util.spec_from_file_location("app", ORCH_DIR / "app.py")
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules["app"] = module
        spec.loader.exec_module(module)
        mp.undo()
        return module


def _courier():
    return {
        "id": "crt-demo",
        "name": "Demo Courier",
        "location": {"lat": 51.5033, "lng": -0.0875, "name": "Guy's Hospital"},
        "status": "idle",
        "phone": "+447700900000",
    }


def _job():
    return {
        "id": "job-demo",
        "type": "sample_pickup",
        "origin": {"lat": 51.5033, "lng": -0.0875, "name": "Guy's Hospital"},
        "destination": {"lat": 51.5290, "lng": -0.1200, "name": "Health Services Laboratories"},
        "priority": "stat",
        "time_window": {
            "ready_at": "2026-06-05T08:00:00+00:00",
            "due_by": "2026-06-05T09:00:00+00:00",
        },
        "cold_chain": True,
        "status": "new",
        "created_at": "2026-06-05T08:00:00+00:00",
    }


@pytest.mark.e2e
def test_close_road_reroutes(monkeypatch):
    app_mod = _load_orchestrator()
    emitted: list[tuple[str, object]] = []

    async def capture(type_, payload):
        emitted.append((type_, payload))

    monkeypatch.setattr(app_mod.HUB, "emit", capture)
    client = TestClient(app_mod.app)

    assert client.post("/couriers", json=_courier()).status_code == 200
    assert client.post("/jobs", json=_job()).status_code == 200
    before = client.get("/plan").json()["generated_at"]

    disruption = {
        "id": "demo-closure",
        "kind": "road_closure",
        "geometry": [{"lat": 51.51, "lng": -0.10}, {"lat": 51.52, "lng": -0.11}],
        "source": "manual",
        "at": "2026-06-05T08:10:00+00:00",
    }
    response = client.post("/disruptions", json=disruption)

    assert response.status_code == 200
    after_plan = client.get("/plan").json()
    assert after_plan["generated_at"] != before
    assert any(event_type == "disruption" for event_type, _ in emitted)
    assert any(event_type == "plan_updated" for event_type, _ in emitted)


@pytest.mark.e2e
def test_voice_call_emitted(monkeypatch):
    app_mod = _load_orchestrator()
    emitted: list[tuple[str, object]] = []

    async def capture(type_, payload):
        emitted.append((type_, payload))

    monkeypatch.setattr(app_mod.HUB, "emit", capture)
    client = TestClient(app_mod.app)

    assert client.post("/couriers", json=_courier()).status_code == 200
    assert client.post("/jobs", json=_job()).status_code == 200

    notifications = [payload for event_type, payload in emitted if event_type == "notification"]
    assert notifications
    assert notifications[-1]["channel"] == "voice_call"
    assert notifications[-1]["to"] == "+447700900000"
    assert "ETA" in notifications[-1]["message"]
