"""Weather DQ — the congestion multiplier is bounded and deterministic."""
from __future__ import annotations

import weather as weather_mod

# A spread of dates: bundled demo-week days + arbitrary out-of-window dates that
# exercise the deterministic hash fallback.
_DATES = [
    "2026-06-01",
    "2026-06-04",
    "2026-06-05",
    "2026-06-08",
    "2025-01-15",
    "2024-12-25",
    "2030-07-04",
    "2026-11-11",
]


def test_weather_multiplier_sane():
    for d in _DATES:
        mult = weather_mod.congestion_multiplier(d)
        assert isinstance(mult, float)
        assert 1.0 <= mult <= 1.8, f"{d}: multiplier {mult} outside [1.0, 1.8]"

        wx = weather_mod.weather_for(d)
        assert wx["condition"] in weather_mod.CONDITIONS, f"{d}: bad condition"
        assert wx["date"] == d
        # the record's embedded multiplier agrees with the function
        assert wx["congestion_multiplier"] == mult

        # determinism: repeated calls agree
        assert weather_mod.congestion_multiplier(d) == mult
        assert weather_mod.weather_for(d) == wx

    # rain is modelled as strictly slower than clear, snow the slowest
    assert weather_mod.CONGESTION_MULTIPLIER["clear"] == 1.0
    assert (
        weather_mod.CONGESTION_MULTIPLIER["clear"]
        < weather_mod.CONGESTION_MULTIPLIER["rain"]
        < weather_mod.CONGESTION_MULTIPLIER["heavy_rain"]
        < weather_mod.CONGESTION_MULTIPLIER["snow"]
        == 1.8
    )

    # the curated scenario day is a wet (rain) day, so > free-flow
    assert weather_mod.congestion_multiplier("2026-06-05") > 1.0
