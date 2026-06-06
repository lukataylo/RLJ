"""Fully-offline London gazetteer + place resolver.

No network, no new dependencies. The gazetteer is, in priority order:

  1. a large optional gazetteer file ``data/gazetteer.json`` (an array of
     ``{name,lat,lng,type,source}`` — typically 10k+ arbitrary London places),
     loaded only when present, and
  2. the real NHS facilities in ``data/facilities.json``, plus
  3. an embedded curated seed of well-known London places (areas, landmarks,
     bridges, stations, major hospitals).

Facilities + the seed are always loaded so resolution works even when the big
gazetteer file is absent on a dev box. Every entry is a plausible WGS84 point
inside the London bbox (lat 51.28–51.69, lng −0.51–0.33); entries are de-duped by
normalized name (facilities/seed win, so their curated coords are preserved).

``resolve()`` is deliberately liberal: exact (punctuation/case-insensitive,
incl. aliases) → substring → difflib fuzzy. It returns
``{"name","lat","lng","type"}`` or ``None``, and stays O(1) on the common exact
path even at 10k+ entries. ``place_names()`` returns the canonical names (now
potentially huge — do NOT feed it to the LLM; intake extracts free-text phrases
instead).

``resolve()`` is also **type-aware**: callers can pass ``prefer_types`` (e.g.
``HEALTH_TYPES``) to softly bias selection toward medical facilities, so
"Whittington" resolves to *Whittington Hospital* rather than the same-named
*Whittington Estate*. Each entry carries its ``type`` (facilities use their
facility type like ``hospital``/``lab``; ``_SEED`` areas default to ``place``;
``gazetteer.json`` entries keep their ``type`` field — ``health``/``place``/…).
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
_GAZETTEER_FILE = _ROOT / "data" / "gazetteer.json"

# London bounding box (matches the rest of the project).
_BBOX = (51.28, 51.69, -0.51, 0.33)  # lat_min, lat_max, lng_min, lng_max

# Medical/health facility types. Callers pass this as ``prefer_types`` so that a
# query that matches both a clinical facility and a same-named generic POI
# resolves to the facility. ``facilities.json`` uses the specific types
# (hospital/lab/gp/pharmacy/clinic); the big ``gazetteer.json`` tags health POIs
# with the umbrella ``health`` type.
HEALTH_TYPES: frozenset[str] = frozenset(
    {"hospital", "lab", "clinic", "gp", "pharmacy", "health"}
)

# How much a type-preferred candidate is boosted in the blended ranking score.
# Tuned so a strong type match overtakes an *equally/slightly-more* similar
# non-preferred name (e.g. "Whittington Hospital" beats "Whittington Estate",
# Δsim ≈ 0.05) while staying a SOFT preference: a clearly better non-preferred
# name (Δsim > _TYPE_BONUS) still wins, so "Dalston" still resolves to the place.
_TYPE_BONUS = 0.15


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


def _load_json(path: Path) -> list:
    """Read a JSON array from ``path``; [] on missing/corrupt (stays offline-safe)."""
    try:
        data = json.loads(path.read_text())
    except Exception:  # noqa: BLE001 - missing/corrupt file: other sources still work
        return []
    return data if isinstance(data, list) else []


def _load_gazetteer() -> list[dict]:
    """Build the gazetteer once.

    Sources, all optional but loaded in a fixed dedup-priority order (first to
    claim a normalized name wins, so curated coords are preserved):
      1. facilities.json — real NHS facilities (curated, win),
      2. the embedded curated _SEED (win),
      3. gazetteer.json — the big arbitrary-London file (10k+; fills the rest).
    """
    entries: list[dict] = []
    seen: set[str] = set()

    def _add(name: str, lat, lng, aliases: list[str], type_: str):
        if not name or lat is None or lng is None:
            return
        try:
            lat, lng = float(lat), float(lng)
        except (TypeError, ValueError):
            return
        if not _in_bbox(lat, lng):
            return
        key = _norm(name)
        if not key or key in seen:
            return
        seen.add(key)
        entries.append({"name": name, "lat": lat, "lng": lng,
                        "norm": key, "type": (type_ or "place"),
                        "aliases": [_norm(a) for a in aliases if a]})

    # 1) facilities.json (primary, curated) — keep the facility's own type
    #    (hospital/lab/gp/pharmacy/clinic).
    for f in _load_json(_FACILITIES):
        if isinstance(f, dict):
            _add(f.get("name", ""), f.get("lat"), f.get("lng"), [],
                 f.get("type", "place"))

    # 2) curated seed (well-known landmarks/areas/stations) — default "place".
    for name, lat, lng, aliases in _SEED:
        _add(name, lat, lng, aliases, "place")

    # 3) big optional gazetteer file: {name,lat,lng,type,source} — keep its type
    #    (health/place/transport/…).
    for g in _load_json(_GAZETTEER_FILE):
        if isinstance(g, dict):
            _add(g.get("name", ""), g.get("lat"), g.get("lng"), [],
                 g.get("type", "place"))

    return entries


_GAZETTEER = _load_gazetteer()
# norm-or-alias -> entry, for O(1) exact/alias lookup.
_EXACT: dict[str, dict] = {}
for _e in _GAZETTEER:
    _EXACT.setdefault(_e["norm"], _e)
    for _a in _e["aliases"]:
        _EXACT.setdefault(_a, _e)
# Precomputed once so the fuzzy fallback doesn't rebuild a 10k+ index per call.
_FUZZY_KEYS: list[str] = list(_EXACT.keys())


def gazetteer_size() -> int:
    return len(_GAZETTEER)


def place_names() -> list[str]:
    """All canonical place names (for the LLM prompt)."""
    return [e["name"] for e in _GAZETTEER]


def _result(e: dict) -> dict:
    return {"name": e["name"], "lat": e["lat"], "lng": e["lng"],
            "type": e.get("type", "place")}


def _type_bonus(e: dict, prefer_types: Optional[set]) -> float:
    """The soft ranking boost for an entry whose ``type`` is preferred."""
    if prefer_types and e.get("type") in prefer_types:
        return _TYPE_BONUS
    return 0.0


def _best_key_sim(q: str, e: dict) -> float:
    """Best name-similarity of ``q`` against the entry's norm + any aliases."""
    best = 0.0
    for key in (e["norm"], *e["aliases"]):
        if not key:
            continue
        r = SequenceMatcher(None, q, key).ratio()
        if r > best:
            best = r
    return best


# Generic tokens stripped before matching hospital names, so the DISTINCTIVE part
# drives the match (otherwise the shared "hospital" suffix inflates similarity across
# every hospital and "X hospital" matches an arbitrary one).
_GENERIC_TOKENS = {"hospital", "hospitals", "the", "nhs", "trust", "university",
                   "centre", "center", "general", "royal", "st", "saint"}


def _distinct(norm: str) -> str:
    return " ".join(t for t in norm.split() if t not in _GENERIC_TOKENS)


def _is_hospital(e: dict) -> bool:
    """A hospital by type tag OR by name — OSM tags many hospitals as generic
    'health', so trust the name too."""
    return e.get("type") == "hospital" or "hospital" in e["norm"]


def _resolve_hospital(q: str) -> Optional[dict]:
    """Best hospital match for ``q`` (norm), or None — "hospital wins on conflict".

    A query that plausibly names a hospital resolves to the hospital even when a
    same-named area/estate/station or non-hospital health POI also matches
    (e.g. "homerton" → *Homerton University Hospital*; "old street hospital" →
    *Moorfields* via its alias). Matching is on the DISTINCTIVE tokens (generic
    words like "hospital"/"university" stripped). Unrelated queries (e.g. "Dalston")
    match no hospital and fall through to normal resolution.
    """
    qd = _distinct(q)
    best: Optional[tuple[float, dict]] = None
    for e in _GAZETTEER:
        if not _is_hospital(e):
            continue
        if q == e["norm"] or q in e["aliases"]:
            return e
        substring = False
        sim = 0.0
        for key in (e["norm"], *e["aliases"]):
            if not key:
                continue
            kd = _distinct(key)
            if qd and kd and (qd in kd or kd in qd):
                substring = True
            r = SequenceMatcher(None, qd or q, kd or key).ratio()
            if r > sim:
                sim = r
        if substring or sim >= 0.8:
            score = sim + (0.6 if substring else 0.0)
            if best is None or score > best[0]:
                best = (score, e)
    return best[1] if best else None


def suggest(query: str, n: int = 3) -> list[str]:
    """Closest canonical names to a (possibly unresolvable) query — for error hints."""
    q = _norm(query)
    if not q:
        return []
    names = place_names()
    scored = sorted(names, key=lambda nm: SequenceMatcher(None, q, _norm(nm)).ratio(),
                    reverse=True)
    return scored[:n]


def resolve(query: str, *, prefer_types: Optional[set] = None) -> Optional[dict]:
    """Resolve a free-text place to ``{"name","lat","lng","type"}`` or ``None``.

    Order: exact/alias (case & punctuation insensitive) → substring (either
    direction) → difflib fuzzy. Within the substring and fuzzy tiers the result
    is chosen by a single blended score = name-similarity + a type bonus.

    ``prefer_types`` is an optional, **soft** preference: candidates whose
    ``type`` is in the set get a ``_TYPE_BONUS`` boost, so among otherwise
    comparable names a medical facility wins (pass :data:`HEALTH_TYPES`). It only
    breaks near-ties — a clearly better non-preferred name still wins, so a query
    with no health match (e.g. "Dalston") resolves to the best place exactly as
    before. ``prefer_types=None`` reproduces the original behavior.
    """
    q = _norm(query)
    if not q:
        return None

    # 0) hospital-first: in a medical context, a plausible hospital match wins over
    #    a same-named area/estate/station or sub-clinic — even over an exact non-
    #    hospital match. Only fires when "hospital" is a preferred type.
    if prefer_types and "hospital" in prefer_types:
        h = _resolve_hospital(q)
        if h is not None:
            return _result(h)

    # 1) exact (incl. aliases) — the strongest possible signal; the user named
    #    this exact place, so honor it regardless of any type preference.
    if q in _EXACT:
        return _result(_EXACT[q])

    # 2) substring, either direction, ranked by similarity + type bonus.
    #    With prefer_types=None the score is just the matched-key ratio, i.e.
    #    identical to the original ranking (back-compat).
    cands: list[tuple[float, dict]] = []
    for e in _GAZETTEER:
        for key in (e["norm"], *e["aliases"]):
            if not key:
                continue
            if q in key or (len(key) >= 3 and key in q):
                score = SequenceMatcher(None, q, key).ratio() + _type_bonus(e, prefer_types)
                cands.append((score, e))
                break
    if cands:
        cands.sort(key=lambda t: t[0], reverse=True)
        return _result(cands[0][1])

    # 3) fuzzy over the precomputed norm/alias keys.
    if not prefer_types:
        hits = get_close_matches(q, _FUZZY_KEYS, n=1, cutoff=0.6)
        if hits:
            return _result(_EXACT[hits[0]])
        return None
    # Type-aware fuzzy: take a few close matches, then re-rank by blended score
    # (best key similarity + type bonus) so a preferred facility can win.
    hits = get_close_matches(q, _FUZZY_KEYS, n=5, cutoff=0.6)
    if not hits:
        return None
    seen: set[str] = set()
    best: Optional[tuple[float, dict]] = None
    for h in hits:
        e = _EXACT[h]
        if e["norm"] in seen:
            continue
        seen.add(e["norm"])
        score = _best_key_sim(q, e) + _type_bonus(e, prefer_types)
        if best is None or score > best[0]:
            best = (score, e)
    return _result(best[1]) if best else None
