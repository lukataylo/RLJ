"""Public-event congestion signals (offline-safe, bundled literal).

Large London venues create predictable, time-boxed road congestion around
kick-off / doors-open and again at egress. We bundle ~8 real venues with their
approximate coordinates and a deterministic set of scheduled event windows, and
expose ``event_disruptions(date)`` -> timed ``traffic`` events: a polygon around
the venue active over ``[start-60min, end+90min]`` with an ``intensity`` scaled
by expected attendance.

Everything is a bundled literal carrying provenance (``source``/``fetched_at``)
so the demo runs with no network and is byte-stable across builds.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent
EVENTS_PATH = DATA_DIR / "events.json"

BUNDLE_FETCHED_AT = "2026-06-01T00:00:00+00:00"
SOURCE = "scheduled"

# Congestion footprint half-size (degrees) around a venue ~ 450m box.
_PAD_DEG = 0.0045
# Largest attendance, used to normalise intensity into (0, 1].
_MAX_ATTENDANCE = 90000

# id, name, lat, lng — real London venues, approximate real coordinates.
VENUES: list[dict] = [
    {"id": "wembley", "name": "Wembley Stadium", "lat": 51.5560, "lng": -0.2796},
    {"id": "emirates", "name": "Emirates Stadium", "lat": 51.5549, "lng": -0.1084},
    {"id": "stamford-bridge", "name": "Stamford Bridge", "lat": 51.4817, "lng": -0.1910},
    {"id": "the-o2", "name": "The O2 Arena", "lat": 51.5030, "lng": 0.0032},
    {"id": "london-stadium", "name": "London Stadium", "lat": 51.5386, "lng": -0.0166},
    {"id": "tottenham", "name": "Tottenham Hotspur Stadium", "lat": 51.6043, "lng": -0.0664},
    {"id": "excel", "name": "ExCeL London", "lat": 51.5081, "lng": 0.0294},
    {"id": "twickenham", "name": "Twickenham Stadium", "lat": 51.4560, "lng": -0.3414},
]
_VENUE_BY_ID = {v["id"]: v for v in VENUES}

# Deterministic scheduled programme (date, venue_id, start HH:MM, end HH:MM,
# expected_attendance). Centred on the demo week (1-8 Jun 2026).
BUNDLED_EVENTS: list[dict] = [
    {"date": "2026-06-05", "venue": "wembley", "title": "England v Spain (friendly)", "start": "19:45", "end": "21:45", "attendance": 88000},
    {"date": "2026-06-05", "venue": "the-o2", "title": "Arena concert", "start": "20:00", "end": "22:30", "attendance": 18000},
    {"date": "2026-06-05", "venue": "excel", "title": "MedTech Expo", "start": "09:00", "end": "17:00", "attendance": 22000},
    {"date": "2026-06-06", "venue": "twickenham", "title": "Rugby international", "start": "15:00", "end": "17:00", "attendance": 80000},
    {"date": "2026-06-06", "venue": "emirates", "title": "Premier League fixture", "start": "12:30", "end": "14:30", "attendance": 60000},
    {"date": "2026-06-06", "venue": "london-stadium", "title": "Athletics meet", "start": "18:00", "end": "21:00", "attendance": 55000},
    {"date": "2026-06-07", "venue": "tottenham", "title": "Premier League fixture", "start": "16:30", "end": "18:30", "attendance": 61000},
    {"date": "2026-06-07", "venue": "stamford-bridge", "title": "Premier League fixture", "start": "14:00", "end": "16:00", "attendance": 40000},
    {"date": "2026-06-07", "venue": "the-o2", "title": "Arena concert", "start": "19:30", "end": "22:00", "attendance": 20000},
    {"date": "2026-06-08", "venue": "wembley", "title": "Cup final", "start": "17:00", "end": "19:00", "attendance": 90000},
    {"date": "2026-06-08", "venue": "excel", "title": "MedTech Expo (day 2)", "start": "09:00", "end": "16:00", "attendance": 21000},
]

# Pre-event build-up and post-event egress padding.
_PRE_MIN = 60
_POST_MIN = 90


def _as_date(d: date | datetime | str) -> date:
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d)[:10])


def _box(lat: float, lng: float) -> list[dict]:
    """A small rectangular footprint around a point (closed ring, 5 pts)."""
    return [
        {"lat": round(lat + _PAD_DEG, 6), "lng": round(lng - _PAD_DEG, 6)},
        {"lat": round(lat + _PAD_DEG, 6), "lng": round(lng + _PAD_DEG, 6)},
        {"lat": round(lat - _PAD_DEG, 6), "lng": round(lng + _PAD_DEG, 6)},
        {"lat": round(lat - _PAD_DEG, 6), "lng": round(lng - _PAD_DEG, 6)},
        {"lat": round(lat + _PAD_DEG, 6), "lng": round(lng - _PAD_DEG, 6)},
    ]


def _hhmm(day: date, hhmm: str) -> datetime:
    hh, mm = (int(x) for x in hhmm.split(":"))
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=timezone.utc)


def event_disruptions(d: date | datetime | str) -> list[dict]:
    """Timed ``traffic`` events for every scheduled event on ``d``.

    Deterministic per calendar date. Intensity in (0, 1] scales with attendance.
    """
    day = _as_date(d)
    iso = day.isoformat()
    out: list[dict] = []
    for idx, ev in enumerate(BUNDLED_EVENTS):
        if ev["date"] != iso:
            continue
        venue = _VENUE_BY_ID[ev["venue"]]
        start = _hhmm(day, ev["start"]) - timedelta(minutes=_PRE_MIN)
        end = _hhmm(day, ev["end"]) + timedelta(minutes=_POST_MIN)
        intensity = round(min(1.0, ev["attendance"] / _MAX_ATTENDANCE), 3)
        intensity = max(intensity, 0.05)  # keep strictly > 0
        out.append(
            {
                "id": f"evt-{iso}-{ev['venue']}-{idx}",
                "kind": "traffic",
                "geometry": _box(venue["lat"], venue["lng"]),
                "start": start.isoformat(),
                "end": end.isoformat(),
                "intensity": intensity,
                "source": SOURCE,
                "label": f"{ev['title']} @ {venue['name']} (~{ev['attendance']:,} attending)",
                "fetched_at": BUNDLE_FETCHED_AT,
            }
        )
    return out


def build_events() -> dict:
    """Return the bundle payload (venues + programme + provenance)."""
    return {
        "source": SOURCE,
        "fetched_at": BUNDLE_FETCHED_AT,
        "provider": "bundled public-event programme (London venues)",
        "venues": [dict(v) for v in VENUES],
        "events": [dict(e) for e in BUNDLED_EVENTS],
    }


def write_events(path: Path | str = EVENTS_PATH) -> dict:
    payload = build_events()
    Path(path).write_text(json.dumps(payload, indent=2) + "\n")
    return payload


if __name__ == "__main__":
    write_events()
    print(f"wrote {len(VENUES)} venues / {len(BUNDLED_EVENTS)} events -> {EVENTS_PATH}")
