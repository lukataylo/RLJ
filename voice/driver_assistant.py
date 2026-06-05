"""Driver-assistant — a hands-free conversational copilot for delivery drivers.

A driver asks a free-text question ("is Tower Bridge open?", "what speed should I do to
catch the green?"); the assistant decides which orchestrator tool(s) to call
(``driver_tools.py``), calls them, and produces a SHORT spoken-style answer which it
speaks via ElevenLabs (guarded → console fallback).

Tool routing has two paths, the same "fallback ladder" as ``nlu.py``:

1. **Local LLM** (any OpenAI-compatible ``/chat/completions``) with a strict
   tool-routing prompt that emits ``{"tools": [...]}`` — used only when ``LLM_BASE_URL``
   is set and reachable.
2. **Keyword router** (``route_question``) — a pure, no-network function used when there
   is no model. This is what the test pins.

Runs with ZERO credentials: keyword routing + console "speech", and tools that degrade
to ``{"error": ...}`` when the orchestrator is down.

CLI:
  python driver_assistant.py --demo               # ~6 canned questions end to end
  python driver_assistant.py "is tower bridge open?"
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Callable, Optional

import httpx

try:  # load .env if python-dotenv is installed; harmless if not.
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # noqa: BLE001
    pass

import driver_tools
from elevenlabs_client import ElevenLabsClient

# ----------------------------------------------------------------------------- config
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000").rstrip("/")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "nemotron")
LLM_API_KEY = os.getenv("LLM_API_KEY", "ollama")
LLM_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "20"))

DEFAULT_DRIVER_ID = os.getenv("DRIVER_ID", "drv-1")
# A plausible in-bounds location/heading for /signals/advice when the live GPS is unknown
# (near Tower Bridge approach, heading north). Overridable via env for the demo.
DEFAULT_LAT = float(os.getenv("DRIVER_LAT", "51.5045"))
DEFAULT_LNG = float(os.getenv("DRIVER_LNG", "-0.0760"))
DEFAULT_HEADING = float(os.getenv("DRIVER_HEADING", "0"))

VALID_TOOLS = tuple(driver_tools.TOOLS.keys())

# ----------------------------------------------------------------------------- keyword router
# Ordered (keyword-group -> tool). First group with a hit wins, so more specific intents
# (bridge, reroute, pickup) are checked before the broad ones (traffic, guidance).
_ROUTES: list[tuple[str, tuple[str, ...]]] = [
    ("bridge_status",    ("bridge", "tower bridge")),
    ("reroute_reason",   ("rerout", "re-rout", "detour", "diverted", "why am i", "why are we")),
    ("next_pickup",      ("next pickup", "next stop", "next job", "next drop", "where am i going",
                          "pickup", "collection", "collect")),
    ("get_signal_advice",("green", "what speed", "how fast", "signal", "traffic light",
                          "lights", "junction", "wave")),
    ("get_congestion",   ("traffic", "congestion", "congested", "busy", "jam", "hold-up",
                          "hotspot", "how's the road", "how is the road")),
    ("get_guidance",     ("park", "parking", "where can i park", "guidance", "my route",
                          "status", "eta", "how long")),
]


def route_question(text: str) -> list[str]:
    """Map a free-text driver question to the tool name(s) to call. Pure / no network.

    Returns a list (usually one tool). Falls back to ``get_guidance`` — the
    general "what's my situation" tool — when nothing matches.
    """
    low = (text or "").lower()
    for tool, keywords in _ROUTES:
        if any(k in low for k in keywords):
            return [tool]
    return ["get_guidance"]


# ----------------------------------------------------------------------------- LLM router
_ROUTER_SYSTEM_PROMPT = (
    "You route a delivery driver's spoken question to backend tools. Reply with ONE JSON "
    'object and nothing else: {"tools": ["<tool_name>", ...]}.\n'
    "Choose only from these tools:\n"
    "- next_pickup: where the driver is headed next / next stop / ETA to next job.\n"
    "- reroute_reason: why the route changed / why detoured / diverted.\n"
    "- bridge_status: whether a named bridge (e.g. Tower Bridge) is open or closed.\n"
    "- get_signal_advice: green-wave speed advice / catch the next green / what speed.\n"
    "- get_congestion: general traffic / congestion / how busy the roads are.\n"
    "- get_guidance: parking near the destination, overall route status, anything else.\n"
    "Pick the single best tool unless two are clearly needed."
)


def _route_with_llm(text: str) -> Optional[list[str]]:
    """Ask an OpenAI-compatible endpoint to pick tools. Returns list or None on failure."""
    body = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": _ROUTER_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    try:
        with httpx.Client(timeout=LLM_TIMEOUT_S) as client:
            r = client.post(
                f"{LLM_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {LLM_API_KEY}"},
                json=body,
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
        obj = _extract_json(content) or {}
        tools = [t for t in (obj.get("tools") or []) if t in VALID_TOOLS]
        return tools or None
    except Exception as e:  # noqa: BLE001 — fall back to the keyword router
        print(f"[driver] LLM router failed ({type(e).__name__}: {e}) — keyword routing.")
        return None


def _extract_json(content: str) -> Optional[dict[str, Any]]:
    content = (content or "").strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\n?|```$", "", content).strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


def decide_tools(text: str) -> list[str]:
    """Pick tools for a question: LLM router if configured+reachable, else keywords."""
    if LLM_BASE_URL:
        tools = _route_with_llm(text)
        if tools:
            return tools
    return route_question(text)


# ----------------------------------------------------------------------------- the agent
class DriverAssistant:
    """Free-text question → tool calls → short spoken answer.

    ``tools`` is a name→callable registry (defaults to the live ``driver_tools``); the
    demo swaps in a mock registry when the orchestrator is down.
    """

    def __init__(
        self,
        tools: Optional[dict[str, Callable[..., dict[str, Any]]]] = None,
        driver_id: str = DEFAULT_DRIVER_ID,
        speak: bool = True,
    ):
        self.tools = tools or driver_tools.TOOLS
        self.driver_id = driver_id
        self.speak = speak
        self._voice = ElevenLabsClient()

    # -- tool dispatch -------------------------------------------------------
    def _invoke(self, name: str) -> dict[str, Any]:
        fn = self.tools.get(name)
        if fn is None:
            return {"error": f"unknown tool {name}"}
        if name == "get_signal_advice":
            return fn(self.driver_id, DEFAULT_LAT, DEFAULT_LNG, DEFAULT_HEADING)
        if name in ("get_guidance", "next_pickup", "reroute_reason"):
            return fn(self.driver_id)
        return fn()  # get_congestion, bridge_status

    # -- public API ----------------------------------------------------------
    def ask(self, question: str) -> dict[str, Any]:
        """Answer one question. Returns {question, tools, results, answer}."""
        tools = decide_tools(question)
        results = {name: self._invoke(name) for name in tools}
        answer = _compose_answer(tools, results)
        if self.speak:
            self._say(answer)
        return {"question": question, "tools": tools, "results": results, "answer": answer}

    def _say(self, message: str) -> None:
        """Speak via ElevenLabs when a key exists; otherwise console fallback."""
        if self._voice.enabled:
            self._voice.tts(message)  # writes an mp3; safe no-op pattern lives in the client
        print(f"[driver] 🔊 {message}")


# ----------------------------------------------------------------------------- answers
def _compose_answer(tools: list[str], results: dict[str, dict[str, Any]]) -> str:
    """Turn tool result dicts into one short, spoken-style sentence."""
    parts = [_answer_for(name, results.get(name, {})) for name in tools]
    return " ".join(p for p in parts if p) or "Sorry, I couldn't find anything on that."


def _answer_for(tool: str, r: dict[str, Any]) -> str:
    if not r or "error" in r:
        return "I can't reach dispatch right now, so I can't check that — keep to your current route."

    if tool == "next_pickup":
        eta = _eta_phrase(r.get("eta"))
        status = r.get("status") or "on your way"
        return f"Your next pickup: you're {status}{eta}."

    if tool == "reroute_reason":
        return f"Heads up — {r.get('reason', 'no reroute in effect')}."

    if tool == "bridge_status":
        bridge = r.get("bridge", "the bridge")
        if r.get("open"):
            extra = ""
            if r.get("closed_bridges"):
                extra = f" Note: {', '.join(r['closed_bridges'])} closed."
            return f"{bridge} is open.{extra}"
        return f"{bridge} is closed — take an alternative crossing."

    if tool == "get_signal_advice":
        if r.get("message"):
            return r["message"]
        spd = r.get("target_speed_mps")
        if spd is not None:
            return f"Hold about {round(float(spd) * 2.237)} miles per hour to catch the next green."
        return "No green-wave advice available right now; drive to the conditions."

    if tool == "get_congestion":
        worst = r.get("worst_congestion", 0.0)
        n = r.get("n_cells", 0)
        if n == 0 or worst < 0.4:
            return "Traffic's light across the network — clear run."
        level = "heavy" if worst >= 0.7 else "moderate"
        return f"Traffic is {level}; {len(r.get('hotspots', []))} hotspot(s) building — I'll route you round them."

    if tool == "get_guidance":
        eta = _eta_phrase(r.get("eta"))
        status = r.get("status") or "en route"
        sig = f" {r['signal_message']}" if r.get("signal_message") else ""
        return f"You're {status}{eta}. Park at the next drop.{sig}"

    return ""


def _eta_phrase(eta: Any) -> str:
    if not eta:
        return ""
    # Show just the clock part of an ISO-8601 timestamp if we can.
    m = re.search(r"T(\d{2}:\d{2})", str(eta))
    return f", ETA {m.group(1)}" if m else f", ETA {eta}"


# ----------------------------------------------------------------------------- demo
# ~6 canned driver questions covering the FAQ set, for `--demo`.
DEMO_QUESTIONS: list[str] = [
    "Where's my next pickup?",
    "Why am I being rerouted?",
    "Is Tower Bridge open?",
    "Where can I park when I get there?",
    "Should I catch the next green — what speed?",
    "How's traffic right now?",
]


def _orchestrator_up() -> bool:
    try:
        with httpx.Client(timeout=2) as client:
            return client.get(f"{ORCHESTRATOR_URL}/healthz").status_code == 200
    except Exception:  # noqa: BLE001
        return False


def _mock_tools() -> dict[str, Callable[..., dict[str, Any]]]:
    """Canned tool results so `--demo` is meaningful even with no orchestrator."""
    return {
        "get_guidance": lambda driver_id: {
            "driver_id": driver_id, "status": "en route", "eta": "2026-06-05T14:25:00Z",
            "signal_message": "Ease to 18 mph for a green at Tooley Street.",
            "target_speed_mps": 8.0, "pings": 412, "couriers_helped": 7,
        },
        "next_pickup": lambda driver_id: {
            "driver_id": driver_id, "status": "heading to St Thomas' lab",
            "eta": "2026-06-05T14:25:00Z",
        },
        "reroute_reason": lambda driver_id: {
            "driver_id": driver_id,
            "reason": "rerouted around 1 active disruption(s): road_closure",
            "disruptions": ["road_closure"], "status": "en route",
        },
        "bridge_status": lambda bridge="Tower Bridge": {
            "bridge": "Tower Bridge", "open": False,
            "closed_bridges": ["Tower Bridge"], "any_bridge_closed": True,
        },
        "get_signal_advice": lambda driver_id, lat, lng, heading: {
            "message": "Hold 18 miles per hour and you'll hit the next light on green.",
            "target_speed_mps": 8.0, "seconds_to_green": 22, "junction": "Tooley Street",
            "confidence": 0.74,
        },
        "get_congestion": lambda: {
            "n_cells": 36, "worst_congestion": 0.81,
            "hotspots": [
                {"cell": "51.51_-0.09", "lat": 51.51, "lng": -0.09, "congestion": 0.81, "speed_mps": 2.1},
                {"cell": "51.50_-0.12", "lat": 51.50, "lng": -0.12, "congestion": 0.66, "speed_mps": 3.4},
            ],
        },
    }


def run_demo() -> int:
    live = _orchestrator_up()
    if live:
        print(f"[driver] orchestrator up at {ORCHESTRATOR_URL} — using live tools.")
        agent = DriverAssistant()
    else:
        print(f"[driver] orchestrator down at {ORCHESTRATOR_URL} — using mocked tools.")
        agent = DriverAssistant(tools=_mock_tools())
    for q in DEMO_QUESTIONS:
        print(f"\n[driver] ❓ {q}")
        out = agent.ask(q)
        print(f"[driver]    → tools: {out['tools']}")
    return 0


def main(argv: list[str]) -> int:
    args = argv[1:]
    if not args or args[0] == "--demo":
        return run_demo()
    question = " ".join(args)
    out = DriverAssistant().ask(question)
    print(f"[driver] tools used: {out['tools']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
