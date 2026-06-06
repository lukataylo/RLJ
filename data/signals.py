"""Signal seam — the single interface the app/routing consumes.

External "signal" sources (Tower Bridge bascule lifts, public-event congestion)
are merged here into one timeline of ``TimedEvent`` dicts, and projected into the
shared ``DisruptionEvent`` contract (contracts/schemas.json $defs/DisruptionEvent)
for the planner.

Three pure, deterministic functions:

* ``timed_events(date)``       -> all signals on a calendar date (full window).
* ``active_disruptions(now)``  -> DisruptionEvents live *right now* (reaction).
* ``horizon_disruptions(now)`` -> DisruptionEvents within a look-ahead window
                                  (anticipation; a superset of ``active``).

Note on provenance: TimedEvents are tagged ``source="scheduled"`` (our internal
provenance vocabulary). The ``DisruptionEvent`` contract only permits
``source in {"tfl","manual"}``, so projected disruptions use ``"manual"`` and
carry the richer provenance in the ``label``. See the contract-gap note in the
build report.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import events as events_mod
import floodwarnings as floodwarnings_mod
import streetworks as streetworks_mod
import towerbridge as towerbridge_mod

# DisruptionEvent.source enum is {"tfl","manual"}; scheduled feeds map to manual.
_DISRUPTION_SOURCE = "manual"


def _parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _coerce_now(now: datetime) -> datetime:
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now


def timed_events(d: date | datetime | str) -> list[dict]:
    """Merged, time-ordered list of TimedEvent dicts for calendar date ``d``.

    Each item: ``{id, kind, geometry, start, end, intensity, source, label}``.
    Deterministic for a given date.
    """
    merged = (
        list(towerbridge_mod.lift_events(d))
        + list(events_mod.event_disruptions(d))
        + list(streetworks_mod.streetwork_disruptions(d))
        + list(floodwarnings_mod.flood_disruptions(d))
    )
    out = [
        {
            "id": e["id"],
            "kind": e["kind"],
            "geometry": [dict(p) for p in e["geometry"]],
            "start": e["start"],
            "end": e["end"],
            "intensity": e["intensity"],
            "source": e["source"],
            "label": e["label"],
        }
        for e in merged
    ]
    out.sort(key=lambda e: (e["start"], e["id"]))
    return out


def _to_disruption(e: dict) -> dict:
    """Project a TimedEvent into a schema-valid DisruptionEvent dict."""
    return {
        "id": e["id"],
        "kind": e["kind"],
        "geometry": [dict(p) for p in e["geometry"]],
        "source": _DISRUPTION_SOURCE,
        "at": e["start"],
    }


def active_disruptions(now: datetime) -> list[dict]:
    """DisruptionEvents live at ``now`` (start <= now < end). Reactive view."""
    now = _coerce_now(now)
    day = now.date()
    out = []
    for e in timed_events(day):
        if _parse(e["start"]) <= now < _parse(e["end"]):
            out.append(_to_disruption(e))
    return out


def horizon_disruptions(now: datetime, horizon_min: int = 120) -> list[dict]:
    """DisruptionEvents overlapping ``[now, now+horizon_min]``. Anticipatory view.

    Superset of :func:`active_disruptions` — includes events that have not yet
    started but will within the look-ahead window, giving the planner more
    information than reaction alone.
    """
    now = _coerce_now(now)
    until = now + timedelta(minutes=horizon_min)
    # Look across today and the next day so windows that span midnight or fall
    # just inside the horizon on the following date are not missed.
    seen_days = {now.date(), until.date()}
    out = []
    for day in sorted(seen_days):
        for e in timed_events(day):
            start, end = _parse(e["start"]), _parse(e["end"])
            if start < until and end > now:  # intervals overlap
                out.append(_to_disruption(e))
    # de-dup by id (an event could appear under two scanned days)
    uniq: dict[str, dict] = {}
    for d in out:
        uniq[d["id"]] = d
    return list(uniq.values())
