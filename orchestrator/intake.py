"""Natural-language delivery intake — parse free text into a structured job spec.

Primary path: the provider-agnostic LLM (``llm.complete_json``) with a strict
prompt that EXTRACTS the literal origin and a LIST of destination place phrases
from the text (free-form — NOT constrained to any list). Depending on the deploy
mode (see ``config``) that LLM is either a LOCAL Ollama/Nemotron model on the GB10
box or OpenAI in production; when neither is reachable ``complete_json`` returns
``None``. The big offline gazetteer + ``geocode.resolve`` then do the matching, so
arbitrary London places resolve. Fallback (LLM unavailable / bad JSON): a
pure-regex heuristic.

The result is ``{origin, destinations:[...], destination, priority, type,
cold_chain}`` — MULTI-DROP aware: one pickup (``origin``) and one or more drops
(``destinations``). ``destination`` (= ``destinations[0]``) is kept for backward
compatibility. Origin/destinations are later passed to ``geocode.resolve`` (so
leaving them as raw phrases is fine).

``parse_delivery`` NEVER raises.
"""
from __future__ import annotations

import re
from typing import Optional

import llm

_VALID_PRIORITY = {"stat", "urgent", "routine"}
_VALID_TYPE = {"sample_pickup", "med_delivery"}


# Splits a destination tail into multiple drops. Order matters: " and also "
# must win over the bare " and " (it contains it), so it is listed first.
_DEST_SPLIT = re.compile(r"\s+and also\s+|\s+and\s+|\s*,\s*|\s+then\s+")
# Trailing clutter to drop from a destination phrase ("... by 3pm", "asap", ...).
_CLUTTER = re.compile(r"\b(by|before|within|asap|please|now)\b")


def _split_destinations(tail: str) -> list[str]:
    """Split a destination tail into ≥1 drop phrases (free-form, for the resolver).

    Strips trailing clutter, then splits on " and also "/" and "/", "/" then ".
    Always returns at least one entry (possibly an empty string).
    """
    tail = _CLUTTER.split(tail or "", maxsplit=1)[0].strip()
    parts = [p.strip() for p in _DEST_SPLIT.split(tail) if p and p.strip()]
    return parts or [tail]


def _heuristic(text: str) -> dict:
    """Offline regex parse. Origin/destinations left as raw phrases for the resolver."""
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

    # origin / destination-tail via "from X to Y" (or just "X to Y")
    origin = ""
    tail = ""
    m = re.search(r"\bfrom\s+(.*?)\s+to\s+(.+)$", low)
    if not m:
        m = re.search(r"^(.*?)\s+to\s+(.+)$", low)
    if m:
        origin = m.group(1).strip()
        tail = m.group(2).strip()
        # strip a leading verb/clause that crept into the origin ("deliver meds from ...")
        origin = re.split(r"\bfrom\b", origin)[-1].strip()
    else:
        # last resort: just hand the whole text to the resolver as the destination
        tail = low

    # MULTI-DROP: split the tail into one or more drop phrases.
    destinations = _split_destinations(tail)

    return {"origin": origin, "destinations": destinations,
            "destination": destinations[0], "priority": priority,
            "type": type_, "cold_chain": cold_chain}


def _coerce(raw: dict) -> dict:
    """Validate/normalise an LLM dict into the canonical multi-drop shape.

    Accepts either ``destinations`` (a list — the new shape) or a single
    ``destination`` string (legacy / single-drop), folding both into a list.
    """
    origin = str(raw.get("origin") or "").strip()

    destinations: list[str] = []
    raw_dests = raw.get("destinations")
    if isinstance(raw_dests, list):
        destinations = [str(d).strip() for d in raw_dests if str(d).strip()]
    single = str(raw.get("destination") or "").strip()
    if not destinations and single:
        destinations = [single]

    priority = str(raw.get("priority") or "routine").strip().lower()
    type_ = str(raw.get("type") or "med_delivery").strip().lower()
    if priority not in _VALID_PRIORITY:
        priority = "routine"
    if type_ not in _VALID_TYPE:
        type_ = "med_delivery"
    if not origin or not destinations:
        raise ValueError("LLM returned empty origin/destinations")
    return {"origin": origin, "destinations": destinations,
            "destination": destinations[0], "priority": priority,
            "type": type_, "cold_chain": bool(raw.get("cold_chain", False))}


def _build_prompt(text: str) -> str:
    """The strict extraction prompt.

    The model EXTRACTS the literal origin phrase and a LIST of destination phrases
    as they appear in the request — it is NOT given a list to pick from. The
    downstream gazetteer + ``geocode.resolve`` handle matching those phrases to
    real London places. The request may name several drop-offs ("... to A and
    also B", "deliver to A, B and C") — capture EACH one.
    """
    return (
        "You convert a dispatcher's free-text courier request into JSON.\n"
        "Extract the single origin and a LIST of destinations EXACTLY as written "
        "in the request (copy each literal place phrase — a name, area, landmark, "
        "postcode or address — do NOT normalise, invent, or pick from any list). "
        "The origin is the one place where the courier collects; the destinations "
        "are every place it is dropped off (there may be one or several).\n\n"
        f'Request: "{text}"\n\n'
        "Return ONLY a JSON object with keys:\n"
        '  origin (string, the single pickup place phrase copied from the request),\n'
        '  destinations (array of strings, each drop-off place phrase copied from '
        'the request; at least one),\n'
        '  priority (one of "stat","urgent","routine"),\n'
        '  type (one of "sample_pickup","med_delivery"; samples/pathology = sample_pickup),\n'
        '  cold_chain (boolean; true for blood/plasma/cold-chain/vaccine).'
    )


def parse_delivery(text: str, place_names: Optional[list[str]] = None) -> dict:
    """Parse free text -> {origin,destinations,destination,priority,type,cold_chain}.

    MULTI-DROP: ``destinations`` is a list of one or more drop phrases;
    ``destination`` (= ``destinations[0]``) is kept for backward compat. Never raises.

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
