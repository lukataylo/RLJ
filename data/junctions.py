"""London signalised junctions (SCOOT/UTC style) + green-wave advice.

Bundles ~30 real central-London signalised junctions / gyratories with
approximate real coordinates (all inside ``quality.LONDON_BBOX``) and a
*deterministic* per-junction signal model:

    {id, name, lat, lng, cycle_s, green_s, offset_s}

* ``cycle_s``  : full signal cycle length, 60-120 s (typical urban UTC range).
* ``green_s``  : green time for the modelled approach (~30-55 % of the cycle).
* ``offset_s`` : phase offset — green is on during
                 ``(t - offset_s) mod cycle_s  <  green_s``.

The model is derived from a stable md5 hash of the junction id, so it is
identical across runs / machines (Python's builtin ``hash`` is salted and must
not be used for reproducible data).

``green_wave_advice(junction, distance_m, now_s, current_speed_mps)`` computes a
target speed that arrives at the next green and returns a ``SignalAdvice``-shaped
dict (contracts/schemas.json $defs/SignalAdvice; only ``message`` is required).
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent
JUNCTIONS_PATH = DATA_DIR / "junctions.json"

# Comfortable urban speed envelope for green-wave advice (m/s).
# 2 m/s ~ crawl, 13.4 m/s ~ 30 mph (the central-London limit).
V_MIN = 2.0
V_MAX = 13.4

# id, name, lat, lng — real central-London signalised junctions / gyratories.
_JUNCTIONS_RAW: list[dict] = [
    {"id": "jct-hyde-park-corner", "name": "Hyde Park Corner", "lat": 51.5027, "lng": -0.1527},
    {"id": "jct-marble-arch", "name": "Marble Arch", "lat": 51.5131, "lng": -0.1589},
    {"id": "jct-oxford-circus", "name": "Oxford Circus", "lat": 51.5152, "lng": -0.1418},
    {"id": "jct-piccadilly-circus", "name": "Piccadilly Circus", "lat": 51.5101, "lng": -0.1340},
    {"id": "jct-trafalgar-square", "name": "Trafalgar Square", "lat": 51.5080, "lng": -0.1281},
    {"id": "jct-parliament-square", "name": "Parliament Square", "lat": 51.5007, "lng": -0.1262},
    {"id": "jct-elephant-castle", "name": "Elephant and Castle", "lat": 51.4946, "lng": -0.1000},
    {"id": "jct-vauxhall-cross", "name": "Vauxhall Cross", "lat": 51.4861, "lng": -0.1253},
    {"id": "jct-aldgate", "name": "Aldgate", "lat": 51.5143, "lng": -0.0755},
    {"id": "jct-bank", "name": "Bank Junction", "lat": 51.5134, "lng": -0.0886},
    {"id": "jct-holborn-circus", "name": "Holborn Circus", "lat": 51.5180, "lng": -0.1090},
    {"id": "jct-ludgate-circus", "name": "Ludgate Circus", "lat": 51.5141, "lng": -0.1045},
    {"id": "jct-cambridge-circus", "name": "Cambridge Circus", "lat": 51.5128, "lng": -0.1287},
    {"id": "jct-st-giles-circus", "name": "St Giles Circus (Tottenham Court Rd)", "lat": 51.5165, "lng": -0.1308},
    {"id": "jct-warren-street", "name": "Warren Street (Euston Rd / TCR)", "lat": 51.5256, "lng": -0.1378},
    {"id": "jct-kings-cross", "name": "King's Cross", "lat": 51.5301, "lng": -0.1230},
    {"id": "jct-angel", "name": "Angel", "lat": 51.5322, "lng": -0.1058},
    {"id": "jct-old-street", "name": "Old Street Roundabout", "lat": 51.5256, "lng": -0.0876},
    {"id": "jct-shoreditch", "name": "Shoreditch High Street", "lat": 51.5240, "lng": -0.0775},
    {"id": "jct-liverpool-street", "name": "Liverpool Street", "lat": 51.5175, "lng": -0.0820},
    {"id": "jct-tower-hill", "name": "Tower Hill", "lat": 51.5095, "lng": -0.0759},
    {"id": "jct-london-bridge", "name": "London Bridge", "lat": 51.5074, "lng": -0.0877},
    {"id": "jct-borough", "name": "Borough High Street / Marshalsea", "lat": 51.5010, "lng": -0.0935},
    {"id": "jct-waterloo-imax", "name": "Waterloo IMAX Roundabout", "lat": 51.5031, "lng": -0.1135},
    {"id": "jct-lambeth-bridge", "name": "Lambeth Bridge (north)", "lat": 51.4944, "lng": -0.1240},
    {"id": "jct-victoria", "name": "Victoria", "lat": 51.4952, "lng": -0.1441},
    {"id": "jct-sloane-square", "name": "Sloane Square", "lat": 51.4924, "lng": -0.1565},
    {"id": "jct-knightsbridge", "name": "Knightsbridge", "lat": 51.5015, "lng": -0.1606},
    {"id": "jct-notting-hill-gate", "name": "Notting Hill Gate", "lat": 51.5090, "lng": -0.1960},
    {"id": "jct-shepherds-bush", "name": "Shepherd's Bush Green", "lat": 51.5046, "lng": -0.2187},
]


def _signal_model(jct_id: str) -> dict:
    """Derive a deterministic {cycle_s, green_s, offset_s} from the junction id."""
    h = int(hashlib.md5(jct_id.encode("utf-8")).hexdigest(), 16)
    cycle_s = 60 + (h % 61)                       # 60 .. 120
    green_frac = 0.30 + ((h >> 8) % 26) / 100.0   # 0.30 .. 0.55 of the cycle
    green_s = max(8, int(round(cycle_s * green_frac)))
    offset_s = (h >> 16) % cycle_s                # 0 .. cycle-1
    return {"cycle_s": cycle_s, "green_s": green_s, "offset_s": offset_s}


def junctions() -> list[dict]:
    """Return the bundled junctions, each with its deterministic signal model."""
    out: list[dict] = []
    for j in _JUNCTIONS_RAW:
        model = _signal_model(j["id"])
        out.append(
            {
                "id": j["id"],
                "name": j["name"],
                "lat": j["lat"],
                "lng": j["lng"],
                "cycle_s": model["cycle_s"],
                "green_s": model["green_s"],
                "offset_s": model["offset_s"],
            }
        )
    return out


def is_green(junction: dict, t_s: float) -> bool:
    """True iff the junction's modelled approach shows green at absolute time ``t_s``."""
    cycle = float(junction["cycle_s"])
    phase = (t_s - float(junction["offset_s"])) % cycle
    return phase < float(junction["green_s"])


def _seconds_to_next_green(junction: dict, t_s: float) -> float:
    """Seconds from ``t_s`` until the start of the next green (0.0 if green now)."""
    cycle = float(junction["cycle_s"])
    phase = (t_s - float(junction["offset_s"])) % cycle
    if phase < float(junction["green_s"]):
        return 0.0
    return cycle - phase


def green_wave_advice(
    junction: dict,
    distance_m: float,
    now_s: float,
    current_speed_mps: float,
) -> dict:
    """Speed to arrive at ``junction`` on the next green — a ``SignalAdvice`` dict.

    Args:
        junction: a junction dict from :func:`junctions`.
        distance_m: metres from the driver to the junction stop-line.
        now_s: current absolute time, seconds (same clock as the signal model).
        current_speed_mps: the driver's current speed, m/s.

    Returns a dict shaped like ``$defs/SignalAdvice`` with keys
    ``message, target_speed_mps, junction, seconds_to_green, confidence``.
    """
    cycle = float(junction["cycle_s"])
    green = float(junction["green_s"])
    offset = float(junction["offset_s"])
    name = junction.get("name", "the junction")
    loc = {"lat": junction["lat"], "lng": junction["lng"], "name": name}

    cruise = current_speed_mps if (current_speed_mps and current_speed_mps > 0) else 6.0

    # Already at / past the stop-line: just report the current signal state.
    if distance_m <= 0:
        s_to_green = _seconds_to_next_green(junction, now_s)
        if s_to_green <= 0:
            msg = f"Green now at {name} — proceed."
        else:
            msg = f"Red at {name} — green in {s_to_green:.0f}s."
        return {
            "message": msg,
            "target_speed_mps": round(cruise, 2),
            "junction": loc,
            "seconds_to_green": round(s_to_green, 1),
            "confidence": 0.5,
        }

    eta = distance_m / cruise  # natural arrival time at current speed

    # Scan the next few green windows and pick the earliest one we can reach
    # within the comfortable speed envelope, with the smallest speed change.
    k0 = math.floor((now_s - offset) / cycle)
    best: dict | None = None
    for k in range(k0, k0 + 6):
        t_g0 = offset + k * cycle          # absolute green start
        t_g1 = t_g0 + green                # absolute green end
        lo_t = t_g0 - now_s                # earliest arrival (sec from now)
        hi_t = t_g1 - now_s                # latest arrival (sec from now)
        if hi_t <= 0:
            continue  # this green window has already fully passed
        # Feasible travel-time window: inside the green AND inside the speed envelope.
        t_lo = max(lo_t, distance_m / V_MAX)
        t_hi = min(hi_t, distance_m / V_MIN)
        if t_lo > t_hi:
            continue  # cannot reach this green within the speed envelope
        # Choose the travel time closest to the natural ETA (smoothest change).
        t_travel = min(max(eta, t_lo), t_hi)
        target = distance_m / t_travel
        s_to_green = max(0.0, lo_t)
        dev = abs(target - cruise) / V_MAX
        confidence = max(0.3, min(0.95, 0.9 - dev)) * max(0.5, 1.0 - (k - k0) * 0.1)
        best = {
            "target": target,
            "seconds_to_green": s_to_green,
            "confidence": confidence,
        }
        break

    if best is None:
        # No reachable green in the scan horizon — advise a steady cruise.
        s_to_green = _seconds_to_next_green(junction, now_s)
        return {
            "message": f"Hold a steady speed approaching {name}.",
            "target_speed_mps": round(min(cruise, V_MAX), 2),
            "junction": loc,
            "seconds_to_green": round(s_to_green, 1),
            "confidence": 0.3,
        }

    target = best["target"]
    target_kmh = target * 3.6
    if target > cruise + 0.5:
        verb = f"Speed up to ~{target_kmh:.0f} km/h"
    elif target < cruise - 0.5:
        verb = f"Ease off to ~{target_kmh:.0f} km/h"
    else:
        verb = f"Maintain ~{target_kmh:.0f} km/h"
    msg = f"{verb} to catch the green at {name} (in {best['seconds_to_green']:.0f}s)."

    return {
        "message": msg,
        "target_speed_mps": round(target, 2),
        "junction": loc,
        "seconds_to_green": round(best["seconds_to_green"], 1),
        "confidence": round(best["confidence"], 2),
    }


def write_junctions(path: Path | str = JUNCTIONS_PATH) -> list[dict]:
    js = junctions()
    Path(path).write_text(json.dumps(js, indent=2) + "\n")
    return js


if __name__ == "__main__":
    js = write_junctions()
    print(f"wrote {len(js)} junctions -> {JUNCTIONS_PATH}")
