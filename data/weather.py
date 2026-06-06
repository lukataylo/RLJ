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
from datetime import date, datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent
WEATHER_PATH = DATA_DIR / "weather.json"

BUNDLE_FETCHED_AT = "2026-06-01T00:00:00+00:00"
SOURCE = "bundled-representative"

# ---- Open-Meteo (live current conditions) --------------------------------- #
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
USER_AGENT = "RLJ-PulseGo-data-build/1.0 (London weather)"
LONDON_LAT, LONDON_LNG = 51.5074, -0.1278
_HTTP_TIMEOUT_S = 10

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


# --------------------------------------------------------------------------- #
# Live current conditions (Open-Meteo). The per-date functions above stay
# deterministic (backtests depend on them); the live pull only enriches the
# build payload with the *current* representative condition + multiplier.
# --------------------------------------------------------------------------- #
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _wmo_to_condition(code: int) -> str:
    """Map a WMO weather code (Open-Meteo) to one of :data:`CONDITIONS`."""
    c = int(code)
    if c in (71, 73, 75, 77, 85, 86):           # snow / snow showers
        return "snow"
    if c in (65, 67, 82, 95, 96, 99):           # heavy rain / violent / thunder
        return "heavy_rain"
    if c in (51, 53, 55, 56, 57, 61, 63, 66, 80, 81):  # drizzle / rain
        return "rain"
    return "clear"                              # 0-3 clear/cloudy, 45/48 fog, etc.


def _open_meteo_fetch_raw(lat: float = LONDON_LAT, lng: float = LONDON_LNG) -> dict:
    """GET current London weather from Open-Meteo. Network seam — tests patch it."""
    import requests

    resp = requests.get(
        OPEN_METEO_URL,
        params={
            "latitude": lat,
            "longitude": lng,
            "current": "temperature_2m,precipitation,wind_speed_10m,weather_code",
            "wind_speed_unit": "ms",
        },
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=_HTTP_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json()


def _try_fetch_live() -> dict | None:
    """Best-effort live current-conditions record. None on any failure."""
    try:
        raw = _open_meteo_fetch_raw()
        cur = raw.get("current") or {}
        cond = _wmo_to_condition(cur["weather_code"])
        ts = cur.get("time")
        iso_date = (str(ts)[:10] if ts else _now_iso()[:10])
        return {
            "date": iso_date,
            "condition": cond,
            "temp_c": float(cur.get("temperature_2m", _CONDITION_WX[cond]["temp_c"])),
            "precip_mm": float(cur.get("precipitation", _CONDITION_WX[cond]["precip_mm"])),
            "wind_mps": float(cur.get("wind_speed_10m", _CONDITION_WX[cond]["wind_mps"])),
            "weather_code": int(cur["weather_code"]),
            "congestion_multiplier": CONGESTION_MULTIPLIER[cond],
            "source": "live",
            "fetched_at": _now_iso(),
        }
    except Exception:  # noqa: BLE001
        return None


def build_weather(allow_network: bool = False) -> dict:
    """Return the full payload (per-day records + provenance).

    When ``allow_network`` is set we add a live Open-Meteo ``current`` block and
    fold today's live condition into ``days``; on any failure we keep the bundled
    representative states. The per-date helpers stay deterministic regardless.
    """
    days = {iso: weather_for(iso) for iso in BUNDLED_WEATHER}
    payload = {
        "source": SOURCE,
        "fetched_at": BUNDLE_FETCHED_AT,
        "live": False,
        "provider": "bundled representative London weather states",
        "conditions": list(CONDITIONS),
        "congestion_multiplier": dict(CONGESTION_MULTIPLIER),
        "days": days,
    }

    if allow_network:
        live = _try_fetch_live()
        if live:
            payload["source"] = "live-with-fallback"
            payload["live"] = True
            payload["fetched_at"] = live["fetched_at"]
            payload["provider"] = "Open-Meteo (live) with bundled fallback"
            payload["current"] = live
            payload["days"][live["date"]] = live

    return payload


def write_weather(path: Path | str = WEATHER_PATH, allow_network: bool = False) -> dict:
    payload = build_weather(allow_network=allow_network)
    Path(path).write_text(json.dumps(payload, indent=2) + "\n")
    return payload


if __name__ == "__main__":
    w = write_weather(allow_network=True)
    print(f"wrote weather for {len(w['days'])} days (live={w['live']}) -> {WEATHER_PATH}")
