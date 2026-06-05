"""Signal DQ — Tower Bridge lifts + public-event congestion as timed disruptions.

These bind to the claims ledger by exact file::function name. They exercise the
single ``data/signals.py`` seam plus the underlying ``towerbridge``/``events``
sources, and validate everything against contracts/schemas.json via the shared
``validate_entity`` fixture.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import events as events_mod
import quality
import signals as signals_mod
import towerbridge as towerbridge_mod

# The demo scenario day (a Friday). Tower Bridge always lifts, so the merged
# timeline is non-empty on any date; this day also has bundled public events.
SCENARIO_DATE = "2026-06-05"


def _parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def test_timed_events_valid():
    """Every merged TimedEvent is schema-valid: good kind, bbox geometry,
    end>start, intensity in (0,1]."""
    events = signals_mod.timed_events(SCENARIO_DATE)
    assert events, "no timed events for the scenario day"

    # shared quality validator (kinds, bbox, end>start, intensity, provenance)
    quality.validate_timed_events(events)

    kinds = {e["kind"] for e in events}
    assert kinds <= set(quality.TIMED_EVENT_KINDS)

    for e in events:
        assert e["geometry"], f"{e['id']} has empty geometry"
        for p in e["geometry"]:
            assert quality.point_in_bbox(p["lat"], p["lng"]), f"{e['id']} vertex out of bbox"
        assert _parse(e["end"]) > _parse(e["start"]), f"{e['id']} end !> start"
        assert 0.0 < e["intensity"] <= 1.0, f"{e['id']} intensity out of range"
        assert e["source"] in quality.VALID_PROVENANCE
        assert e["id"] and e["label"]

    # both signal families are represented on the scenario day
    assert any(e["kind"] == "road_closure" for e in events)  # tower bridge
    assert any(e["kind"] == "traffic" for e in events)  # public events


def test_active_and_horizon_consistency(validate_entity):
    """active ⊆ horizon; each is a schema-valid DisruptionEvent; and a horizon
    taken just before a Tower Bridge lift INCLUDES that lift while active does
    not (anticipation strictly dominates reaction)."""
    events = signals_mod.timed_events(SCENARIO_DATE)

    # pick a Tower Bridge lift and stand 30 min before it (inside a 120m horizon)
    lift = next(e for e in events if e["id"].startswith("twr-"))
    now = _parse(lift["start"]).astimezone(timezone.utc).replace(microsecond=0)
    now = datetime.fromtimestamp(now.timestamp() - 30 * 60, tz=timezone.utc)

    active = signals_mod.active_disruptions(now)
    horizon = signals_mod.horizon_disruptions(now, horizon_min=120)

    active_ids = {d["id"] for d in active}
    horizon_ids = {d["id"] for d in horizon}

    # every active item is also in the horizon (superset relationship)
    assert active_ids <= horizon_ids

    # the upcoming lift is anticipated by the horizon but is NOT yet active
    assert lift["id"] in horizon_ids, "horizon failed to anticipate the lift"
    assert lift["id"] not in active_ids, "lift should not be active yet"

    # everything projected is a schema-valid DisruptionEvent
    for d in active + horizon:
        validate_entity("DisruptionEvent", d)
        assert d["kind"] in ("road_closure", "traffic", "courier_down")
        assert d["source"] in ("tfl", "manual")


def test_towerbridge_schedule_sane():
    """Plausible lifts/day, each 5-20 min, no overlaps, geometry on/near bridge."""
    lifts = towerbridge_mod.lift_events(SCENARIO_DATE)
    assert 4 <= len(lifts) <= 10, f"implausible lift count {len(lifts)}"

    spans = []
    for lift in lifts:
        s, e = _parse(lift["start"]), _parse(lift["end"])
        dur_min = (e - s).total_seconds() / 60.0
        assert 5 <= dur_min <= 20, f"{lift['id']} duration {dur_min}min out of range"
        spans.append((s, e))

        # geometry sits on/near the bridge centre (~within ~150m)
        centre = towerbridge_mod.BRIDGE_CENTRE
        for p in lift["geometry"]:
            assert abs(p["lat"] - centre["lat"]) < 0.003
            assert abs(p["lng"] - centre["lng"]) < 0.003

    # no two lifts overlap
    spans.sort()
    for (s0, e0), (s1, e1) in zip(spans, spans[1:]):
        assert e0 <= s1, f"overlapping lifts: {e0} > {s1}"

    # validates across the whole bundled week too
    for wd in range(7):
        day_lifts = towerbridge_mod.BUNDLED_LIFTS[wd]
        assert 4 <= len(day_lifts) <= 10
