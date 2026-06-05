"""Simulated crowdsourced driver GPS — the raw material of the congestion flywheel.

Deterministic, offline simulation of consenting drivers moving between random
central-London points, emitting a GPS probe (~every 30 s). Speeds are realistic
(2-12 m/s) and deliberately slower inside a central congested zone around
(51.515, -0.12), so the aggregated field shows a believable hotspot.

* ``make_drivers(n, seed)``        -> list of ``$defs/Driver`` dicts (consent True).
* ``simulate_probes(n_drivers, now, minutes=10, seed=0)``
                                   -> list of ``$defs/DriverPing`` dicts.

Determinism: a single ``random.Random(seed)`` drives the whole simulation, so
the same ``(n_drivers, now, minutes, seed)`` always yields byte-identical pings.
"""
from __future__ import annotations

import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent
PROBES_SNAPSHOT_PATH = DATA_DIR / "probes_snapshot.json"

# Fixed scenario clock + seed for the committed snapshot (matches demand.py).
SNAPSHOT_NOW = "2026-06-05T08:00:00+00:00"
SNAPSHOT_SEED = 0
SNAPSHOT_DRIVERS = 40

PING_INTERVAL_S = 30

# Central-London trip box for random origins/destinations (well inside the bbox).
_TRIP_LAT = (51.495, 51.535)
_TRIP_LNG = (-0.170, -0.070)

# The congested hotspot: drivers within ~900 m crawl (2-5 m/s); elsewhere flow
# is brisker (6-12 m/s).
_HOT_LAT = 51.515
_HOT_LNG = -0.120
_HOT_RADIUS_M = 900.0
_SLOW_RANGE = (2.0, 5.0)
_FREE_RANGE = (6.0, 12.0)

_VEHICLE_TYPES = ("bike", "scooter", "car", "van")

_M_PER_DEG_LAT = 111_320.0


def _m_per_deg_lng(lat: float) -> float:
    return 111_320.0 * math.cos(math.radians(lat))


def _parse_now(now) -> datetime:
    if isinstance(now, datetime):
        dt = now
    else:
        dt = datetime.fromisoformat(str(now).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _dist_to_hotspot_m(lat: float, lng: float) -> float:
    dy = (lat - _HOT_LAT) * _M_PER_DEG_LAT
    dx = (lng - _HOT_LNG) * _m_per_deg_lng(lat)
    return math.hypot(dx, dy)


def _rand_point(rng: random.Random) -> tuple[float, float]:
    return (
        rng.uniform(*_TRIP_LAT),
        rng.uniform(*_TRIP_LNG),
    )


def make_drivers(n: int, seed: int = 0) -> list[dict]:
    """Return ``n`` schema-valid ``$defs/Driver`` dicts, all with ``consent=True``."""
    rng = random.Random(seed)
    joined = "2026-06-01T00:00:00+00:00"
    out: list[dict] = []
    for i in range(n):
        out.append(
            {
                "id": f"drv-{i:04d}",
                "name": f"Driver {i:04d}",
                "vehicle_type": _VEHICLE_TYPES[rng.randrange(len(_VEHICLE_TYPES))],
                "consent": True,
                "joined_at": joined,
                "points": rng.randint(0, 500),
            }
        )
    return out


def simulate_probes(
    n_drivers: int,
    now,
    minutes: int = 10,
    seed: int = 0,
) -> list[dict]:
    """Simulate ``n_drivers`` over ``minutes``, one ping every ~30 s per driver.

    Returns a flat list of ``$defs/DriverPing`` dicts ordered by driver then time.
    Deterministic for a given ``(n_drivers, now, minutes, seed)``.
    """
    rng = random.Random(seed)
    now_dt = _parse_now(now)
    n_pings = max(1, int(minutes * 60 / PING_INTERVAL_S))

    pings: list[dict] = []
    for i in range(n_drivers):
        driver_id = f"drv-{i:04d}"
        lat, lng = _rand_point(rng)
        dest_lat, dest_lng = _rand_point(rng)

        for k in range(n_pings):
            # current step speed depends on proximity to the hotspot
            if _dist_to_hotspot_m(lat, lng) < _HOT_RADIUS_M:
                speed = rng.uniform(*_SLOW_RANGE)
            else:
                speed = rng.uniform(*_FREE_RANGE)

            # bearing toward the destination (east, north components in metres)
            east = (dest_lng - lng) * _m_per_deg_lng(lat)
            north = (dest_lat - lat) * _M_PER_DEG_LAT
            dist = math.hypot(east, north)
            heading = (math.degrees(math.atan2(east, north))) % 360.0

            ts = now_dt + timedelta(seconds=k * PING_INTERVAL_S)
            pings.append(
                {
                    "driver_id": driver_id,
                    "lat": round(lat, 6),
                    "lng": round(lng, 6),
                    "speed_mps": round(speed, 2),
                    "heading_deg": round(heading, 1),
                    "ts": _iso(ts),
                }
            )

            # advance along the bearing by speed * dt metres (clamp at the dest)
            move_m = speed * PING_INTERVAL_S
            if dist <= 1e-6 or move_m >= dist:
                # arrived (or already there): hop to a fresh destination
                lat, lng = dest_lat, dest_lng
                dest_lat, dest_lng = _rand_point(rng)
            else:
                frac = move_m / dist
                lat += (north * frac) / _M_PER_DEG_LAT
                lng += (east * frac) / _m_per_deg_lng(lat)
    return pings


def write_snapshot(
    path: Path | str = PROBES_SNAPSHOT_PATH,
    n_drivers: int = SNAPSHOT_DRIVERS,
    now: str = SNAPSHOT_NOW,
    minutes: int = 10,
    seed: int = SNAPSHOT_SEED,
) -> list[dict]:
    pings = simulate_probes(n_drivers=n_drivers, now=now, minutes=minutes, seed=seed)
    Path(path).write_text(json.dumps(pings, indent=2) + "\n")
    return pings


if __name__ == "__main__":
    ps = write_snapshot()
    print(f"wrote {len(ps)} probe pings -> {PROBES_SNAPSHOT_PATH}")
