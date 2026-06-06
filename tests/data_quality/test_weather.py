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


# --------------------------------------------------------------------------- #
# WMO code mapping + LIVE Open-Meteo path — HTTP mocked (deterministic/offline).
# --------------------------------------------------------------------------- #
def test_wmo_to_condition_mapping():
    cases = {
        0: "clear", 3: "clear", 45: "clear",
        51: "rain", 61: "rain", 80: "rain",
        65: "heavy_rain", 95: "heavy_rain", 99: "heavy_rain",
        71: "snow", 75: "snow", 86: "snow",
    }
    for code, expected in cases.items():
        assert weather_mod._wmo_to_condition(code) == expected, f"WMO {code}"


def _canned_open_meteo(code: int):
    def _fetch(lat=weather_mod.LONDON_LAT, lng=weather_mod.LONDON_LNG):
        return {
            "current": {
                "time": "2026-06-06T10:45",
                "temperature_2m": 12.3,
                "precipitation": 1.4,
                "wind_speed_10m": 4.2,
                "weather_code": code,
            }
        }
    return _fetch


def test_live_weather_payload(monkeypatch):
    """A live Open-Meteo pull enriches the payload with a current condition and
    the matching congestion multiplier, and marks the source live-with-fallback."""
    monkeypatch.setattr(weather_mod, "_open_meteo_fetch_raw", _canned_open_meteo(61))  # rain

    payload = weather_mod.build_weather(allow_network=True)
    assert payload["live"] is True
    assert payload["source"] == "live-with-fallback"

    cur = payload["current"]
    assert cur["condition"] == "rain"
    assert cur["congestion_multiplier"] == weather_mod.CONGESTION_MULTIPLIER["rain"]
    assert 1.0 <= cur["congestion_multiplier"] <= 1.8
    assert cur["source"] == "live"
    # today's live record is folded into the per-day map
    assert payload["days"][cur["date"]] == cur


def test_live_weather_falls_back(monkeypatch):
    """On any Open-Meteo error the payload stays on the bundled representative
    states (offline-safe)."""
    def _boom(*a, **k):
        raise RuntimeError("open-meteo down")

    monkeypatch.setattr(weather_mod, "_open_meteo_fetch_raw", _boom)

    payload = weather_mod.build_weather(allow_network=True)
    assert payload["live"] is False
    assert payload["source"] == weather_mod.SOURCE
    assert "current" not in payload
