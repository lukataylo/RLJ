"""Natural-language understanding: raw intake text -> structured DeliveryJob dict.

Two paths, tried in order (the ARCHITECTURE.md "fallback ladder"):

1. Local LLM (Nemotron via Ollama / NemoClaw, any OpenAI-compatible /chat/completions
   endpoint). A strict JSON-output system prompt constrains the model to our schema,
   with a couple of few-shot examples lifted from contracts/samples.
2. Keyword/regex fallback — runs when LLM_BASE_URL is unset or the endpoint is
   unreachable, so the demo survives with no model at all.

The returned dict matches the DeliveryJob entity in contracts/schemas.json. We omit
server-filled fields (id/status/created_at) and let the orchestrator populate them.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

import httpx

# ----------------------------------------------------------------------------- config
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "nemotron")
LLM_API_KEY = os.getenv("LLM_API_KEY", "ollama")
LLM_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "20"))

# A tiny London gazetteer so the keyword fallback can still emit lat/lng (the schema
# requires them). Keys are matched case-insensitively as substrings of the intake text.
# Coordinates mirror the facilities used across contracts/samples.
GAZETTEER: dict[str, dict[str, Any]] = {
    "somers town":    {"lat": 51.5290, "lng": -0.1225, "name": "Somers Town GP surgery"},
    "st thomas":      {"lat": 51.4980, "lng": -0.1188, "name": "St Thomas' Hospital lab", "facility_id": "RJ122"},
    "royal london":   {"lat": 51.5185, "lng": -0.0731, "name": "Royal London pharmacy"},
    "bow":            {"lat": 51.5416, "lng": -0.0042, "name": "Bow housebound patient"},
    "camden":         {"lat": 51.5410, "lng": -0.1430, "name": "Camden clinic"},
    "euston":         {"lat": 51.5246, "lng": -0.1340, "name": "Euston"},
    "london bridge":  {"lat": 51.5079, "lng": -0.0877, "name": "London Bridge"},
    "guy's":          {"lat": 51.5031, "lng": -0.0875, "name": "Guy's Hospital", "facility_id": "RJ701"},
    "ucl":            {"lat": 51.5246, "lng": -0.1340, "name": "UCLH"},
    "whitechapel":    {"lat": 51.5194, "lng": -0.0608, "name": "Whitechapel"},
}
# Used when no gazetteer entry matches — central London so the map still renders.
LONDON_CENTRE = {"lat": 51.5072, "lng": -0.1276, "name": "Central London"}

# ----------------------------------------------------------------------------- prompt
_SYSTEM_PROMPT = """You are the intake parser for a London medical-courier dispatcher.
Convert the clinician's spoken request into ONE JSON object — nothing else, no prose,
no markdown fences. Use exactly this shape:

{
  "type": "sample_pickup" | "med_delivery",
  "origin":      {"lat": <number>, "lng": <number>, "name": <string>},
  "destination": {"lat": <number>, "lng": <number>, "name": <string>},
  "priority": "stat" | "urgent" | "routine",
  "time_window": {"due_by": <ISO-8601 UTC string or null>},
  "cold_chain": <boolean>,
  "raw_text": <the verbatim request>
}

Rules:
- "sample_pickup" = collecting bloods/samples FROM a clinic TO a lab.
  "med_delivery" = taking medication/meds TO a patient or ward.
- priority: "stat" for emergencies (STAT, critical, drop everything),
  "urgent" for same-window/ASAP, otherwise "routine".
- cold_chain true if cold chain / refrigerated / on ice is mentioned.
- Provide best-effort London lat/lng for named places; if unknown use 51.5072,-0.1276.
- due_by: convert clock times to ISO-8601 UTC for today; if none given use null."""

# Few-shot examples derived from the raw_text fields in contracts/samples.
_FEWSHOT: list[tuple[str, dict[str, Any]]] = [
    (
        "Urgent INR bloods from Somers Town surgery to St Thomas lab by half ten, cold chain.",
        {
            "type": "sample_pickup",
            "origin": {"lat": 51.5290, "lng": -0.1225, "name": "Somers Town GP surgery"},
            "destination": {"lat": 51.4980, "lng": -0.1188, "name": "St Thomas' Hospital lab"},
            "priority": "urgent",
            "time_window": {"due_by": "2026-06-06T10:30:00Z"},
            "cold_chain": True,
        },
    ),
    (
        "Insulin delivery to housebound patient in Bow before midday.",
        {
            "type": "med_delivery",
            "origin": {"lat": 51.5185, "lng": -0.0731, "name": "Royal London pharmacy"},
            "destination": {"lat": 51.5416, "lng": -0.0042, "name": "Bow housebound patient"},
            "priority": "urgent",
            "time_window": {"due_by": "2026-06-06T12:00:00Z"},
            "cold_chain": False,
        },
    ),
]


# ----------------------------------------------------------------------------- public API
def parse_intake(text: str) -> dict[str, Any]:
    """Return a DeliveryJob dict for `text`. Never raises — always degrades gracefully."""
    text = (text or "").strip()
    if not text:
        raise ValueError("empty intake text")

    if LLM_BASE_URL:
        job = _parse_with_llm(text)
        if job is not None:
            return _normalise(job, text)
        print("[nlu] LLM unreachable or invalid output — using keyword fallback.")
    else:
        print("[nlu] LLM_BASE_URL unset — using keyword fallback.")

    return _normalise(_parse_with_keywords(text), text)


# ----------------------------------------------------------------------------- LLM path
def _parse_with_llm(text: str) -> Optional[dict[str, Any]]:
    """Call an OpenAI-compatible chat endpoint. Returns a dict or None on any failure."""
    messages: list[dict[str, str]] = [{"role": "system", "content": _SYSTEM_PROMPT}]
    for ex_text, ex_json in _FEWSHOT:
        messages.append({"role": "user", "content": ex_text})
        messages.append({"role": "assistant", "content": json.dumps(ex_json)})
    messages.append({"role": "user", "content": text})

    body = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": 0,
        # Ask for JSON; servers that don't support response_format simply ignore it.
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
        return _extract_json(content)
    except Exception as e:  # noqa: BLE001 — fallback is intentional
        print(f"[nlu] LLM call failed ({type(e).__name__}: {e})")
        return None


def _extract_json(content: str) -> Optional[dict[str, Any]]:
    """Pull the first JSON object out of a model response (tolerates ```fences```)."""
    content = content.strip()
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


# ----------------------------------------------------------------------------- keyword path
def _parse_with_keywords(text: str) -> dict[str, Any]:
    """Deterministic fallback parser — no model, just regex + the gazetteer."""
    low = text.lower()

    # type: medication delivery vs. sample collection.
    med_words = ("insulin", "med", "drug", "deliver", "dose", "vaccine", "prescription")
    job_type = "med_delivery" if any(w in low for w in med_words) else "sample_pickup"

    # priority.
    if any(w in low for w in ("stat", "critical", "emergency", "drop everything")):
        priority = "stat"
    elif any(w in low for w in ("urgent", "asap", "immediately", "now", "before")):
        priority = "urgent"
    else:
        priority = "routine"

    cold_chain = any(w in low for w in ("cold chain", "cold-chain", "refrigerat", "on ice", "frozen"))

    origin, destination = _places_from_text(low, job_type)
    due_by = _time_from_text(low)

    return {
        "type": job_type,
        "origin": origin,
        "destination": destination,
        "priority": priority,
        "time_window": {"due_by": due_by},
        "cold_chain": cold_chain,
    }


def _places_from_text(low: str, job_type: str) -> tuple[dict, dict]:
    """Find origin/destination via 'from X to Y' phrasing, else gazetteer order."""
    hits: list[dict] = []
    seen: set[str] = set()
    for key, loc in GAZETTEER.items():
        idx = low.find(key)
        if idx >= 0 and key not in seen:
            hits.append({"_idx": idx, **loc})
            seen.add(key)
    hits.sort(key=lambda h: h["_idx"])
    places = [{k: v for k, v in h.items() if k != "_idx"} for h in hits]

    if len(places) >= 2:
        return places[0], places[1]
    if len(places) == 1:
        # One named place: for deliveries it's the destination, for pickups the origin.
        if job_type == "med_delivery":
            return dict(LONDON_CENTRE), places[0]
        return places[0], dict(LONDON_CENTRE)
    return dict(LONDON_CENTRE), dict(LONDON_CENTRE)


def _time_from_text(low: str) -> Optional[str]:
    """Best-effort clock-time -> ISO-8601 UTC for the demo date (today)."""
    date = os.getenv("RLJ_DEMO_DATE", "2026-06-06")  # keep demo deterministic with samples
    # word-boundary so "afternoon" doesn't match "noon", etc.
    if re.search(r"\b(midday|noon)\b", low):
        return f"{date}T12:00:00Z"
    if re.search(r"\bmidnight\b", low):
        return f"{date}T00:00:00Z"
    # "half ten" -> 10:30
    half = re.search(r"half (\w+)", low)
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
             "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
    if half and half.group(1) in words:
        return f"{date}T{words[half.group(1)]:02d}:30:00Z"
    # "by 10:30", "before 5pm", "at 9am"
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", low)
    if m and re.search(r"\b(by|before|at|until|til|till)\b", low):
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        ampm = m.group(3)
        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{date}T{hour:02d}:{minute:02d}:00Z"
    return None


# ----------------------------------------------------------------------------- normalise
def _normalise(job: dict[str, Any], raw_text: str) -> dict[str, Any]:
    """Coerce a parsed dict into a valid, minimal DeliveryJob the orchestrator accepts."""
    out: dict[str, Any] = {}
    out["type"] = job.get("type") if job.get("type") in ("sample_pickup", "med_delivery") else "sample_pickup"
    out["origin"] = _loc(job.get("origin"))
    out["destination"] = _loc(job.get("destination"))
    out["priority"] = job.get("priority") if job.get("priority") in ("stat", "urgent", "routine") else "routine"

    tw = job.get("time_window") or {}
    if isinstance(tw, dict) and (tw.get("due_by") or tw.get("ready_at")):
        out["time_window"] = {k: tw.get(k) for k in ("ready_at", "due_by") if tw.get(k)}

    out["cold_chain"] = bool(job.get("cold_chain", False))
    out["raw_text"] = raw_text  # always preserve verbatim intake for traceability
    return out


def _loc(loc: Any) -> dict[str, Any]:
    """Guarantee a Location with numeric lat/lng (schema-required)."""
    if not isinstance(loc, dict):
        return dict(LONDON_CENTRE)
    try:
        out = {"lat": float(loc["lat"]), "lng": float(loc["lng"])}
    except (KeyError, TypeError, ValueError):
        out = dict(LONDON_CENTRE)
    for k in ("name", "facility_id"):
        if loc.get(k):
            out[k] = loc[k]
    return out


if __name__ == "__main__":  # quick manual check: `python nlu.py "STAT bloods ..."`
    import sys
    sample = sys.argv[1] if len(sys.argv) > 1 else \
        "STAT INR bloods from Somers Town surgery to St Thomas lab by half ten, cold chain."
    print(json.dumps(parse_intake(sample), indent=2))
