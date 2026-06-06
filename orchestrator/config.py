"""Deploy-mode configuration — one backend, two environments.

The SAME orchestrator code runs in two places, selected by the ``LOCAL`` env flag:

* **LOCAL** (``LOCAL=true``, developer laptop / GB10 DGX Spark box): use the on-box
  backends — Valhalla for routing geometry, a local Ollama/Nemotron model for the
  LLM, and the on-box agent worker answers ``/agent/ask``.
* **PRODUCTION** (``LOCAL`` unset/false, pulsego.org on Railway, no DGX access): no
  Valhalla (haversine fallback handles geometry), the LLM is OpenAI
  (``OPENAI_API_KEY``), and — since there is no on-box worker — the orchestrator
  itself answers ``/agent/ask`` via OpenAI.

Small and dependency-free: everything reads from the environment at call time so
tests can monkeypatch ``os.environ`` (or set/delete vars) without re-importing.
"""
from __future__ import annotations

import os

_TRUTHY = {"1", "true", "yes", "on"}


def is_local() -> bool:
    """True iff the ``LOCAL`` env var is truthy (case-insensitive)."""
    return os.getenv("LOCAL", "").strip().lower() in _TRUTHY


def ollama_url() -> str:
    """Base URL of the local Ollama/Nemotron server."""
    return os.getenv("OLLAMA", "http://localhost:11434")


def model() -> str:
    """The local (Ollama) model name."""
    return os.getenv("MODEL", "nemotron")


def openai_key() -> str:
    """The OpenAI API key (empty string if unset)."""
    return os.getenv("OPENAI_API_KEY", "")


def openai_model() -> str:
    """The OpenAI chat model name."""
    return os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def valhalla_enabled() -> bool:
    """Informational: Valhalla is only usable on the local box with a URL set."""
    return is_local() and bool(os.getenv("VALHALLA_URL", "").strip())


def llm_available() -> bool:
    """True iff some LLM provider is reachable: local Ollama, or an OpenAI key."""
    return is_local() or bool(openai_key())
