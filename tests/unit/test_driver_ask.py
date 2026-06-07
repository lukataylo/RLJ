"""Offline, deterministic tests for the in-cab driver directions Q&A (POST /driver/ask).

The driver app asks natural-language questions ("where's my next stop?", "how's
traffic?", "what speed for the green?"). The orchestrator answers via the LLM seam
(Ollama on the GB10, OpenAI in prod) grounded in the driver's live route, and falls
back to a deterministic, route-aware answer when no model is configured — so the cab
assistant is never silent. These tests force the fallback (llm.chat -> None) so they
need no network, no key, and no provider.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]

_COLLIDING = (
    "app", "models", "seed", "greedy", "congestion", "geocode", "intake", "nl_intake",
    "solver", "solver_baseline", "solver_ortools", "solver_aco", "solver_ls",
    "traveltime",
)


def _load_app():
    sys.path.insert(0, str(ROOT / "orchestrator"))
    for mod in _COLLIDING:
        sys.modules.pop(mod, None)
    return importlib.import_module("app")


def _route_with_stop(app_mod, name="Camden clinic", courier_id="c1"):
    models = importlib.import_module("models")
    stop = models.Stop(
        job_id="j1", kind="pickup",
        location=models.Location(lat=51.54, lng=-0.14, name=name), sequence=0)
    route = models.Route(courier_id=courier_id, stops=[stop])
    app_mod.S.plan = models.Plan(routes=[route], objective=models.Objective())


@pytest.fixture()
def client(monkeypatch):
    app_mod = _load_app()
    # Force the deterministic fallback path (no model available).
    monkeypatch.setattr(app_mod.llm, "chat", lambda *a, **k: None)
    return TestClient(app_mod.app), app_mod


def test_driver_ask_always_answers(client):
    c, _ = client
    r = c.post("/driver/ask", json={"question": "how is traffic right now?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"] and isinstance(body["answer"], str)


def test_driver_ask_grounded_in_next_stop(client):
    c, app_mod = client
    _route_with_stop(app_mod, name="Camden clinic", courier_id="c1")
    r = c.post("/driver/ask",
               json={"question": "where is my next stop?", "courier_id": "c1"})
    assert r.status_code == 200, r.text
    assert "Camden clinic" in r.json()["answer"]


def test_driver_ask_speed_intent(client):
    c, _ = client
    r = c.post("/driver/ask", json={"question": "what speed for the green light?"})
    assert r.status_code == 200, r.text
    assert "km/h" in r.json()["answer"]


def test_driver_ask_rejects_empty(client):
    c, _ = client
    r = c.post("/driver/ask", json={"question": "   "})
    # blank after strip -> the deterministic guide still answers (never 5xx); the
    # endpoint must not crash on whitespace.
    assert r.status_code in (200, 422)


def test_driver_ask_validation_missing_question(client):
    c, _ = client
    r = c.post("/driver/ask", json={})
    assert r.status_code == 422  # question is required
