"""Offline, deterministic tests for the natural-language delivery intake.

Covers the gazetteer resolver (exact + fuzzy), the heuristic parse fallback (with
Ollama patched to raise so there is no network), and the POST /intake endpoint via
a FastAPI TestClient. orchestrator/ is on sys.path via tests/conftest.py; the app is
loaded with an isolated import cache to avoid the orchestrator/routing ``app``/``models``
module-name collision (same trick as tests/completeness).
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]

_COLLIDING = (
    "app", "models", "seed", "greedy", "congestion", "geocode", "nl_intake",
    "solver", "solver_baseline", "solver_ortools", "solver_aco", "solver_ls",
    "traveltime",
)


def _load(modname: str):
    # Force orchestrator/ to the FRONT of sys.path so its `app`/`models` shadow routing/'s
    # (conftest puts both on the path; routing would otherwise win the bare `import app`).
    sys.path.insert(0, str(ROOT / "orchestrator"))
    for mod in _COLLIDING:
        sys.modules.pop(mod, None)
    return importlib.import_module(modname)


# --------------------------------------------------------------------------- geocode
def test_gazetteer_loaded_and_in_bbox():
    geocode = _load("geocode")
    assert geocode.gazetteer_size() >= 50
    for name in geocode.place_names():
        r = geocode.resolve(name)
        assert r is not None
        assert 51.28 <= r["lat"] <= 51.69 and -0.51 <= r["lng"] <= 0.33


def test_resolve_exact():
    geocode = _load("geocode")
    r = geocode.resolve("Guy's Hospital")
    assert r and r["name"] == "Guy's Hospital"
    r2 = geocode.resolve("moorfields eye hospital")  # case-insensitive
    assert r2 and r2["name"] == "Moorfields Eye Hospital"


def test_resolve_fuzzy_and_substring():
    geocode = _load("geocode")
    # "guys" -> Guy's Hospital
    r = geocode.resolve("guys")
    assert r and r["name"] == "Guy's Hospital"
    # "Old Street hospital" -> a hospital near Old Street (Moorfields)
    r2 = geocode.resolve("Old Street hospital")
    assert r2 and r2["name"] == "Moorfields Eye Hospital"
    # "Southwark Bridge hospital" -> resolves (to the Southwark Bridge area), in bbox
    r3 = geocode.resolve("Southwark Bridge hospital")
    assert r3 and 51.28 <= r3["lat"] <= 51.69 and -0.51 <= r3["lng"] <= 0.33


def test_resolve_unknown_returns_none():
    geocode = _load("geocode")
    assert geocode.resolve("zzz nowhere planet xyzzy") is None
    assert geocode.resolve("") is None


# --------------------------------------------------------------- type-aware resolve
def _entry(geocode, name, lat, lng, type_, aliases=()):
    """A gazetteer entry in the module's in-memory shape."""
    return {
        "name": name, "lat": lat, "lng": lng,
        "norm": geocode._norm(name), "type": type_,
        "aliases": [geocode._norm(a) for a in aliases],
    }


def _install(geocode, monkeypatch, entries):
    """Swap in a tiny synthetic gazetteer so type-ranking is deterministic even
    when the big data/gazetteer.json is absent on a dev box."""
    exact = {}
    for e in entries:
        exact.setdefault(e["norm"], e)
        for a in e["aliases"]:
            exact.setdefault(a, e)
    monkeypatch.setattr(geocode, "_GAZETTEER", entries)
    monkeypatch.setattr(geocode, "_EXACT", exact)
    monkeypatch.setattr(geocode, "_FUZZY_KEYS", list(exact.keys()))


def test_health_types_constant():
    geocode = _load("geocode")
    assert {"hospital", "lab", "clinic", "gp", "pharmacy", "health"} <= set(geocode.HEALTH_TYPES)


def test_resolve_result_includes_type():
    geocode = _load("geocode")
    r = geocode.resolve("Guy's Hospital")
    assert r and "type" in r
    # facilities.json tags Guy's as a hospital
    assert r["type"] == "hospital"


def test_resolve_prefer_types_picks_hospital_over_samename_place(monkeypatch):
    # Synthetic reproduction of the real bug: "Whittington" -> housing estate.
    geocode = _load("geocode")
    _install(geocode, monkeypatch, [
        _entry(geocode, "Whittington Estate", 51.5651, -0.1424, "place"),
        _entry(geocode, "Whittington Hospital", 51.5658, -0.1390, "hospital"),
    ])
    # Default (no preference): pure name-similarity favors the SHORTER same-named
    # place -> this is exactly the mis-resolution we are fixing.
    assert geocode.resolve("whittington")["name"] == "Whittington Estate"
    # Type-aware: the hospital wins.
    r = geocode.resolve("whittington", prefer_types=geocode.HEALTH_TYPES)
    assert r["name"] == "Whittington Hospital"
    assert r["type"] == "hospital"


def test_resolve_prefer_types_main_hospital_beats_subclinic(monkeypatch):
    # Among health entries, prefer the shorter/closer exact-ish hospital name over
    # a longer sub-clinic (the "UCLH main vs Westmoreland Street" shape).
    geocode = _load("geocode")
    _install(geocode, monkeypatch, [
        _entry(geocode, "University College Hospital at Westmoreland Street",
               51.5196, -0.1497, "health"),
        _entry(geocode, "University College Hospital", 51.5248, -0.1365, "health"),
        _entry(geocode, "University College Estate", 51.5230, -0.1300, "place"),
    ])
    # Exact-ish full name -> the main hospital, not the longer sub-clinic.
    r = geocode.resolve("university college hospital", prefer_types=geocode.HEALTH_TYPES)
    assert r["name"] == "University College Hospital"
    # Partial name still prefers a health entry over the same-named place.
    r2 = geocode.resolve("university college", prefer_types=geocode.HEALTH_TYPES)
    assert r2["type"] in geocode.HEALTH_TYPES


def test_resolve_prefer_types_is_soft_no_health_match(monkeypatch):
    # When nothing health-y matches, still resolve to the best place (e.g. Dalston).
    geocode = _load("geocode")
    _install(geocode, monkeypatch, [
        _entry(geocode, "Dalston", 51.5432, -0.0760, "place"),
        _entry(geocode, "Kingsland", 51.5460, -0.0760, "place"),
    ])
    r = geocode.resolve("dalston", prefer_types=geocode.HEALTH_TYPES)
    assert r and r["name"] == "Dalston"


def test_resolve_prefer_types_none_preserves_behavior(monkeypatch):
    # prefer_types=None must reproduce the un-biased result (back-compat).
    geocode = _load("geocode")
    _install(geocode, monkeypatch, [
        _entry(geocode, "Whittington Estate", 51.5651, -0.1424, "place"),
        _entry(geocode, "Whittington Hospital", 51.5658, -0.1390, "hospital"),
    ])
    none_res = geocode.resolve("whittington")
    explicit = geocode.resolve("whittington", prefer_types=None)
    assert none_res == explicit
    assert none_res["name"] == "Whittington Estate"  # un-biased default


def test_resolve_prefer_types_real_facilities():
    # Real data path (facilities.json is always present): a hospital from the
    # curated facilities must beat any same-named generic POI when health-preferred.
    geocode = _load("geocode")
    r = geocode.resolve("whittington", prefer_types=geocode.HEALTH_TYPES)
    assert r is not None
    assert r["type"] in geocode.HEALTH_TYPES
    assert "hospital" in r["name"].lower()


# --------------------------------------------------------------------------- intake parse
def test_parse_delivery_heuristic_fallback(monkeypatch):
    geocode = _load("geocode")
    intake = _load("nl_intake")

    # No LLM provider reachable -> complete_json returns None -> heuristic path.
    monkeypatch.setattr(intake.llm, "complete_json", lambda *a, **k: None)

    parsed = intake.parse_delivery("urgent meds from Guy's to Moorfields",
                                   geocode.place_names())
    assert parsed["priority"] == "urgent"
    assert parsed["type"] == "med_delivery"

    origin = geocode.resolve(parsed["origin"])
    dest = geocode.resolve(parsed["destination"])
    assert origin and origin["name"] == "Guy's Hospital"
    assert dest and dest["name"] == "Moorfields Eye Hospital"


def test_parse_delivery_extracts_freetext_phrases(monkeypatch):
    # Arbitrary facility names (NOT in the curated seed) — the LLM extracts the
    # literal phrases and the gazetteer (facilities.json) resolves them. Ollama
    # is forced down so the deterministic regex heuristic runs offline.
    geocode = _load("geocode")
    intake = _load("nl_intake")
    monkeypatch.setattr(intake.llm, "complete_json", lambda *a, **k: None)

    parsed = intake.parse_delivery(
        "urgent sample from Spitalfields Practice to Victoria Medical Centre")
    assert parsed["priority"] == "urgent"
    assert parsed["type"] == "sample_pickup"
    assert parsed["origin"]
    assert parsed["destination"]

    origin = geocode.resolve(parsed["origin"])
    dest = geocode.resolve(parsed["destination"])
    assert origin and origin["name"] == "Spitalfields Practice"
    assert dest and dest["name"] == "Victoria Medical Centre"


def test_parse_delivery_ignores_place_names_arg(monkeypatch):
    # place_names is accepted for compat but ignored; passing junk must not break.
    intake = _load("nl_intake")
    monkeypatch.setattr(intake.llm, "complete_json", lambda *a, **k: None)
    parsed = intake.parse_delivery("routine meds from Bank to Angel",
                                   ["totally", "irrelevant", "list"])
    assert parsed["origin"] and parsed["destination"]


def test_parse_delivery_multidrop(monkeypatch):
    # MULTI-DROP: one pickup (Guy's), two drops (St Thomas' + Moorfields).
    geocode = _load("geocode")
    intake = _load("nl_intake")
    monkeypatch.setattr(intake.llm, "complete_json", lambda *a, **k: None)

    parsed = intake.parse_delivery(
        "deliver blood from Guy's to St Thomas' and also Moorfields")
    assert parsed["cold_chain"] is True
    # origin resolves to Guy's
    origin = geocode.resolve(parsed["origin"])
    assert origin and origin["name"] == "Guy's Hospital"
    # exactly two destinations, resolving to St Thomas' + Moorfields
    assert len(parsed["destinations"]) == 2
    assert parsed["destination"] == parsed["destinations"][0]  # back-compat key
    resolved = [geocode.resolve(d) for d in parsed["destinations"]]
    names = [r["name"] for r in resolved if r]
    assert "St Thomas' Hospital" in names
    assert "Moorfields Eye Hospital" in names


def test_parse_delivery_single_still_one_destination(monkeypatch):
    # Single-drop request -> destinations length 1, destination == destinations[0].
    intake = _load("nl_intake")
    monkeypatch.setattr(intake.llm, "complete_json", lambda *a, **k: None)
    parsed = intake.parse_delivery("urgent meds from Guy's to Moorfields")
    assert len(parsed["destinations"]) == 1
    assert parsed["destination"] == parsed["destinations"][0]


def test_parse_delivery_sample_and_cold(monkeypatch):
    intake = _load("nl_intake")
    monkeypatch.setattr(intake.llm, "complete_json", lambda *a, **k: None)
    parsed = intake.parse_delivery("stat blood sample from Whitechapel to King's Cross", [])
    assert parsed["priority"] == "stat"
    assert parsed["type"] == "sample_pickup"
    assert parsed["cold_chain"] is True


def test_parse_delivery_uses_llm_when_available(monkeypatch):
    # Prod-style: an LLM provider returns good JSON -> parse_delivery uses it (no heuristic).
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("LOCAL", raising=False)
    intake = _load("nl_intake")
    monkeypatch.setattr(intake.llm, "complete_json", lambda *a, **k: {
        "origin": "Guy's Hospital", "destination": "Moorfields Eye Hospital",
        "priority": "stat", "type": "sample_pickup", "cold_chain": True,
    })
    parsed = intake.parse_delivery("grab the bloods over to the eye place")
    assert parsed["origin"] == "Guy's Hospital"
    assert parsed["destination"] == "Moorfields Eye Hospital"
    assert parsed["priority"] == "stat"
    assert parsed["type"] == "sample_pickup"
    assert parsed["cold_chain"] is True


# --------------------------------------------------------------------------- endpoint
@pytest.fixture()
def client(monkeypatch):
    # Load the app first (this imports the `intake` module app actually uses), THEN patch
    # that exact module's Ollama call so /intake is deterministic + offline (regex path).
    app_mod = _load("app")
    intake = sys.modules["nl_intake"]
    monkeypatch.setattr(intake.llm, "complete_json", lambda *a, **k: None)
    return TestClient(app_mod.app)


def test_intake_endpoint_creates_job(client):
    r = client.post("/intake",
                    json={"text": "deliver from Southwark Bridge hospital to Old Street hospital"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True, body
    jobs = body["jobs"]
    assert len(jobs) == 1
    job = jobs[0]
    assert job["id"]
    for end in ("origin", "destination"):
        loc = job[end]
        assert 51.28 <= loc["lat"] <= 51.69 and -0.51 <= loc["lng"] <= 0.33
    assert body["resolved"]["destinations"][0]["name"] == "Moorfields Eye Hospital"
    assert body["order"]  # optimised visiting order is present
    assert "→" in body["message"]


def test_intake_endpoint_multidrop(client):
    # One pickup, two drops -> two jobs created, optimised order returned.
    r = client.post("/intake",
                    json={"text": "deliver blood from Guy's to St Thomas' and also Moorfields"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True, body
    assert len(body["jobs"]) == 2
    assert len(body["resolved"]["destinations"]) == 2
    # order starts at the origin (pickup) and lists all stops
    assert body["order"]
    assert body["order"][0] == "Guy's Hospital"
    assert len(body["order"]) == 3  # origin + 2 drops
    # offline-safe: Valhalla unreachable in tests -> polyline falls back to []
    assert body["route"] == []
    assert "route optimized" in body["message"]


def test_intake_endpoint_unresolved(client):
    r = client.post("/intake", json={"text": "from qwerty noplace to asdfgh nowhere"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "suggestions" in body
