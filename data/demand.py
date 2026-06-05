"""Deterministic synthetic demand generator -> schema-valid DeliveryJob[].

Time windows are anchored to a supplied ``now`` so the demo's clinical
deadlines are always relative to the scenario clock:

  * ready_at : now .. now+30min
  * due_by   : ready_at + a priority-dependent clinical window
        stat    ~ 45-75 min   (drop everything)
        urgent  ~ 110-140 min (~2h)
        routine ~ 170-195 min (~3h)

Priority mix ~ 20% stat / 30% urgent / 50% routine. Deterministic given seed.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import facilities as facilities_mod
import quality

DATA_DIR = Path(__file__).resolve().parent
DEMAND_PATH = DATA_DIR / "demand.json"

# A fixed scenario clock for the committed snapshot (08:00 UTC, demo morning).
SNAPSHOT_NOW = "2026-06-05T08:00:00+00:00"

_PRIORITIES = ["stat", "urgent", "routine"]
_PRIORITY_WEIGHTS = [0.20, 0.30, 0.50]

# Clinical window (minutes from ready_at) drawn per priority; stays inside the
# bounds asserted by quality.validate_demand.
_WINDOW_MIN = {"stat": (45, 70), "urgent": (110, 140), "routine": (170, 195)}


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


def _location(facility: dict) -> dict:
    return {
        "lat": facility["lat"],
        "lng": facility["lng"],
        "name": facility["name"],
        "facility_id": facility["id"],
    }


def _residential_point(rng: random.Random) -> dict:
    """A plausible residential drop-off inside central London (no facility id)."""
    b = quality.LONDON_BBOX
    # keep within a tighter central band so points read as urban deliveries
    lat = rng.uniform(b["lat_min"] + 0.10, b["lat_max"] - 0.10)
    lng = rng.uniform(b["lng_min"] + 0.18, b["lng_max"] - 0.18)
    return {"lat": round(lat, 5), "lng": round(lng, 5), "name": "Patient residence"}


def generate_demand(n: int = 30, seed: int = 7, now=SNAPSHOT_NOW) -> list[dict]:
    """Return ``n`` schema-valid DeliveryJob dicts anchored to ``now``."""
    rng = random.Random(seed)
    now_dt = _parse_now(now)
    fac = facilities_mod.build_facilities()

    by_type: dict[str, list[dict]] = {}
    for f in fac:
        by_type.setdefault(f["type"], []).append(f)

    origins_sample = by_type.get("gp", []) + by_type.get("clinic", [])
    labs = by_type.get("lab", []) + by_type.get("hospital", [])
    pharmacies = by_type.get("pharmacy", [])

    jobs: list[dict] = []
    for i in range(n):
        priority = rng.choices(_PRIORITIES, weights=_PRIORITY_WEIGHTS, k=1)[0]
        # sample_pickup (clinic->lab) is the majority for a pathology courier.
        job_type = "sample_pickup" if rng.random() < 0.65 else "med_delivery"

        if job_type == "sample_pickup":
            origin = _location(rng.choice(origins_sample))
            destination = _location(rng.choice(labs))
            cold_chain = rng.random() < 0.85  # samples mostly need cold chain
        else:
            origin = _location(rng.choice(pharmacies))
            destination = _residential_point(rng)
            cold_chain = rng.random() < 0.25  # some meds (e.g. insulin) chilled

        ready_offset = timedelta(minutes=rng.randint(0, 30))
        ready_at = now_dt + ready_offset
        lo, hi = _WINDOW_MIN[priority]
        due_by = ready_at + timedelta(minutes=rng.randint(lo, hi))

        job = {
            "id": f"job-{i:04d}",
            "type": job_type,
            "origin": origin,
            "destination": destination,
            "priority": priority,
            "time_window": {"ready_at": _iso(ready_at), "due_by": _iso(due_by)},
            "cold_chain": cold_chain,
            "capacity_units": rng.choice([1, 1, 1, 2]),
            "status": "new",
            "created_at": _iso(now_dt),
            "raw_text": _raw_text(job_type, priority, origin, destination),
        }
        jobs.append(job)
    return jobs


def _raw_text(job_type: str, priority: str, origin: dict, destination: dict) -> str:
    if job_type == "sample_pickup":
        return (
            f"{priority.upper()} sample pickup from {origin['name']} "
            f"to {destination['name']}"
        )
    return f"{priority.upper()} medication delivery from {origin['name']} to patient"


def write_demand(
    path: Path | str = DEMAND_PATH,
    n: int = 30,
    seed: int = 7,
    now=SNAPSHOT_NOW,
) -> list[dict]:
    jobs = generate_demand(n=n, seed=seed, now=now)
    # validate before persisting — never write unverified demand to disk.
    quality.validate_demand(jobs, now=now)
    Path(path).write_text(json.dumps(jobs, indent=2) + "\n")
    return jobs


if __name__ == "__main__":
    j = write_demand()
    print(f"wrote {len(j)} jobs (now={SNAPSHOT_NOW}) -> {DEMAND_PATH}")
