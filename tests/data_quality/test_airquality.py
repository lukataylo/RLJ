"""Air Quality DQ tests."""
from __future__ import annotations

import airquality as airquality_mod
import quality


def test_airquality_sane():
    payload = airquality_mod.build_airquality(allow_network=False)
    quality.validate_airquality(payload)

    # Southwark centroid: 51.5035, -0.0804
    rec = airquality_mod.air_quality_for("2026-06-05", 51.5035, -0.0804)
    assert rec["borough"] == "southwark"
    assert 1 <= rec["aqi"] <= 10
    assert rec["status"] in ("good", "moderate", "poor")

    # City of London centroid: 51.5137, -0.0918
    rec2 = airquality_mod.air_quality_for("2026-06-06", 51.5137, -0.0918)
    assert rec2["borough"] == "city-of-london"
