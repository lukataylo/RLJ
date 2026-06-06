"""TfL Streetworks integration (offline-safe, planned roadworks bundle).

Exposes:
* ``streetwork_disruptions(date)`` -> list of TimedEvent road_closures.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent
STREETWORKS_PATH = DATA_DIR / "streetworks.json"

BUNDLE_FETCHED_AT = "2026-06-01T00:00:00+00:00"
SOURCE = "scheduled"

# Core London streetwork permits (representative fallback)
BUNDLED_STREETWORKS = [
    {
        "id": "stw-whitechapel",
        "description": "Whitechapel Road — utility main replacement by Thames Water",
        "lat": 51.5175,
        "lng": -0.0600,
        "start": "08:00",
        "end": "18:00",
        "date": "2026-06-05",
    },
    {
        "id": "stw-strand",
        "description": "Strand — carriageway resurfacing",
        "lat": 51.5110,
        "lng": -0.1200,
        "start": "09:00",
        "end": "17:00",
        "date": "2026-06-06",
    },
    {
        "id": "stw-euston",
        "description": "Euston Road — gas mains renewal",
        "lat": 51.5246,
        "lng": -0.1340,
        "start": "07:00",
        "end": "19:00",
        "date": "2026-06-07",
    },
]


def _as_date(d: date | datetime | str) -> date:
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d)[:10])


def _box(lat: float, lng: float) -> list[dict]:
    pad = 0.003
    return [
        {"lat": round(lat + pad, 6), "lng": round(lng - pad, 6)},
        {"lat": round(lat + pad, 6), "lng": round(lng + pad, 6)},
        {"lat": round(lat - pad, 6), "lng": round(lng + pad, 6)},
        {"lat": round(lat - pad, 6), "lng": round(lng - pad, 6)},
        {"lat": round(lat + pad, 6), "lng": round(lng - pad, 6)},
    ]


def streetwork_disruptions(d: date | datetime | str) -> list[dict]:
    """Get the planned streetwork disruptions for a date."""
    day = _as_date(d)
    iso = day.isoformat()
    out = []
    for idx, sw in enumerate(BUNDLED_STREETWORKS):
        if sw["date"] != iso:
            continue
        shh, smm = (int(x) for x in sw["start"].split(":"))
        ehh, emm = (int(x) for x in sw["end"].split(":"))
        start = datetime(day.year, day.month, day.day, shh, smm, tzinfo=timezone.utc)
        end = datetime(day.year, day.month, day.day, ehh, emm, tzinfo=timezone.utc)

        out.append(
            {
                "id": f"{sw['id']}-{iso}",
                "kind": "road_closure",
                "geometry": _box(sw["lat"], sw["lng"]),
                "start": start.isoformat(),
                "end": end.isoformat(),
                "intensity": 1.0,
                "source": SOURCE,
                "label": sw["description"],
                "fetched_at": BUNDLE_FETCHED_AT,
            }
        )
    return out


def build_streetworks() -> dict:
    return {
        "source": SOURCE,
        "fetched_at": BUNDLE_FETCHED_AT,
        "provider": "TfL Streetworks Register (bundled)",
        "streetworks": BUNDLED_STREETWORKS,
    }


def write_streetworks(path: Path | str = STREETWORKS_PATH) -> dict:
    payload = build_streetworks()
    Path(path).write_text(json.dumps(payload, indent=2) + "\n")
    return payload


if __name__ == "__main__":
    write_streetworks()
