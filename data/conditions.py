"""Upcoming-conditions pipeline — one forward-looking timeline for the courier.

Merges every *scheduled / forward-looking* source that can affect a delivery run into a
single, time-ordered feed the operator and driver can act on ahead of time:

* planned street/road **works** (with start/end), from :mod:`streetworks`
* Tower **bridge** bascule lifts, from :mod:`towerbridge`
* major public **events**, from :mod:`events`
* **flood** alerts, from :mod:`floodwarnings`
* major **developments** (planning), from :mod:`planning` (no fixed window — standing
  context near the operating area)

Each merged record is normalized to ``{id, category, title, severity, starts, ends,
lat, lng, source}``. Pure + deterministic for a given ``now``; the orchestrator's
``/conditions/upcoming`` endpoint reads the published artifact and filters by horizon +
proximity at request time.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import events as events_mod
import floodwarnings as floodwarnings_mod
import planning as planning_mod
import streetworks as streetworks_mod
import towerbridge as towerbridge_mod

DATA_DIR = Path(__file__).resolve().parent
ROOT = DATA_DIR.parent
CONDITIONS_PATH = DATA_DIR / "conditions.json"
FRONTEND_CONDITIONS_PATH = ROOT / "frontend" / "public" / "data" / "conditions.json"

CONDITION_CATEGORIES = ("works", "bridge", "event", "flood", "development")
CONDITION_SEVERITIES = ("low", "moderate", "severe")

DEFAULT_HORIZON_HOURS = 24


def _parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _coerce_now(now: datetime | str) -> datetime:
    dt = _parse(now) if isinstance(now, str) else now
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _centroid(geometry: list[dict]) -> tuple[float, float] | None:
    pts = [(p.get("lat"), p.get("lng")) for p in geometry if p.get("lat") is not None]
    if not pts:
        return None
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def _severity(rec: dict) -> str:
    sev = str(rec.get("severity") or "").lower()
    if sev in CONDITION_SEVERITIES:
        return sev
    intensity = rec.get("intensity")
    if isinstance(intensity, (int, float)):
        if intensity >= 0.8:
            return "severe"
        if intensity >= 0.4:
            return "moderate"
    return "low"


def _timed_to_condition(rec: dict, category: str) -> dict | None:
    centre = _centroid(rec.get("geometry") or [])
    if centre is None:
        return None
    lat, lng = centre
    return {
        "id": str(rec["id"]),
        "category": category,
        "title": str(rec.get("label") or category.title()),
        "severity": _severity(rec),
        "starts": rec.get("start"),
        "ends": rec.get("end"),
        "lat": round(lat, 6),
        "lng": round(lng, 6),
        "source": str(rec.get("source") or "scheduled"),
    }


def _planning_to_condition(app: dict) -> dict:
    # Developments are standing context (no fixed window): a leading indicator of future
    # road impact near the operating area.
    return {
        "id": str(app["id"]),
        "category": "development",
        "title": str(app.get("description") or "Major development"),
        "severity": "moderate" if app.get("scale") == "major" else "low",
        "starts": None,
        "ends": None,
        "lat": float(app["lat"]),
        "lng": float(app["lng"]),
        "source": "planning",
    }


def build_conditions(now: datetime | str, horizon_hours: int = DEFAULT_HORIZON_HOURS,
                     allow_network: bool = False) -> dict:
    """Merge all forward-looking sources into one normalized, time-ordered feed."""
    now_dt = _coerce_now(now)
    until = now_dt + timedelta(hours=horizon_hours)

    timed: list[dict] = []
    for day in sorted({now_dt.date(), until.date()}):
        timed += [(_timed_to_condition(e, "works")) for e in streetworks_mod.streetwork_disruptions(day)]
        timed += [(_timed_to_condition(e, "bridge")) for e in towerbridge_mod.lift_events(day)]
        timed += [(_timed_to_condition(e, "event")) for e in events_mod.event_disruptions(day)]
        timed += [(_timed_to_condition(e, "flood")) for e in floodwarnings_mod.flood_disruptions(day)]

    # Keep timed conditions overlapping [now, now+horizon]; de-dup by id.
    windowed: dict[str, dict] = {}
    for c in timed:
        if c is None:
            continue
        starts = _parse(c["starts"]) if c.get("starts") else now_dt
        ends = _parse(c["ends"]) if c.get("ends") else until
        if starts < until and ends > now_dt:
            windowed[c["id"]] = c

    planning_payload = planning_mod.build_planning(allow_network=allow_network)
    developments = [_planning_to_condition(a) for a in planning_payload.get("applications", [])]

    conditions = list(windowed.values())
    conditions.sort(key=lambda c: (c.get("starts") or "", c["id"]))
    # Developments appended after the time-ordered window (no start time of their own).
    conditions += developments

    return {
        "source": "derived",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "provider": "PulseGo upcoming-conditions seam (streetworks + bridge + events + flood + planning)",
        "scenario_now": now_dt.isoformat(),
        "horizon_hours": horizon_hours,
        "conditions": conditions,
    }


def write_conditions(now: datetime | str, path: Path | str = CONDITIONS_PATH,
                     horizon_hours: int = DEFAULT_HORIZON_HOURS,
                     allow_network: bool = False) -> dict:
    payload = build_conditions(now, horizon_hours=horizon_hours, allow_network=allow_network)
    blob = json.dumps(payload, indent=2) + "\n"
    Path(path).write_text(blob)
    FRONTEND_CONDITIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    FRONTEND_CONDITIONS_PATH.write_text(blob)
    return payload


if __name__ == "__main__":
    write_conditions(datetime.now(timezone.utc).isoformat())
