"""Environment Agency Live Flood Warning API integration (offline-safe, bundled fallback).

Exposes:
* ``flood_disruptions(date)`` -> list of TimedEvent road_closures / traffic delays.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent
FLOODWARNINGS_PATH = DATA_DIR / "floodwarnings.json"

BUNDLE_FETCHED_AT = "2026-06-01T00:00:00+00:00"
SOURCE = "scheduled"

# Flood alert configurations for London
BUNDLED_FLOODS = [
    {
        "id": "fld-thames-barrier",
        "description": "Thames Barrier / Woolwich — high tide flood warning",
        "lat": 51.4980,
        "lng": 0.0370,
        "start": "12:00",
        "end": "16:00",
        "date": "2026-06-05",
        "severity": "Serious",
    },
    {
        "id": "fld-putney-embankment",
        "description": "Putney Embankment — localized tidal flooding",
        "lat": 51.4680,
        "lng": -0.2200,
        "start": "13:30",
        "end": "16:30",
        "date": "2026-06-06",
        "severity": "Serious",
    },
    {
        "id": "fld-richmond",
        "description": "Richmond Riverpath — tidal overflow",
        "lat": 51.4580,
        "lng": -0.3100,
        "start": "14:00",
        "end": "17:00",
        "date": "2026-06-07",
        "severity": "Minimal",
    },
]


def _as_date(d: date | datetime | str) -> date:
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d)[:10])


def _box(lat: float, lng: float) -> list[dict]:
    pad = 0.005
    return [
        {"lat": round(lat + pad, 6), "lng": round(lng - pad, 6)},
        {"lat": round(lat + pad, 6), "lng": round(lng + pad, 6)},
        {"lat": round(lat - pad, 6), "lng": round(lng + pad, 6)},
        {"lat": round(lat - pad, 6), "lng": round(lng - pad, 6)},
        {"lat": round(lat + pad, 6), "lng": round(lng - pad, 6)},
    ]


def flood_disruptions(d: date | datetime | str) -> list[dict]:
    """Get flood-related timed disruptions for a given date."""
    day = _as_date(d)
    iso = day.isoformat()
    out = []
    for idx, f in enumerate(BUNDLED_FLOODS):
        if f["date"] != iso:
            continue
        shh, smm = (int(x) for x in f["start"].split(":"))
        ehh, emm = (int(x) for x in f["end"].split(":"))
        start = datetime(day.year, day.month, day.day, shh, smm, tzinfo=timezone.utc)
        end = datetime(day.year, day.month, day.day, ehh, emm, tzinfo=timezone.utc)

        kind = "road_closure" if f["severity"] == "Serious" else "traffic"
        intensity = 1.0 if kind == "road_closure" else 0.5

        out.append(
            {
                "id": f"{f['id']}-{iso}",
                "kind": kind,
                "geometry": _box(f["lat"], f["lng"]),
                "start": start.isoformat(),
                "end": end.isoformat(),
                "intensity": intensity,
                "source": SOURCE,
                "label": f["description"],
                "fetched_at": BUNDLE_FETCHED_AT,
            }
        )
    return out


def build_floodwarnings() -> dict:
    return {
        "source": SOURCE,
        "fetched_at": BUNDLE_FETCHED_AT,
        "provider": "Environment Agency Live Flood Warnings (bundled)",
        "floods": BUNDLED_FLOODS,
    }


def write_floodwarnings(path: Path | str = FLOODWARNINGS_PATH) -> dict:
    payload = build_floodwarnings()
    Path(path).write_text(json.dumps(payload, indent=2) + "\n")
    return payload


if __name__ == "__main__":
    write_floodwarnings()
