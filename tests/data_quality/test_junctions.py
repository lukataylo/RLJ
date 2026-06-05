"""Junction DQ — signal model sanity + green-wave advice is a valid SignalAdvice.

Binds to the claims ledger by exact file::function name. Validates the junction
records and the ``green_wave_advice`` output against contracts/schemas.json via
the shared ``validate_entity`` fixture.
"""
from __future__ import annotations

import junctions as junctions_mod
import quality


def test_junctions_valid(validate_entity):
    js = junctions_mod.junctions()

    # ~30 real central-London junctions, ids unique
    assert 25 <= len(js) <= 40, f"implausible junction count {len(js)}"
    assert len({j["id"] for j in js}) == len(js), "duplicate junction ids"

    # shared pipeline validator (bbox, cycle/green/offset sanity, uniqueness)
    quality.validate_junctions(js)

    for j in js:
        assert quality.point_in_bbox(j["lat"], j["lng"]), f"{j['id']} out of bbox"
        assert 60 <= j["cycle_s"] <= 120, f"{j['id']} cycle_s out of range"
        assert 0 < j["green_s"] < j["cycle_s"], f"{j['id']} green_s out of range"
        assert 0 <= j["offset_s"] < j["cycle_s"], f"{j['id']} offset_s out of range"

    # determinism: the bundled signal model is stable across calls
    assert junctions_mod.junctions() == js

    # ---- green_wave_advice returns a valid SignalAdvice ------------------- #
    j = js[0]
    scenarios = [
        # distance_m, now_s, current_speed_mps
        (200.0, 1000.0, 8.0),    # approaching, mid-speed
        (50.0, 0.0, 3.0),        # close, crawling
        (600.0, 137.0, 11.0),    # far, fast
        (0.0, 42.0, 0.0),        # at the stop-line, stopped
        (300.0, 999.0, 0.0),     # stopped some way back
    ]
    for distance_m, now_s, speed in scenarios:
        advice = junctions_mod.green_wave_advice(j, distance_m, now_s, speed)
        # schema-valid SignalAdvice (only `message` is required; extras allowed)
        validate_entity("SignalAdvice", advice)
        assert advice["message"], "advice must carry a human-readable message"
        # our advice carries the optional fields; sanity-check their ranges
        assert advice["target_speed_mps"] > 0
        assert advice["seconds_to_green"] >= 0
        assert 0.0 <= advice["confidence"] <= 1.0

    # a bare message-only advice is also a valid SignalAdvice
    validate_entity("SignalAdvice", {"message": "Maintain speed."})
