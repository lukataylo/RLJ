"""Streetworks DQ tests."""
from __future__ import annotations

import integrations
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
        # TimedEvent provenance must stay in the valid vocab even though the manifest
        # dataset source is now "live-with-fallback".
        assert d["source"] in quality.VALID_PROVENANCE


def test_planned_streetworks_normalizer_extracts_dates():
    # TfL road disruptions that are dated planned works → bundle-shaped records.
    raw = [
        {
            "id": "TIMS-PW-1",
            "category": "Planned Works",
            "subCategory": "Lane Closure",
            "severity": "Serious",
            "comments": "Carriageway resurfacing on the A3",
            "startDateTime": "2026-06-09T08:00:00Z",
            "endDateTime": "2026-06-09T17:00:00Z",
            "geography": {"type": "Point", "coordinates": [-0.1100, 51.5050]},
        },
        # current (undated) disruption must be dropped by the planned-works filter
        {
            "id": "TIMS-NOW",
            "category": "Accident",
            "geography": {"type": "Point", "coordinates": [-0.12, 51.51]},
        },
    ]
    works = integrations.normalize_tfl_planned_streetworks(raw)
    assert len(works) == 1
    w = works[0]
    assert w["date"] == "2026-06-09"
    assert w["start"] == "08:00" and w["end"] == "17:00"
    assert w["severity"] == "severe"
    assert quality.point_in_bbox(w["lat"], w["lng"])
