"""Through-the-app tests for the structured NemoClaw chat: POST /agent/ask returns a
clean (reasoning-stripped) answer plus, when warranted, a proposed operator action that
the UI renders as a Yes/No decision card.

Deterministic + offline: we monkeypatch ``llm.chat`` so no model/key/network is needed.
We exercise BOTH provider paths the seam supports — the LLM-on path (a reasoning model
returning ``<think>…</think>``) and the no-model fallback — proving the chat behaves the
same whether it's local Nemotron, OpenAI, or neither.
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
    "agent_actions", "solver", "solver_baseline", "solver_ortools", "solver_aco",
    "solver_ls", "traveltime",
)


def _load_app(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "false")  # chat posts without a token
    sys.path.insert(0, str(ROOT / "orchestrator"))
    for mod in _COLLIDING:
        sys.modules.pop(mod, None)
    return importlib.import_module("app")


def _seed_courier(app_mod, cid="crt-1", name="Alex"):
    models = importlib.import_module("models")
    app_mod.S.couriers[cid] = models.Courier(
        id=cid, name=name, location=models.Location(lat=51.54, lng=-0.14, name="depot"),
        phone="+44 700 900001")


@pytest.fixture()
def client(monkeypatch):
    app_mod = _load_app(monkeypatch)
    return TestClient(app_mod.app), app_mod, monkeypatch


def test_ask_strips_reasoning_and_proposes_redirect(client):
    """LLM-on path: a reasoning model wraps its thinking in <think>…</think> and suggests
    a reroute. The answer is returned clean, the reasoning preserved separately, and a
    redirect decision card is proposed for the named courier."""
    c, app_mod, mp = client
    _seed_courier(app_mod, "crt-1", "Alex")
    mp.setattr(app_mod.llm, "chat",
               lambda *a, **k: "<think>Camden Rd is jammed; rerouting saves time.</think>\n"
                               "I'd **reroute Alex** now to dodge the congestion.")
    r = c.post("/agent/ask", json={"question": "should I reroute Alex?"})
    assert r.status_code == 200, r.text
    task = r.json()
    assert "<think>" not in task["answer"]
    assert "reroute Alex" in task["answer"]
    assert "jammed" in task["reasoning"]
    assert task["action"] and task["action"]["type"] == "redirect"
    assert task["action"]["courier_id"] == "crt-1"
    assert task["action"]["endpoint"] == "/couriers/crt-1/redirect"


def test_ask_fallback_still_proposes_action_from_question(client):
    """No-model fallback: the answer is the deterministic summary, but a re-plan is still
    offered because the intent is read from the operator's question text."""
    c, app_mod, mp = client
    mp.setattr(app_mod.llm, "chat", lambda *a, **k: None)
    r = c.post("/agent/ask", json={"question": "re-plan the whole fleet please"})
    assert r.status_code == 200, r.text
    task = r.json()
    assert task["answer"]  # never silent
    assert task["reasoning"] == ""
    assert task["action"] and task["action"]["type"] == "optimize"


def test_ask_plain_question_has_no_action(client):
    c, app_mod, mp = client
    mp.setattr(app_mod.llm, "chat", lambda *a, **k: "Two couriers and three jobs are live.")
    r = c.post("/agent/ask", json={"question": "how many couriers are active?"})
    assert r.status_code == 200, r.text
    task = r.json()
    assert task["answer"]
    assert task.get("action") in (None, {})


def test_worker_answer_path_strips_think_and_proposes(client):
    """The on-box GB10 worker may POST a plain Nemotron answer (with <think>) to
    /agent/answer; the orchestrator strips the reasoning and derives a decision card from
    the original question + answer."""
    c, app_mod, mp = client
    _seed_courier(app_mod, "crt-1", "Alex")
    mp.setattr(app_mod.llm, "chat", lambda *a, **k: None)  # ask uses fallback
    task = c.post("/agent/ask", json={"question": "is Alex on track?"}).json()
    r = c.post("/agent/answer", json={
        "task_id": task["id"],
        "answer": "<think>he's stuck behind a closure</think> Reroute Alex around it.",
    })
    assert r.status_code == 200, r.text
    stored = next(t for t in app_mod.S.agent_tasks if t["id"] == task["id"])
    assert "<think>" not in stored["answer"]
    assert stored["reasoning"] == "he's stuck behind a closure"
    assert stored["action"] and stored["action"]["courier_id"] == "crt-1"
