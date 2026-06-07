"""Provider-agnostic LLM helper with an offline fallback.

Two entry points, both selecting the provider the same way (see ``config``):

* ``config.is_local()``  -> local **Ollama/Nemotron** (``{ollama_url()}/api/generate``)
* else ``config.openai_key()`` -> **OpenAI** chat completions
* else -> ``None`` (no provider; callers fall back to deterministic/offline paths)

No new pip dependencies — uses ``httpx`` (already a dependency). Every network call
is wrapped in try/except so these helpers NEVER raise: they return ``None`` (or an
empty parse) on any failure, keeping the orchestrator deterministic and offline-safe
by default.
"""
from __future__ import annotations

import json
from typing import Optional

import httpx

import config

def complete_json(prompt: str, *, timeout: float = 20.0) -> Optional[dict]:
    """Ask the active LLM for a JSON object. Returns the parsed dict, or None on any failure."""
    if not config.llm_enabled_runtime():
        return None
    try:
        if config.is_local():
            payload = {
                "model": config.model(),
                "prompt": prompt,
                "stream": False,
                "format": "json",
            }
            with httpx.Client(timeout=timeout) as client:
                r = client.post(f"{config.ollama_url()}/api/generate", json=payload)
                r.raise_for_status()
                body = r.json()
            raw = json.loads(body["response"])
            return raw if isinstance(raw, dict) else None

        key = config.openai_key()
        if key:
            payload = {
                "model": config.openai_model(),
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": "Return only JSON."},
                    {"role": "user", "content": prompt},
                ],
            }
            headers = {"Authorization": f"Bearer {key}"}
            with httpx.Client(timeout=timeout) as client:
                r = client.post(
                    f"{config.openai_base_url()}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                r.raise_for_status()
                body = r.json()
            content = body["choices"][0]["message"]["content"]
            raw = json.loads(content)
            return raw if isinstance(raw, dict) else None
    except Exception:  # noqa: BLE001 - provider down / bad JSON -> deterministic fallback
        return None
    return None


def chat(prompt: str, *, system: Optional[str] = None, timeout: float = 30.0) -> Optional[str]:
    """Free-text answer from the active LLM. Returns the text, or None on failure / no provider."""
    if not config.llm_enabled_runtime():
        return None  # operator turned the model off → caller uses deterministic fallback
    try:
        if config.is_local():
            full = f"{system}\n\n{prompt}" if system else prompt
            payload = {
                "model": config.model(),
                "prompt": full,
                "stream": False,
            }
            with httpx.Client(timeout=timeout) as client:
                r = client.post(f"{config.ollama_url()}/api/generate", json=payload)
                r.raise_for_status()
                body = r.json()
            text = (body.get("response") or "").strip()
            return text or None

        key = config.openai_key()
        if key:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            payload = {"model": config.openai_model(), "messages": messages}
            headers = {"Authorization": f"Bearer {key}"}
            with httpx.Client(timeout=timeout) as client:
                r = client.post(
                    f"{config.openai_base_url()}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                r.raise_for_status()
                body = r.json()
            text = (body["choices"][0]["message"]["content"] or "").strip()
            return text or None
    except Exception:  # noqa: BLE001 - provider down -> caller handles None
        return None
    return None
