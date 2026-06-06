"""Voice stack end-to-end flows — happy + unhappy, fully offline/deterministic.

Covers the driver-assistant agent loop, the spoken-answer composer, the outbound WS
dispatch handler, inbound intake POST, and the ElevenLabs guard. No real keys, no
network, no orchestrator.
"""
from __future__ import annotations

import os

os.environ["LLM_BASE_URL"] = ""  # keyword routing only

import driver_assistant as da  # noqa: E402
import outbound  # noqa: E402
import intake  # noqa: E402
from elevenlabs_client import ElevenLabsClient  # noqa: E402


# ---- driver-assistant agent loop ------------------------------------------------
HAPPY_TOOLS = {
    "bridge_status": lambda bridge="Tower Bridge": {
        "bridge": "Tower Bridge", "open": False, "closed_bridges": ["Tower Bridge"], "any_bridge_closed": True,
    },
    "get_guidance": lambda driver_id: {
        "driver_id": driver_id, "status": "en route", "eta": "2026-06-06T14:25:00Z", "signal_message": None,
    },
    "next_pickup": lambda driver_id: {"driver_id": driver_id, "status": "heading to St Thomas'", "eta": "2026-06-06T14:25:00Z"},
    "reroute_reason": lambda driver_id: {"driver_id": driver_id, "reason": "rerouted around 1 active disruption(s): road_closure", "disruptions": ["road_closure"]},
    "get_signal_advice": lambda driver_id, lat, lng, heading: {"message": "Hold 18 mph for the green.", "target_speed_mps": 8.0},
    "get_congestion": lambda: {"n_cells": 36, "worst_congestion": 0.81, "hotspots": [{"cell": "x"}, {"cell": "y"}]},
}


def test_ask_bridge_question_happy():
    agent = da.DriverAssistant(tools=HAPPY_TOOLS, speak=False)
    out = agent.ask("Is Tower Bridge open?")
    assert out["tools"] == ["bridge_status"]
    assert "closed" in out["answer"].lower()


def test_ask_all_faqs_produce_nonempty_answers():
    agent = da.DriverAssistant(tools=HAPPY_TOOLS, speak=False)
    for q in da.DEMO_QUESTIONS:
        out = agent.ask(q)
        assert out["answer"] and "couldn't find" not in out["answer"]
        assert "can't reach dispatch" not in out["answer"]


def test_ask_unhappy_tool_error_speaks_safe_fallback():
    err_tools = {name: (lambda *a, **k: {"error": "orchestrator unreachable"}) for name in da.VALID_TOOLS}
    agent = da.DriverAssistant(tools=err_tools, speak=False)
    out = agent.ask("How's traffic right now?")
    assert "can't reach dispatch" in out["answer"].lower()


def test_decide_tools_uses_keyword_router_when_no_llm():
    da.LLM_BASE_URL = ""
    assert da.decide_tools("why am I being rerouted?") == ["reroute_reason"]
    assert da.decide_tools("anything unmatched at all") == ["get_guidance"]  # safe default


# ---- spoken-answer composer ----------------------------------------------------
def test_answer_for_each_tool_happy():
    assert "open" in da._answer_for("bridge_status", {"bridge": "Tower Bridge", "open": True}).lower()
    assert "closed" in da._answer_for("bridge_status", {"bridge": "Tower Bridge", "open": False}).lower()
    assert "green" in da._answer_for("get_signal_advice", {"message": "catch the green"}).lower()
    assert da._answer_for("get_congestion", {"n_cells": 0, "worst_congestion": 0.0}).lower().count("light") >= 1


def test_answer_for_error_is_safe():
    assert "can't reach dispatch" in da._answer_for("get_guidance", {"error": "down"}).lower()
    assert "can't reach dispatch" in da._answer_for("bridge_status", {}).lower()


# ---- outbound WS dispatch handler ----------------------------------------------
def test_outbound_places_call_on_voice_notification(monkeypatch):
    calls = []
    monkeypatch.setattr(outbound, "place_call", lambda to, message: calls.append((to, message)))
    outbound._handle({"type": "notification", "payload": {
        "channel": "voice_call", "to": "+44...", "message": "Your ETA is 14:25.", "job_id": "job-7",
    }})
    assert calls == [("+44...", "Your ETA is 14:25.")]


def test_outbound_ignores_non_voice_notifications(monkeypatch):
    calls = []
    monkeypatch.setattr(outbound, "place_call", lambda to, message: calls.append((to, message)))
    outbound._handle({"type": "notification", "payload": {"channel": "ui", "message": "hi"}})
    outbound._handle({"type": "agent_log", "payload": {"level": "info", "message": "narration"}})
    outbound._handle({"type": "plan_updated", "payload": {}})
    assert calls == []  # nothing dialled


def test_place_call_never_raises_without_keys():
    # No ElevenLabs key/agent → console fallback, no exception.
    outbound.place_call("+44123", "test message")


# ---- inbound intake ------------------------------------------------------------
class _FakeResp:
    def __init__(self, payload):
        self._p = payload
    def raise_for_status(self):
        return None
    def json(self):
        return self._p


class _FakeClient:
    def __init__(self, *a, **k):
        pass
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def post(self, url, json=None):
        # echo back an orchestrator-style created job
        return _FakeResp({"id": "job-99", "status": "planned", **(json or {})})


def test_intake_submit_happy(monkeypatch):
    monkeypatch.setattr(intake.httpx, "Client", _FakeClient)
    created = intake.submit("STAT bloods from Somers Town to St Thomas, cold chain")
    assert created and created["id"] == "job-99"
    assert created["priority"] == "stat" and created["cold_chain"] is True


def test_intake_submit_unhappy_orchestrator_down(monkeypatch):
    monkeypatch.setattr(intake, "ORCHESTRATOR_URL", "http://127.0.0.1:59232")
    out = intake.submit("Routine samples from Camden to Guy's")
    assert out is None  # POST failed, but no exception


# ---- ElevenLabs guard ----------------------------------------------------------
def test_elevenlabs_disabled_without_key_is_noop(monkeypatch):
    # Ensure no ambient key (a local voice/.env must not leak into this assertion).
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    c = ElevenLabsClient(api_key="")
    assert c.enabled is False
    assert c.tts("hello") is None          # no network, no file
    assert c.call("+44", "hi") is False    # cannot dial


def test_elevenlabs_enabled_with_key_flag_only():
    c = ElevenLabsClient(api_key="sk_test")
    assert c.enabled is True
    # call() still returns False without an agent id (no dial), without raising
    assert c.call("+44", "hi") is False
