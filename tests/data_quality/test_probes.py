"""Probe DQ — simulated driver GPS pings are schema-valid, sane and deterministic.

Binds to the claims ledger by exact file::function name. Validates every
simulated ``DriverPing`` and every ``Driver`` against contracts/schemas.json via
the shared ``validate_entity`` fixture.
"""
from __future__ import annotations

from datetime import datetime

import probes as probes_mod
import quality

NOW = probes_mod.SNAPSHOT_NOW


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def test_probe_pings_valid(validate_entity):
    pings = probes_mod.simulate_probes(n_drivers=30, now=NOW, minutes=10, seed=0)
    assert pings, "simulate_probes produced no pings"

    # shared pipeline validator (bbox, speed 0-40, required fields, valid ts)
    quality.validate_pings(pings)

    speeds: list[float] = []
    for p in pings:
        # schema-valid DriverPing
        validate_entity("DriverPing", p)
        assert quality.point_in_bbox(p["lat"], p["lng"]), f"{p} out of bbox"
        assert 0.0 <= p["speed_mps"] <= 40.0, f"insane speed {p['speed_mps']}"
        assert 0.0 <= p["heading_deg"] <= 360.0, f"bad heading {p['heading_deg']}"
        _parse(p["ts"])  # raises if unparseable
        speeds.append(p["speed_mps"])

    # speeds sit in the realistic 2-12 m/s simulation band
    assert min(speeds) >= 2.0 - 1e-6
    assert max(speeds) <= 12.0 + 1e-6

    # there is a believable congested hotspot: some pings crawl near the centre
    slow_near_hotspot = [
        p
        for p in pings
        if p["speed_mps"] <= 5.0
        and probes_mod._dist_to_hotspot_m(p["lat"], p["lng"]) < probes_mod._HOT_RADIUS_M
    ]
    assert slow_near_hotspot, "expected a slow-moving congested hotspot"

    # determinism: same seed -> byte-identical output across two calls
    again = probes_mod.simulate_probes(n_drivers=30, now=NOW, minutes=10, seed=0)
    assert again == pings, "simulate_probes is not deterministic for a fixed seed"

    # a different seed should differ (genuinely seeded randomness)
    other = probes_mod.simulate_probes(n_drivers=30, now=NOW, minutes=10, seed=1)
    assert other != pings

    # ---- drivers are valid $defs/Driver, all consenting ------------------ #
    drivers = probes_mod.make_drivers(20, seed=1)
    assert len(drivers) == 20
    assert len({d["id"] for d in drivers}) == 20, "duplicate driver ids"
    for d in drivers:
        validate_entity("Driver", d)
        assert d["consent"] is True, "drivers in the flywheel must have consented"
        assert d["vehicle_type"] in ("bike", "scooter", "car", "van")

    assert probes_mod.make_drivers(20, seed=1) == drivers  # deterministic
