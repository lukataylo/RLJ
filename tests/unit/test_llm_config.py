"""Offline, deterministic tests for the deploy-mode flag + provider-agnostic LLM.

Covers ``config`` (the LOCAL/prod flag + helpers) and ``llm`` (Ollama vs OpenAI
provider selection, offline fallback to None). All network is monkeypatched: no
real HTTP, no provider, no keys required. orchestrator/ is on sys.path via
tests/conftest.py (and has no name collision with routing/ for these modules).
"""
from __future__ import annotations

import asyncio
import importlib
import json
import sys
from pathlib import Path

import config
import llm
import pytest

ROOT = Path(__file__).resolve().parents[2]

_COLLIDING = (
    "app", "models", "seed", "greedy", "congestion", "geocode", "intake",
    "solver", "solver_baseline", "solver_ortools", "solver_aco", "solver_ls",
    "traveltime",
)


def _load_app():
    """Load orchestrator/app.py with an isolated import cache (its app/models would
    otherwise collide with routing/'s — same trick as test_intake_geocode.py)."""
    sys.path.insert(0, str(ROOT / "orchestrator"))
    for mod in _COLLIDING:
        sys.modules.pop(mod, None)
    return importlib.import_module("app")


# --------------------------------------------------------------------------- config
@pytest.mark.parametrize("val,expected", [
    ("1", True), ("true", True), ("TRUE", True), ("Yes", True), ("on", True),
    ("0", False), ("false", False), ("no", False), ("", False), ("maybe", False),
])
def test_is_local_truthiness(monkeypatch, val, expected):
    monkeypatch.setenv("LOCAL", val)
    assert config.is_local() is expected


def test_is_local_unset(monkeypatch):
    monkeypatch.delenv("LOCAL", raising=False)
    assert config.is_local() is False


def test_config_helpers_defaults(monkeypatch):
    for k in ("OLLAMA", "MODEL", "OPENAI_API_KEY", "OPENAI_MODEL", "VALHALLA_URL", "LOCAL"):
        monkeypatch.delenv(k, raising=False)
    assert config.ollama_url() == "http://localhost:11434"
    assert config.model() == "nemotron"
    assert config.openai_key() == ""
    assert config.openai_model() == "gpt-4o-mini"
    assert config.valhalla_enabled() is False
    assert config.llm_available() is False


def test_valhalla_enabled_requires_local_and_url(monkeypatch):
    monkeypatch.setenv("VALHALLA_URL", "http://localhost:8002")
    monkeypatch.delenv("LOCAL", raising=False)
    assert config.valhalla_enabled() is False  # URL set but not local
    monkeypatch.setenv("LOCAL", "true")
    assert config.valhalla_enabled() is True


def test_llm_available(monkeypatch):
    monkeypatch.delenv("LOCAL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert config.llm_available() is False
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    assert config.llm_available() is True
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("LOCAL", "true")
    assert config.llm_available() is True


# --------------------------------------------------------------------------- httpx fake
class _FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


def _install_fake_httpx(monkeypatch, responder):
    """Patch httpx.Client so llm.* makes no real network calls. ``responder(url)``
    returns the JSON body. Captures the last post() call into the returned dict."""
    captured: dict = {}

    class _FakeClient:
        def __init__(self, *a, **k):
            captured["timeout"] = k.get("timeout")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _FakeResp(responder(url))

    monkeypatch.setattr(llm.httpx, "Client", _FakeClient)
    return captured


# --------------------------------------------------------------------------- no provider
def test_complete_json_no_provider_returns_none(monkeypatch):
    monkeypatch.delenv("LOCAL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # If it tried the network this would explode; assert it stays offline.
    monkeypatch.setattr(llm.httpx, "Client",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("network!")))
    assert llm.complete_json("hi") is None


def test_chat_no_provider_returns_none(monkeypatch):
    monkeypatch.delenv("LOCAL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(llm.httpx, "Client",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("network!")))
    assert llm.chat("hi") is None


def test_helpers_never_raise_on_bad_response(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.delenv("LOCAL", raising=False)
    _install_fake_httpx(monkeypatch, lambda url: {"bogus": "shape"})
    assert llm.complete_json("hi") is None
    assert llm.chat("hi") is None


# --------------------------------------------------------------------------- LOCAL/Ollama
def test_complete_json_local_hits_ollama(monkeypatch):
    monkeypatch.setenv("LOCAL", "true")
    monkeypatch.setenv("OLLAMA", "http://gb10:11434")
    monkeypatch.setenv("MODEL", "nemotron-test")
    cap = _install_fake_httpx(
        monkeypatch,
        lambda url: {"response": json.dumps({"origin": "A", "destination": "B"})})
    out = llm.complete_json("parse this")
    assert out == {"origin": "A", "destination": "B"}
    assert cap["url"] == "http://gb10:11434/api/generate"
    assert cap["json"]["model"] == "nemotron-test"
    assert cap["json"]["format"] == "json"
    assert cap["json"]["stream"] is False
    assert cap["headers"] is None  # no auth header for Ollama


def test_chat_local_hits_ollama(monkeypatch):
    monkeypatch.setenv("LOCAL", "true")
    monkeypatch.setenv("OLLAMA", "http://gb10:11434")
    cap = _install_fake_httpx(monkeypatch, lambda url: {"response": "all good"})
    out = llm.chat("how is the fleet?", system="ctx")
    assert out == "all good"
    assert cap["url"] == "http://gb10:11434/api/generate"
    assert "ctx" in cap["json"]["prompt"]


# --------------------------------------------------------------------------- OpenAI (prod)
def _openai_body(content):
    return {"choices": [{"message": {"content": content}}]}


def test_complete_json_openai(monkeypatch):
    monkeypatch.delenv("LOCAL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    cap = _install_fake_httpx(
        monkeypatch, lambda url: _openai_body(json.dumps({"answer": 42})))
    out = llm.complete_json("give me json")
    assert out == {"answer": 42}
    assert cap["url"] == "https://api.openai.com/v1/chat/completions"
    assert cap["headers"]["Authorization"] == "Bearer sk-secret"
    assert cap["json"]["response_format"] == {"type": "json_object"}
    assert cap["json"]["model"] == "gpt-4o-mini"
    # system msg instructs JSON-only
    assert any(m["role"] == "system" for m in cap["json"]["messages"])


def test_chat_openai(monkeypatch):
    monkeypatch.delenv("LOCAL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    cap = _install_fake_httpx(monkeypatch, lambda url: _openai_body("fleet looks healthy"))
    out = llm.chat("status?", system="you are a dispatcher")
    assert out == "fleet looks healthy"
    assert cap["url"] == "https://api.openai.com/v1/chat/completions"
    assert cap["headers"]["Authorization"] == "Bearer sk-secret"
    roles = [m["role"] for m in cap["json"]["messages"]]
    assert roles == ["system", "user"]


def test_local_takes_precedence_over_openai(monkeypatch):
    # Both configured -> LOCAL wins (Ollama URL), prod path not taken.
    monkeypatch.setenv("LOCAL", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.setenv("OLLAMA", "http://gb10:11434")
    cap = _install_fake_httpx(monkeypatch, lambda url: {"response": "from ollama"})
    assert llm.chat("hi") == "from ollama"
    assert cap["url"].startswith("http://gb10:11434")


# --------------------------------------------------------------------------- /agent/ask prod
def _capture_emits(app_mod, monkeypatch):
    events: list[tuple[str, object]] = []

    async def _fake_emit(type_, payload):
        events.append((type_, payload))

    monkeypatch.setattr(app_mod.HUB, "emit", _fake_emit)
    return events


def test_agent_ask_answers_via_llm(monkeypatch):
    # The orchestrator answers /agent/ask itself via the LLM seam (OpenAI/Ollama).
    monkeypatch.delenv("LOCAL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    app_mod = _load_app()
    events = _capture_emits(app_mod, monkeypatch)
    monkeypatch.setattr(app_mod.llm, "chat", lambda *a, **k: "Two couriers are en route.")

    ans = asyncio.run(app_mod._answer_question("status?"))
    assert ans == "Two couriers are en route."

    app_mod.S.agent_tasks.append({"id": "task-77", "question": "status?",
                                  "ts": "now", "status": "pending"})
    asyncio.run(app_mod._record_agent_answer("task-77", ans))

    types = [t for t, _ in events]
    assert "agent_answer" in types
    answer_payload = next(p for t, p in events if t == "agent_answer")
    assert answer_payload == {"task_id": "task-77", "answer": "Two couriers are en route."}
    task = next(t for t in app_mod.S.agent_tasks if t["id"] == "task-77")
    assert task["status"] == "answered"
    assert any(t == "agent_log" and p.get("source") == "nemotron" for t, p in events)


def test_agent_ask_falls_back_when_no_llm(monkeypatch):
    # No model available -> deterministic fleet-summary fallback (chat is never silent).
    monkeypatch.delenv("LOCAL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app_mod = _load_app()
    monkeypatch.setattr(app_mod.llm, "chat", lambda *a, **k: None)

    ans = asyncio.run(app_mod._answer_question("anything at all?"))
    assert ans and "Local read" in ans
