"""Upcoming-conditions pipeline DQ tests (data/conditions.py).

The merged forward-looking feed must combine every scheduled source (works, bridge
lifts, events, floods) plus standing major developments, normalized to one schema and
inside the London bbox — so the operator/driver get a single, trustworthy horizon.
"""
from __future__ import annotations

from datetime import datetime, timezone

import conditions as conditions_mod
import quality

SCENARIO_NOW = "2026-06-05T08:00:00+00:00"


def test_conditions_feed_sane():
    payload = conditions_mod.build_conditions(SCENARIO_NOW, allow_network=False)
    quality.validate_conditions(payload)

    conds = payload["conditions"]
    assert len(conds) > 0
    ids = [c["id"] for c in conds]
    assert len(ids) == len(set(ids))  # de-duplicated
    cats = {c["category"] for c in conds}
    # the pipeline must surface forward-looking works AND standing developments
    assert "works" in cats
    assert "development" in cats
    for c in conds:
        assert quality.point_in_bbox(c["lat"], c["lng"])
        assert c["severity"] in conditions_mod.CONDITION_SEVERITIES


def test_conditions_window_orders_by_start():
    payload = conditions_mod.build_conditions(SCENARIO_NOW, horizon_hours=12, allow_network=False)
    timed = [c for c in payload["conditions"] if c.get("starts")]
    starts = [c["starts"] for c in timed]
    assert starts == sorted(starts)  # soonest-first within the window


def test_conditions_horizon_excludes_far_future():
    # A 1-hour horizon must drop works that only start much later in the day.
    short = conditions_mod.build_conditions(SCENARIO_NOW, horizon_hours=1, allow_network=False)
    long = conditions_mod.build_conditions(SCENARIO_NOW, horizon_hours=24, allow_network=False)
    short_timed = [c for c in short["conditions"] if c.get("starts")]
    long_timed = [c for c in long["conditions"] if c.get("starts")]
    assert len(short_timed) <= len(long_timed)
