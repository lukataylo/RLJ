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
    "app", "models", "seed", "greedy", "congestion", "geocode", "intake",
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


# --------------------------------------------------------------------------- intake parse
def test_parse_delivery_heuristic_fallback(monkeypatch):
    geocode = _load("geocode")
    intake = _load("intake")

    def _boom(*a, **k):  # force the offline heuristic path
        raise RuntimeError("ollama down")

    monkeypatch.setattr(intake, "_ask_ollama", _boom)

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
    intake = _load("intake")
    monkeypatch.setattr(intake, "_ask_ollama",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))

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
    intake = _load("intake")
    monkeypatch.setattr(intake, "_ask_ollama",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    parsed = intake.parse_delivery("routine meds from Bank to Angel",
                                   ["totally", "irrelevant", "list"])
    assert parsed["origin"] and parsed["destination"]


def test_parse_delivery_sample_and_cold(monkeypatch):
    intake = _load("intake")
    monkeypatch.setattr(intake, "_ask_ollama",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    parsed = intake.parse_delivery("stat blood sample from Whitechapel to King's Cross", [])
    assert parsed["priority"] == "stat"
    assert parsed["type"] == "sample_pickup"
    assert parsed["cold_chain"] is True


# --------------------------------------------------------------------------- endpoint
@pytest.fixture()
def client(monkeypatch):
    # Load the app first (this imports the `intake` module app actually uses), THEN patch
    # that exact module's Ollama call so /intake is deterministic + offline (regex path).
    app_mod = _load("app")
    intake = sys.modules["intake"]
    monkeypatch.setattr(intake, "_ask_ollama",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    return TestClient(app_mod.app)


def test_intake_endpoint_creates_job(client):
    r = client.post("/intake",
                    json={"text": "deliver from Southwark Bridge hospital to Old Street hospital"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True, body
    job = body["job"]
    assert job["id"]
    for end in ("origin", "destination"):
        loc = job[end]
        assert 51.28 <= loc["lat"] <= 51.69 and -0.51 <= loc["lng"] <= 0.33
    assert body["resolved"]["destination"]["name"] == "Moorfields Eye Hospital"
    assert "→" in body["message"]


def test_intake_endpoint_unresolved(client):
    r = client.post("/intake", json={"text": "from qwerty noplace to asdfgh nowhere"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "suggestions" in body
