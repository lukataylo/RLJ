"""TfL live road-disruption / hazard DQ tests."""
from __future__ import annotations

import hazards as hazards_mod
import integrations
import quality


def test_hazards_sane():
    payload = hazards_mod.build_hazards()
    quality.validate_hazards(payload)

    hazards = payload["hazards"]
    assert len(hazards) > 0
    # deterministic ids, all in the London bbox, valid severities
    ids = [h["id"] for h in hazards]
    assert len(ids) == len(set(ids))
    for h in hazards:
        assert quality.point_in_bbox(h["lat"], h["lng"])
        assert h["severity"] in hazards_mod.HAZARD_SEVERITIES
    # at least one severe hazard the driver must avoid
    assert any(h["severity"] == "severe" for h in hazards)


def test_severity_band_mapping():
    assert hazards_mod.severity_band("Serious") == "severe"
    assert hazards_mod.severity_band("Severe") == "severe"
    assert hazards_mod.severity_band("Moderate") == "moderate"
    assert hazards_mod.severity_band("Minimal") == "low"
    assert hazards_mod.severity_band("") == "moderate"


def test_tfl_road_hazard_normalizer_handles_disruption_payload():
    raw = [
        {
            "id": "TIMS-9001",
            "category": "Accident",
            "severity": "Serious",
            "comments": "Collision blocking two lanes",
            "geography": {"type": "Point", "coordinates": [-0.1276, 51.5072]},
        },
        # out-of-bbox record must be dropped
        {
            "id": "TIMS-9002",
            "severity": "Moderate",
            "geography": {"type": "Point", "coordinates": [2.3522, 48.8566]},
        },
    ]

    hazards = integrations.normalize_tfl_road_hazards(raw)
    assert len(hazards) == 1
    h = hazards[0]
    assert h["id"] == "TIMS-9001"
    assert h["severity"] == "severe"
    assert h["description"] == "Collision blocking two lanes"
    quality.validate_hazards(
        {
            "source": "live",
            "fetched_at": "2026-06-05T08:00:00+00:00",
            "provider": "test",
            "hazards": hazards,
        }
    )
