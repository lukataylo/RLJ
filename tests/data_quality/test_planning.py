"""Major-developments (planning) DQ tests."""
from __future__ import annotations

import integrations
import planning as planning_mod
import quality


def test_planning_bundle_sane():
    payload = planning_mod.build_planning(allow_network=False)
    quality.validate_planning(payload)

    apps = payload["applications"]
    assert len(apps) > 0
    ids = [a["id"] for a in apps]
    assert len(ids) == len(set(ids))  # deterministic, unique ids
    for a in apps:
        assert quality.point_in_bbox(a["lat"], a["lng"])
        assert a["scale"] in planning_mod.PLANNING_SCALES
    # at least one major scheme (the high road-impact ones)
    assert any(a["scale"] == "major" for a in apps)


def test_planning_normalizer_filters_to_bbox():
    raw = {
        "entities": [
            {
                "entity": "44001",
                "reference": "2025/AB/0001",
                "name": "Central London tower scheme",
                "latitude": 51.5072,
                "longitude": -0.1276,
                "decision": "approved",
            },
            # out-of-bbox record must be dropped (Paris)
            {"entity": "44002", "latitude": 48.8566, "longitude": 2.3522},
        ]
    }
    apps = integrations.normalize_planning_applications(raw)
    assert len(apps) == 1
    assert apps[0]["reference"] == "2025/AB/0001"
    quality.validate_planning(
        {
            "source": "live",
            "fetched_at": "2026-06-05T08:00:00+00:00",
            "provider": "test",
            "applications": apps,
        }
    )
