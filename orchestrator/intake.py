"""Natural-language delivery intake — parse free text into a structured job spec.

Primary path: the provider-agnostic LLM (``llm.complete_json``) with a strict
prompt that EXTRACTS the literal origin and destination place phrases from the
text (free-form — NOT constrained to any list). Depending on the deploy mode
(see ``config``) that LLM is either a LOCAL Ollama/Nemotron model on the GB10 box
or OpenAI in production; when neither is reachable ``complete_json`` returns
``None``. The big offline gazetteer + ``geocode.resolve`` then do the matching, so
arbitrary London places resolve. Fallback (LLM unavailable / bad JSON): a
pure-regex heuristic. Either way the result is ``{origin,destination,priority,
type,cold_chain}`` and origin/destination are later passed to ``geocode.resolve``
(so leaving them as raw phrases is fine).

``parse_delivery`` NEVER raises.
"""
from __future__ import annotations

import re
from typing import Optional

import llm

_VALID_PRIORITY = {"stat", "urgent", "routine"}
_VALID_TYPE = {"sample_pickup", "med_delivery"}


def _heuristic(text: str) -> dict:
    """Offline regex parse. Origin/destination left as raw phrases for the resolver."""
    t = (text or "").strip()
    low = t.lower()

    # priority
    if re.search(r"\bstat\b", low):
        priority = "stat"
    elif re.search(r"\b(urgent|asap|immediately|emergency|now)\b", low):
        priority = "urgent"
    elif re.search(r"\broutine\b", low):
        priority = "routine"
    else:
        priority = "routine"

    # type: anything sample/pathology/specimen/blood-draw -> pickup, else delivery
    if re.search(r"\b(sample|samples|pathology|specimen|specimens|swab|swabs|biopsy)\b", low):
        type_ = "sample_pickup"
    else:
        type_ = "med_delivery"

    # cold chain
    cold_chain = bool(re.search(r"\b(cold|cold[- ]?chain|blood|plasma|refrigerat|frozen|vaccine)\b", low))

    # origin / destination via "from X to Y" (or just "X to Y")
    origin = destination = ""
    m = re.search(r"\bfrom\s+(.*?)\s+to\s+(.+)$", low)
    if not m:
        m = re.search(r"^(.*?)\s+to\s+(.+)$", low)
    if m:
        origin = m.group(1).strip()
        destination = m.group(2).strip()
        # strip a leading verb/clause that crept into the origin ("deliver meds from ...")
        origin = re.split(r"\bfrom\b", origin)[-1].strip()
    else:
        # last resort: just hand the whole text to the resolver as the destination
        destination = low

    # trim trailing clutter ("... by 3pm", "asap", etc.) from the destination tail
    destination = re.split(r"\b(by|before|within|asap|please|now)\b", destination)[0].strip()

    return {"origin": origin, "destination": destination, "priority": priority,
            "type": type_, "cold_chain": cold_chain}


def _coerce(raw: dict) -> dict:
    """Validate/normalise an LLM dict into the canonical shape."""
    out = {
        "origin": str(raw.get("origin") or "").strip(),
        "destination": str(raw.get("destination") or "").strip(),
        "priority": str(raw.get("priority") or "routine").strip().lower(),
        "type": str(raw.get("type") or "med_delivery").strip().lower(),
        "cold_chain": bool(raw.get("cold_chain", False)),
    }
    if out["priority"] not in _VALID_PRIORITY:
        out["priority"] = "routine"
    if out["type"] not in _VALID_TYPE:
        out["type"] = "med_delivery"
    if not out["origin"] or not out["destination"]:
        raise ValueError("LLM returned empty origin/destination")
    return out


def _build_prompt(text: str) -> str:
    """The strict extraction prompt.

    The model EXTRACTS the literal origin/destination phrases as they appear in
    the request — it is NOT given a list to pick from. The downstream gazetteer
    + ``geocode.resolve`` handle matching those phrases to real London places.
    """
    return (
        "You convert a dispatcher's free-text courier request into JSON.\n"
        "Extract the origin and destination EXACTLY as written in the request "
        "(copy the literal place phrase — a name, area, landmark, postcode or "
        "address — do NOT normalise, invent, or pick from any list). The origin "
        "is where the courier collects; the destination is where it is dropped "
        "off.\n\n"
        f'Request: "{text}"\n\n'
        "Return ONLY a JSON object with keys:\n"
        '  origin (string, the pickup place phrase copied from the request),\n'
        '  destination (string, the drop-off place phrase copied from the request),\n'
        '  priority (one of "stat","urgent","routine"),\n'
        '  type (one of "sample_pickup","med_delivery"; samples/pathology = sample_pickup),\n'
        '  cold_chain (boolean; true for blood/plasma/cold-chain/vaccine).'
    )


def parse_delivery(text: str, place_names: Optional[list[str]] = None) -> dict:
    """Parse free text -> {origin,destination,priority,type,cold_chain}. Never raises.

    Uses the provider-agnostic ``llm.complete_json`` (local Ollama or OpenAI per
    deploy mode). When it returns ``None`` (no provider / unreachable) or yields an
    unusable result, falls back to the deterministic offline regex heuristic.

    ``place_names`` is accepted for backwards compatibility (app.py still passes
    it) but ignored: the LLM now extracts free-text phrases and the big gazetteer
    does the matching, so we no longer pin to a constrained list.
    """
    del place_names  # accepted for compat; no longer used
    try:
        raw = llm.complete_json(_build_prompt(text))
        if raw is not None:
            return _coerce(raw)
    except Exception:  # noqa: BLE001 - bad/empty LLM JSON -> deterministic heuristic
        pass
    return _heuristic(text)
