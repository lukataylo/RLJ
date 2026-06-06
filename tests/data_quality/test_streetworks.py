"""Streetworks DQ tests."""
from __future__ import annotations

import quality
import streetworks as streetworks_mod


def test_streetworks_sane():
    payload = streetworks_mod.build_streetworks()
    assert len(payload["streetworks"]) > 0

    disruptions = streetworks_mod.streetwork_disruptions("2026-06-05")
    assert len(disruptions) > 0
    quality.validate_timed_events(disruptions)

    for d in disruptions:
        assert d["kind"] == "road_closure"
        assert d["intensity"] == 1.0
