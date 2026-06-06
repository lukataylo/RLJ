"""NLU intake parser — happy + unhappy flows (deterministic keyword fallback).

No model, no network: LLM_BASE_URL is forced empty so `parse_intake` uses the regex/
gazetteer fallback. Pins that real clinic phrasings map to a valid DeliveryJob and that
garbage/empty input degrades safely.
"""
from __future__ import annotations

import os

import pytest

# Force the keyword fallback (no LLM) before importing the module.
os.environ["LLM_BASE_URL"] = ""
os.environ.setdefault("RLJ_DEMO_DATE", "2026-06-06")

import nlu  # noqa: E402

REQUIRED = {"type", "origin", "destination", "priority", "cold_chain", "raw_text"}


def _valid_loc(loc: dict) -> bool:
    return isinstance(loc, dict) and isinstance(loc.get("lat"), float) and isinstance(loc.get("lng"), float)


def _job(text: str) -> dict:
    nlu.LLM_BASE_URL = ""  # belt-and-braces: keyword path
    return nlu.parse_intake(text)


# ----------------------------------------------------------------- happy flows
def test_stat_cold_chain_pickup_from_to():
    j = _job("STAT INR bloods from Somers Town surgery to St Thomas lab by half ten, cold chain")
    assert REQUIRED <= set(j)
    assert j["type"] == "sample_pickup"
    assert j["priority"] == "stat"
    assert j["cold_chain"] is True
    assert "Somers Town" in j["origin"]["name"]
    assert "St Thomas" in j["destination"]["name"]
    assert j["time_window"]["due_by"] == "2026-06-06T10:30:00Z"  # "half ten"
    assert _valid_loc(j["origin"]) and _valid_loc(j["destination"])
    assert j["raw_text"].startswith("STAT INR")


def test_med_delivery_midday_urgent():
    j = _job("Insulin delivery to a housebound patient in Bow before midday")
    assert j["type"] == "med_delivery"
    assert j["priority"] == "urgent"  # "before"
    assert j["cold_chain"] is False
    assert "Bow" in j["destination"]["name"]
    assert j["time_window"]["due_by"] == "2026-06-06T12:00:00Z"


def test_routine_no_time_window():
    j = _job("Routine histology samples from Camden clinic to Guy's this afternoon")
    assert j["priority"] == "routine"
    # No parseable clock time → no time_window key (orchestrator fills defaults).
    assert "time_window" not in j or not j["time_window"].get("due_by")


def test_clock_time_pm_parsing():
    j = _job("Urgent meds to Whitechapel by 5pm")
    assert j["time_window"]["due_by"] == "2026-06-06T17:00:00Z"


# --------------------------------------------------------------- unhappy flows
def test_empty_text_raises():
    with pytest.raises(ValueError):
        nlu.parse_intake("")
    with pytest.raises(ValueError):
        nlu.parse_intake("   ")


def test_garbage_text_degrades_to_valid_job():
    j = _job("asdfghjkl qwerty zzz")
    assert REQUIRED <= set(j)
    assert j["priority"] == "routine"
    assert j["type"] == "sample_pickup"
    # Unknown places → central-London fallback coords (schema still satisfied).
    assert _valid_loc(j["origin"]) and _valid_loc(j["destination"])


def test_single_named_place_pickup_vs_delivery():
    # delivery with one place → that place is the destination
    d = _job("deliver insulin to Whitechapel")
    assert "Whitechapel" in d["destination"]["name"]
    # pickup with one place → that place is the origin
    p = _job("collect bloods from Whitechapel")
    assert "Whitechapel" in p["origin"]["name"]


def test_never_raises_on_odd_input():
    for t in ["123", "!!!", "from to from to", "STAT", "cold chain only"]:
        j = nlu.parse_intake(t)
        assert REQUIRED <= set(j)
