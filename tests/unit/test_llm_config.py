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
    "app", "models", "seed", "greedy", "congestion", "geocode", "intake", "nl_intake",
    "solver", "solver_baseline", "solver_ortools", "solver_aco", "solver_ls",
    "traveltime",
)


@pytest.fixture(autouse=True)
def _reset_provider():
    """Each test starts on the default provider; the openai-path tests opt in explicitly."""
    config.set_provider("nemotron")
    yield
    config.set_provider("nemotron")


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
    for k in (
        "OLLAMA", "MODEL", "OPENAI_API_KEY", "OPENAI_MODEL", "LLM_API_KEY",
        "LLM_MODEL", "LLM_BASE_URL", "VALHALLA_URL", "LOCAL",
    ):
        monkeypatch.delenv(k, raising=False)
    assert config.ollama_url() == "http://localhost:11434"
    assert config.model() == "nemotron"
    # provider-aware: check the OpenAI provider's defaults explicitly, then restore.
    config.set_provider("openai")
    assert config.openai_key() == ""
    assert config.openai_model() == "gpt-4o-mini"
    assert config.openai_base_url() == "https://api.openai.com/v1"
    config.set_provider("nemotron")
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
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert config.llm_available() is False
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    assert config.llm_available() is True
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("LOCAL", "true")
    assert config.llm_available() is True


def test_openai_compatible_env_aliases(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "nebius-key")
    monkeypatch.setenv("LLM_MODEL", "nemotron-test")
    monkeypatch.setenv("LLM_BASE_URL", "https://inference.example/v1/")
    assert config.openai_key() == "nebius-key"
    assert config.openai_model() == "nemotron-test"
    assert config.openai_base_url() == "https://inference.example/v1"
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


# ------------------------------------------------------- Ollama model-name resolution
@pytest.mark.parametrize("desired,served,expected", [
    # exact tag wins
    ("nemotron3:33b", ["nemotron3:33b", "nemotron:latest"], "nemotron3:33b"),
    # bare "nemotron" -> nemotron:latest when present
    ("nemotron", ["nemotron3:33b", "nemotron:latest"], "nemotron:latest"),
    # bare "nemotron" reaches nemotron3:33b when :latest is absent (the key case)
    ("nemotron", ["nemotron3:33b"], "nemotron3:33b"),
    # "nemotron3:33b" requested but only nemotron:latest served -> token overlap
    ("nemotron3:33b", ["nemotron:latest"], "nemotron:latest"),
    # same base, non-latest tag
    ("nemotron3", ["nemotron3:33b"], "nemotron3:33b"),
    # no models served -> unchanged (let Ollama decide / fail to offline fallback)
    ("nemotron", [], "nemotron"),
    # nothing nemotron-ish -> unchanged
    ("nemotron", ["llama3:8b", "qwen:7b"], "nemotron"),
])
def test_match_model_interchangeable(desired, served, expected):
    assert llm._match_model(desired, served) == expected


def _install_fake_httpx_with_tags(monkeypatch, served, gen_body):
    """Fake httpx.Client supporting GET /api/tags (model list) and POST /api/generate."""
    cap: dict = {}

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, **k):
            cap["get_url"] = url
            return _FakeResp({"models": [{"name": n} for n in served]})

        def post(self, url, json=None, headers=None):
            cap["json"] = json
            return _FakeResp(gen_body)

    monkeypatch.setattr(llm.httpx, "Client", _Client)
    return cap


def test_resolve_model_reaches_served_nemotron(monkeypatch):
    """End-to-end: configured MODEL=nemotron resolves to the served nemotron3:33b tag."""
    monkeypatch.setenv("LOCAL", "true")
    monkeypatch.setenv("OLLAMA", "http://gb10:11434")
    monkeypatch.setenv("MODEL", "nemotron")
    llm._MODEL_CACHE.clear()
    cap = _install_fake_httpx_with_tags(
        monkeypatch, ["nemotron3:33b"], {"response": json.dumps({"ok": True})})
    out = llm.complete_json("parse")
    assert out == {"ok": True}
    assert cap["get_url"] == "http://gb10:11434/api/tags"
    assert cap["json"]["model"] == "nemotron3:33b"   # reached the served tag, not "nemotron"
    llm._MODEL_CACHE.clear()


def test_resolve_model_falls_back_when_tags_unreachable(monkeypatch):
    """If /api/tags can't be read, the configured name is used verbatim (old behaviour)."""
    monkeypatch.setenv("MODEL", "nemotron")
    monkeypatch.setenv("OLLAMA", "http://gb10:11434")
    llm._MODEL_CACHE.clear()

    class _Boom:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            raise RuntimeError("tags down")

    monkeypatch.setattr(llm.httpx, "Client", _Boom)
    assert llm.resolve_model() == "nemotron"
    llm._MODEL_CACHE.clear()


# --------------------------------------------------------------------------- OpenAI (prod)
def _openai_body(content):
    return {"choices": [{"message": {"content": content}}]}


def test_complete_json_openai(monkeypatch):
    monkeypatch.delenv("LOCAL", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    config.set_provider("openai")
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
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    config.set_provider("openai")
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

    ans, reasoning = asyncio.run(app_mod._answer_question("status?"))
    assert ans == "Two couriers are en route."
    assert reasoning == ""  # no <think> markers in this answer

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
    # No model available -> deterministic keyword-aware fleet fallback (chat is never silent).
    monkeypatch.delenv("LOCAL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app_mod = _load_app()
    monkeypatch.setattr(app_mod.llm, "chat", lambda *a, **k: None)

    ans, _ = asyncio.run(app_mod._answer_question("anything at all?"))
    assert ans and "NemoClaw is online" in ans


# ------------------------------------------------------------ /healthz LLM provider
# The brand pill shows the on-prem DGX Spark indicator only when the model runs
# locally, and hides it when a cloud model is active. /healthz exposes which it is.
def _health(app_mod):
    from fastapi.testclient import TestClient
    return TestClient(app_mod.app).get("/healthz").json()


def test_healthz_reports_local_model(monkeypatch):
    # config reads env at call time, so set the flags AFTER import (importing app may
    # load voice/.env). LOCAL wins regardless of any cloud key present.
    app_mod = _load_app()
    monkeypatch.setenv("LOCAL", "true")
    body = _health(app_mod)
    assert body["llm_provider"] == "local"
    assert body["local_model"] is True
    assert body["cloud_model"] is False  # DGX indicator stays SHOWN


def test_healthz_reports_cloud_model(monkeypatch):
    app_mod = _load_app()
    monkeypatch.delenv("LOCAL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    body = _health(app_mod)
    assert body["llm_provider"] == "cloud"
    assert body["local_model"] is False
    assert body["cloud_model"] is True  # DGX indicator gets HIDDEN


def test_healthz_no_provider_is_not_cloud(monkeypatch):
    # No model configured at all: treated as on-prem, so the indicator shows. Clear the
    # keys AFTER import to undo any voice/.env injection.
    app_mod = _load_app()
    monkeypatch.delenv("LOCAL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    body = _health(app_mod)
    assert body["llm_provider"] == "none"
    assert body["cloud_model"] is False
