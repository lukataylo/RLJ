"""Representative London weather states + a congestion multiplier.

Rain and snow demonstrably slow urban traffic. We bundle a deterministic set of
daily weather states for the demo week and expose:

* ``weather_for(date)``           -> a weather record for any calendar date.
* ``congestion_multiplier(date)`` -> a float in [1.0, 1.8] (1.0 = dry/free-flow,
                                     higher = wetter/slower).

Everything is offline and byte-stable. Dates inside the bundled demo window use
the curated states; any other date falls back to a stable hash of the ISO date
string so the function is total and reproducible with no network.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent
WEATHER_PATH = DATA_DIR / "weather.json"

BUNDLE_FETCHED_AT = "2026-06-01T00:00:00+00:00"
SOURCE = "bundled-representative"

# Recognised conditions and their traffic-congestion multiplier (wet => slower).
CONDITIONS = ("clear", "rain", "heavy_rain", "snow")
CONGESTION_MULTIPLIER = {
    "clear": 1.0,
    "rain": 1.25,
    "heavy_rain": 1.5,
    "snow": 1.8,
}

# Representative per-condition meteorology (temp_c, precip_mm/h, wind_mps).
_CONDITION_WX = {
    "clear": {"temp_c": 18.0, "precip_mm": 0.0, "wind_mps": 3.0},
    "rain": {"temp_c": 13.0, "precip_mm": 2.5, "wind_mps": 5.0},
    "heavy_rain": {"temp_c": 11.0, "precip_mm": 8.0, "wind_mps": 8.0},
    "snow": {"temp_c": 0.0, "precip_mm": 4.0, "wind_mps": 6.0},
}

# Curated demo-week conditions (London, early June scenario week).
BUNDLED_WEATHER: dict[str, str] = {
    "2026-06-01": "clear",
    "2026-06-02": "rain",
    "2026-06-03": "clear",
    "2026-06-04": "heavy_rain",
    "2026-06-05": "rain",      # the demo scenario day
    "2026-06-06": "clear",
    "2026-06-07": "rain",
    "2026-06-08": "clear",
}


def _iso_date(d: date | datetime | str) -> str:
    if isinstance(d, datetime):
        return d.date().isoformat()
    if isinstance(d, date):
        return d.isoformat()
    return str(d)[:10]


def _condition(d: date | datetime | str) -> str:
    iso = _iso_date(d)
    if iso in BUNDLED_WEATHER:
        return BUNDLED_WEATHER[iso]
    # Deterministic fallback for arbitrary dates: weight towards drier days.
    h = int(hashlib.md5(iso.encode("utf-8")).hexdigest(), 16)
    # 0-4 clear, 5-7 rain, 8 heavy_rain, 9 snow  (mostly dry, occasionally wet)
    bucket = h % 10
    if bucket <= 4:
        return "clear"
    if bucket <= 7:
        return "rain"
    if bucket == 8:
        return "heavy_rain"
    return "snow"


def weather_for(d: date | datetime | str) -> dict:
    """Return a weather record for calendar date ``d`` (deterministic)."""
    iso = _iso_date(d)
    cond = _condition(iso)
    wx = _CONDITION_WX[cond]
    return {
        "date": iso,
        "condition": cond,
        "temp_c": wx["temp_c"],
        "precip_mm": wx["precip_mm"],
        "wind_mps": wx["wind_mps"],
        "congestion_multiplier": CONGESTION_MULTIPLIER[cond],
        "source": SOURCE,
        "fetched_at": BUNDLE_FETCHED_AT,
    }


def congestion_multiplier(d: date | datetime | str) -> float:
    """Traffic-congestion multiplier for date ``d`` — a float in [1.0, 1.8]."""
    return float(CONGESTION_MULTIPLIER[_condition(d)])


def build_weather() -> dict:
    """Return the full bundle payload (per-day records + provenance)."""
    days = {iso: weather_for(iso) for iso in BUNDLED_WEATHER}
    return {
        "source": SOURCE,
        "fetched_at": BUNDLE_FETCHED_AT,
        "provider": "bundled representative London weather states",
        "conditions": list(CONDITIONS),
        "congestion_multiplier": dict(CONGESTION_MULTIPLIER),
        "days": days,
    }


def write_weather(path: Path | str = WEATHER_PATH) -> dict:
    payload = build_weather()
    Path(path).write_text(json.dumps(payload, indent=2) + "\n")
    return payload


if __name__ == "__main__":
    w = write_weather()
    print(f"wrote weather for {len(w['days'])} days -> {WEATHER_PATH}")
