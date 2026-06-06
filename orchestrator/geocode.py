"""Fully-offline London gazetteer + place resolver.

No network, no new dependencies. The gazetteer is the real NHS facilities in
``data/facilities.json`` PLUS an embedded curated seed of well-known London
places (areas, landmarks, bridges, stations, major hospitals) — every entry is a
plausible WGS84 point inside the London bbox (lat 51.28–51.69, lng −0.51–0.33).

``resolve()`` is deliberately liberal: exact (punctuation/case-insensitive,
incl. aliases) → substring → difflib fuzzy. It returns ``{"name","lat","lng"}``
or ``None``. ``place_names()`` returns the canonical names (for the LLM prompt).
"""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher, get_close_matches
from pathlib import Path
from typing import Optional

# repo root = parent of orchestrator/
_ROOT = Path(__file__).resolve().parent.parent
_FACILITIES = _ROOT / "data" / "facilities.json"

# London bounding box (matches the rest of the project).
_BBOX = (51.28, 51.69, -0.51, 0.33)  # lat_min, lat_max, lng_min, lng_max


# Curated seed: well-known London places. (name, lat, lng, [aliases]).
# Coordinates are real/plausible and all within the London bbox.
_SEED: list[tuple[str, float, float, list[str]]] = [
    ("Moorfields Eye Hospital", 51.5266, -0.0901,
     ["Old Street Hospital", "Old Street Eye Hospital", "Moorfields"]),
    ("Southwark Bridge", 51.5080, -0.0941, []),
    ("Old Street", 51.5256, -0.0875, []),
    ("King's Cross", 51.5308, -0.1238, ["Kings Cross", "King's Cross Station"]),
    ("Liverpool Street", 51.5178, -0.0823, ["Liverpool Street Station"]),
    ("Waterloo", 51.5031, -0.1132, ["Waterloo Station"]),
    ("London Bridge", 51.5079, -0.0877, ["London Bridge Station"]),
    ("Tower Bridge", 51.5055, -0.0754, []),
    ("Shoreditch", 51.5265, -0.0784, []),
    ("Camden", 51.5390, -0.1426, ["Camden Town"]),
    ("Whitechapel", 51.5195, -0.0598, []),
    ("Elephant and Castle", 51.4946, -0.1000, ["Elephant & Castle"]),
    ("Angel", 51.5322, -0.1058, ["Angel Islington"]),
    ("Bank", 51.5134, -0.0886, []),
    ("Holborn", 51.5174, -0.1200, []),
    ("Aldgate", 51.5143, -0.0755, []),
    ("Clerkenwell", 51.5230, -0.1050, []),
    ("Islington", 51.5362, -0.1033, []),
    ("Hackney", 51.5450, -0.0553, []),
    ("Bermondsey", 51.4979, -0.0637, []),
    ("Vauxhall", 51.4857, -0.1232, []),
    ("Brixton", 51.4613, -0.1156, []),
    ("Peckham", 51.4740, -0.0695, []),
    ("Greenwich", 51.4810, -0.0052, []),
    ("Canary Wharf", 51.5054, -0.0235, []),
    ("Stratford", 51.5416, -0.0042, []),
    ("Paddington", 51.5154, -0.1755, ["Paddington Station"]),
    ("Victoria", 51.4952, -0.1441, ["Victoria Station"]),
    ("Westminster", 51.4995, -0.1248, []),
    ("Marylebone", 51.5225, -0.1631, []),
    ("Euston", 51.5282, -0.1337, ["Euston Station"]),
    ("Farringdon", 51.5203, -0.1053, []),
    ("Oxford Circus", 51.5152, -0.1418, []),
    ("Piccadilly Circus", 51.5101, -0.1340, []),
    ("Soho", 51.5138, -0.1316, []),
    ("Covent Garden", 51.5117, -0.1240, []),
    ("Bethnal Green", 51.5270, -0.0549, []),
    ("Bow", 51.5274, -0.0203, []),
    ("Deptford", 51.4790, -0.0265, []),
    ("Lewisham", 51.4657, -0.0117, []),
    ("Clapham", 51.4620, -0.1380, []),
    ("Wandsworth", 51.4571, -0.1910, []),
    ("Battersea", 51.4750, -0.1530, []),
    ("Fulham", 51.4800, -0.1950, []),
    ("Hammersmith", 51.4920, -0.2230, []),
    ("Notting Hill", 51.5090, -0.1960, []),
    ("Highbury", 51.5520, -0.1030, []),
]


def _norm(s: str) -> str:
    """Lowercase, drop apostrophes, fold remaining punctuation to spaces, collapse."""
    s = (s or "").lower()
    s = s.replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _in_bbox(lat: float, lng: float) -> bool:
    a, b, c, d = _BBOX
    return a <= lat <= b and c <= lng <= d


def _load_gazetteer() -> list[dict]:
    """Build the gazetteer once: facilities.json (primary) + curated seed."""
    entries: list[dict] = []
    seen: set[str] = set()

    def _add(name: str, lat: float, lng: float, aliases: list[str]):
        if not name or lat is None or lng is None:
            return
        if not _in_bbox(lat, lng):
            return
        key = _norm(name)
        if key in seen:
            return
        seen.add(key)
        entries.append({"name": name, "lat": float(lat), "lng": float(lng),
                        "norm": key, "aliases": [_norm(a) for a in aliases if a]})

    try:
        facilities = json.loads(_FACILITIES.read_text())
    except Exception:  # noqa: BLE001 - missing/corrupt file: seed still works offline
        facilities = []
    for f in facilities if isinstance(facilities, list) else []:
        _add(f.get("name", ""), f.get("lat"), f.get("lng"), [])

    for name, lat, lng, aliases in _SEED:
        _add(name, lat, lng, aliases)

    return entries


_GAZETTEER = _load_gazetteer()
# norm-or-alias -> entry, for O(1) exact/alias lookup.
_EXACT: dict[str, dict] = {}
for _e in _GAZETTEER:
    _EXACT.setdefault(_e["norm"], _e)
    for _a in _e["aliases"]:
        _EXACT.setdefault(_a, _e)


def gazetteer_size() -> int:
    return len(_GAZETTEER)


def place_names() -> list[str]:
    """All canonical place names (for the LLM prompt)."""
    return [e["name"] for e in _GAZETTEER]


def _result(e: dict) -> dict:
    return {"name": e["name"], "lat": e["lat"], "lng": e["lng"]}


def suggest(query: str, n: int = 3) -> list[str]:
    """Closest canonical names to a (possibly unresolvable) query — for error hints."""
    q = _norm(query)
    if not q:
        return []
    names = place_names()
    scored = sorted(names, key=lambda nm: SequenceMatcher(None, q, _norm(nm)).ratio(),
                    reverse=True)
    return scored[:n]


def resolve(query: str) -> Optional[dict]:
    """Resolve a free-text place to ``{"name","lat","lng"}`` or ``None``.

    Order: exact/alias (case & punctuation insensitive) → substring (either
    direction, ranked by similarity) → difflib fuzzy.
    """
    q = _norm(query)
    if not q:
        return None

    # 1) exact (incl. aliases)
    if q in _EXACT:
        return _result(_EXACT[q])

    # 2) substring, either direction, ranked by similarity
    cands: list[tuple[float, dict]] = []
    for e in _GAZETTEER:
        for key in (e["norm"], *e["aliases"]):
            if not key:
                continue
            if q in key or (len(key) >= 3 and key in q):
                cands.append((SequenceMatcher(None, q, key).ratio(), e))
                break
    if cands:
        cands.sort(key=lambda t: t[0], reverse=True)
        return _result(cands[0][1])

    # 3) fuzzy over names + aliases
    lookup: dict[str, dict] = {}
    for e in _GAZETTEER:
        lookup[e["norm"]] = e
        for a in e["aliases"]:
            lookup[a] = e
    hits = get_close_matches(q, list(lookup.keys()), n=1, cutoff=0.6)
    if hits:
        return _result(lookup[hits[0]])
    return None
