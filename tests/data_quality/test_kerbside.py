"""Kerbside loading-zone DQ tests."""
from __future__ import annotations

import kerbside as kerbside_mod
import quality


def test_kerbside_loading_zones_sane():
    payload = kerbside_mod.build_kerbside()
    quality.validate_kerbside(payload)

    stat_zones = [z for z in payload["loading_zones"] if z["clinical_priority"] == "stat"]
    assert stat_zones, "no STAT-priority handoff zones"

    nearest = kerbside_mod.nearest_loading_zone(51.498, -0.1188)
    assert nearest["id"] == "kerb-gstt-lab"
    assert nearest["max_stay_min"] <= 20
