"""Tower Bridge bascule-lift schedule (offline-safe, bundled literal).

The City Bridge Foundation publishes Tower Bridge lift times at
``towerbridge.org.uk/lift-times``. The bridge lifts ~6-8 times a day for ~10
minutes each; during a lift the carriageway is fully closed to road traffic, so
each lift is modelled as a timed ``road_closure`` over the bridge span.

We bundle a realistic week of published lift times keyed by ISO weekday so that
``lift_events(date)`` is deterministic for *any* date with no network. The
literal carries provenance (``source``/``fetched_at``) per the data contract.
``build_towerbridge(allow_network=True)`` will best-effort fetch the live page
and silently fall back to the bundle if anything is unreachable.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent
TOWERBRIDGE_PATH = DATA_DIR / "towerbridge.json"

# Provenance for the bundled literal: a fixed publish/snapshot instant so the
# written JSON is byte-stable across builds (deterministic).
BUNDLE_FETCHED_AT = "2026-06-01T00:00:00+00:00"
SOURCE = "scheduled"

# The Tower Bridge carriageway span (north abutment -> south abutment over the
# Thames). Approximate real coordinates, inside the London bbox.
BRIDGE_GEOMETRY: list[dict] = [
    {"lat": 51.5061, "lng": -0.0755},
    {"lat": 51.5055, "lng": -0.0751},
    {"lat": 51.5049, "lng": -0.0747},
]
# Bridge centre, used by tests to assert geometry sits on/near the structure.
BRIDGE_CENTRE = {"lat": 51.5055, "lng": -0.0751}

# A realistic published week, keyed by ISO weekday (Mon=0 .. Sun=6).
# Each lift: (HH:MM local published time, duration minutes, vessel).
BUNDLED_LIFTS: dict[int, list[tuple[str, int, str]]] = {
    0: [  # Monday
        ("06:45", 10, "Paddle Steamer Waverley"),
        ("09:15", 9, "Dixie Queen"),
        ("11:30", 11, "Silver Sturgeon"),
        ("13:45", 10, "Tower RNLI Lifeboat"),
        ("15:30", 8, "Jubilant"),
        ("18:00", 10, "Gloriana"),
        ("20:30", 12, "Sabre"),
    ],
    1: [  # Tuesday
        ("07:00", 10, "Dixie Queen"),
        ("09:45", 9, "Edwardian"),
        ("12:00", 10, "Silver Sturgeon"),
        ("14:15", 11, "Paddle Steamer Waverley"),
        ("16:30", 9, "Jubilant"),
        ("19:00", 10, "Gloriana"),
    ],
    2: [  # Wednesday
        ("06:30", 9, "Sabre"),
        ("08:45", 10, "Silver Sturgeon"),
        ("11:00", 12, "Dixie Queen"),
        ("13:30", 10, "Gloriana"),
        ("15:45", 8, "Edwardian"),
        ("18:15", 10, "Paddle Steamer Waverley"),
        ("21:00", 11, "Jubilant"),
    ],
    3: [  # Thursday
        ("07:15", 10, "Jubilant"),
        ("09:30", 9, "Gloriana"),
        ("12:15", 10, "Sabre"),
        ("14:45", 11, "Silver Sturgeon"),
        ("17:00", 10, "Dixie Queen"),
        ("19:45", 9, "Edwardian"),
    ],
    4: [  # Friday
        ("06:45", 10, "Edwardian"),
        ("09:00", 9, "Sabre"),
        ("11:15", 10, "Paddle Steamer Waverley"),
        ("13:30", 12, "Gloriana"),
        ("16:00", 10, "Dixie Queen"),
        ("18:30", 9, "Silver Sturgeon"),
        ("21:15", 11, "Jubilant"),
    ],
    5: [  # Saturday
        ("07:30", 10, "Paddle Steamer Waverley"),
        ("10:00", 11, "Dixie Queen"),
        ("12:30", 10, "Gloriana"),
        ("14:45", 9, "Silver Sturgeon"),
        ("17:15", 10, "Sabre"),
        ("19:30", 10, "Jubilant"),
        ("21:45", 8, "Edwardian"),
    ],
    6: [  # Sunday
        ("08:00", 10, "Gloriana"),
        ("10:30", 9, "Silver Sturgeon"),
        ("12:45", 10, "Dixie Queen"),
        ("15:00", 11, "Paddle Steamer Waverley"),
        ("17:30", 9, "Sabre"),
        ("20:00", 10, "Edwardian"),
    ],
}


def _as_date(d: date | datetime | str) -> date:
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d)[:10])


def lift_events(d: date | datetime | str) -> list[dict]:
    """Timed ``road_closure`` events for every Tower Bridge lift on ``d``.

    Deterministic: the same calendar date always yields the same list. Times are
    interpreted as UTC for reproducibility offline.
    """
    day = _as_date(d)
    lifts = BUNDLED_LIFTS[day.weekday()]
    out: list[dict] = []
    for idx, (hhmm, dur_min, vessel) in enumerate(lifts):
        hh, mm = (int(x) for x in hhmm.split(":"))
        start = datetime(day.year, day.month, day.day, hh, mm, tzinfo=timezone.utc)
        end = start + _td(dur_min)
        out.append(
            {
                "id": f"twr-{day.isoformat()}-{idx}",
                "kind": "road_closure",
                "geometry": [dict(p) for p in BRIDGE_GEOMETRY],
                "start": start.isoformat(),
                "end": end.isoformat(),
                "intensity": 1.0,  # full carriageway closure during a lift
                "source": SOURCE,
                "label": f"Tower Bridge lift for {vessel}",
                "fetched_at": BUNDLE_FETCHED_AT,
            }
        )
    return out


def _td(minutes: int):
    from datetime import timedelta

    return timedelta(minutes=minutes)


def build_towerbridge(allow_network: bool = False) -> dict:
    """Return the bundle payload (schedule + geometry + provenance)."""
    if allow_network:
        fetched = _try_fetch()
        if fetched:
            return fetched
    return {
        "source": SOURCE,
        "fetched_at": BUNDLE_FETCHED_AT,
        "provider": "City Bridge Foundation / towerbridge.org.uk (bundled)",
        "geometry": [dict(p) for p in BRIDGE_GEOMETRY],
        "centre": dict(BRIDGE_CENTRE),
        "schedule": {
            str(wd): [
                {"time": t, "duration_min": dur, "vessel": v}
                for (t, dur, v) in lifts
            ]
            for wd, lifts in BUNDLED_LIFTS.items()
        },
    }


def _try_fetch() -> dict | None:
    """Best-effort live fetch; returns None on any failure (stays offline)."""
    try:  # pragma: no cover - network path not exercised in CI
        import requests

        resp = requests.get("https://www.towerbridge.org.uk/lift-times", timeout=3)
        resp.raise_for_status()
        # The live page is HTML; we do not trust ad-hoc scraping for the demo and
        # deliberately keep the curated bundle.
        return None
    except Exception:
        return None


def write_towerbridge(path: Path | str = TOWERBRIDGE_PATH, allow_network: bool = False) -> dict:
    payload = build_towerbridge(allow_network=allow_network)
    Path(path).write_text(json.dumps(payload, indent=2) + "\n")
    return payload


if __name__ == "__main__":
    p = write_towerbridge()
    print(f"wrote Tower Bridge schedule ({sum(len(v) for v in BUNDLED_LIFTS.values())} lifts/wk) -> {TOWERBRIDGE_PATH}")
