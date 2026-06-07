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
import time
from typing import Optional

import httpx

import config

# --- Ollama model-name resolution --------------------------------------------------
# The box may serve any nemotron tag (``nemotron:latest``, ``nemotron3:33b``, …) and the
# operator uses those names interchangeably. Rather than 404 when the configured name
# isn't the exact served tag, we resolve ``config.model()`` against Ollama's live
# ``/api/tags`` list and pick the best-matching nemotron variant. Cached briefly so we
# don't re-query on every generate; on any failure we fall back to the configured name
# verbatim (preserving the old behaviour and the offline-safe contract).
_MODEL_CACHE: dict[tuple[str, str], tuple[float, str]] = {}
_MODEL_TTL_S = 300.0


def _match_model(desired: str, available: list[str]) -> str:
    """Pick the served Ollama tag that best matches ``desired``.

    Treats ``nemotron``, ``nemotron:latest`` and ``nemotron3:33b`` as interchangeable so a
    request reaches whichever nemotron variant is actually pulled. Resolution order:
    exact tag -> ``<base>:latest`` -> any tag with the same base -> base-token overlap
    (``nemotron`` <-> ``nemotron3``) -> the desired name unchanged.
    """
    if not available or desired in available:
        return desired
    base = desired.split(":", 1)[0].lower()
    for n in available:                                   # <base>:latest
        if n.lower() == f"{base}:latest":
            return n
    for n in available:                                   # same base, any tag
        if n.split(":", 1)[0].lower() == base:
            return n
    for n in available:                                   # token overlap (nemotron/nemotron3)
        nb = n.split(":", 1)[0].lower()
        if base and (base in nb or nb in base):
            return n
    return desired


def resolve_model(*, timeout: float = 3.0) -> str:
    """Configured Ollama model name resolved to a tag Ollama actually serves."""
    desired = config.model()
    url = config.ollama_url()
    key = (url, desired)
    now = time.monotonic()
    cached = _MODEL_CACHE.get(key)
    if cached and now - cached[0] < _MODEL_TTL_S:
        return cached[1]
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(f"{url}/api/tags")
            r.raise_for_status()
            available = [m.get("name", "") for m in r.json().get("models", [])]
        resolved = _match_model(desired, [n for n in available if n])
        _MODEL_CACHE[key] = (now, resolved)
        return resolved
    except Exception:  # noqa: BLE001 - tags unreachable -> use the configured name as-is
        return desired


def complete_json(prompt: str, *, timeout: float = 20.0) -> Optional[dict]:
    """Ask the active LLM for a JSON object. Returns the parsed dict, or None on any failure."""
    try:
        if config.is_local():
            payload = {
                "model": resolve_model(),
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
    try:
        if config.is_local():
            full = f"{system}\n\n{prompt}" if system else prompt
            payload = {
                "model": resolve_model(),
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
