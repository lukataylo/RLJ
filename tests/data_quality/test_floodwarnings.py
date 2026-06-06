"""Flood warnings DQ tests."""
from __future__ import annotations

import floodwarnings as floodwarnings_mod
import quality


def test_floodwarnings_sane():
    payload = floodwarnings_mod.build_floodwarnings()
    assert len(payload["floods"]) > 0

    disruptions = floodwarnings_mod.flood_disruptions("2026-06-05")
    assert len(disruptions) > 0
    quality.validate_timed_events(disruptions)

    for d in disruptions:
        assert d["kind"] in ("road_closure", "traffic")
        if d["kind"] == "road_closure":
            assert d["intensity"] == 1.0
        else:
            assert d["intensity"] == 0.5
