"""Build + verify every dataset, then write data/manifest.json.

For each dataset we:
  1. generate the artifact (facilities / demand / road graph),
  2. run the shared ``quality.py`` validators on it,
  3. compute sha256 + row count,
  4. record dq_passed (= did the validators pass) and the bound dq_suite.

``make data`` runs this (python data/build.py). The loader then refuses to
serve anything whose dq_passed is not true.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import demand as demand_mod
import events as events_mod
import facilities as facilities_mod
import junctions as junctions_mod
import probes as probes_mod
import quality
import roadgraph as roadgraph_mod
import signals as signals_mod
import towerbridge as towerbridge_mod
import weather as weather_mod
from loader import sha256_file

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
MANIFEST_PATH = DATA_DIR / "manifest.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def build(
    now: str = demand_mod.SNAPSHOT_NOW,
    demand_n: int = 30,
    seed: int = 7,
    allow_network: bool = True,
) -> dict:
    datasets: dict[str, dict] = {}

    # ---- facilities (LIVE: NHS ODS + postcodes.io, bundled fallback) ------- #
    fac_path = facilities_mod.FACILITIES_PATH
    facilities, fac_live = facilities_mod.write_facilities(fac_path, allow_network=allow_network)
    fac_passed, fac_rows = True, len(facilities)
    try:
        quality.validate_facilities(facilities)
    except Exception as e:  # noqa: BLE001
        fac_passed = False
        print(f"[facilities] DQ FAILED: {e}")
    datasets["facilities"] = {
        "source": "live-with-fallback",
        "live": fac_live,
        "provider": "NHS ODS + postcodes.io" if fac_live else "bundled-nhs-london",
        "path": _rel(fac_path),
        "rows": fac_rows,
        "sha256": sha256_file(fac_path),
        "fetched_at": _now_iso(),
        "dq_passed": fac_passed,
        "dq_suite": "tests/data_quality/test_facilities.py",
    }

    # ---- demand ----------------------------------------------------------- #
    dem_path = demand_mod.DEMAND_PATH
    dem_passed, dem_rows = True, 0
    try:
        jobs = demand_mod.write_demand(dem_path, n=demand_n, seed=seed, now=now)
        dem_rows = len(jobs)
        quality.validate_demand(jobs, now=now)
    except Exception as e:  # noqa: BLE001
        dem_passed = False
        print(f"[demand] DQ FAILED: {e}")
        # still emit whatever was generated for transparency
        if dem_path.exists():
            dem_rows = len(json.loads(dem_path.read_text()))
    datasets["demand"] = {
        "source": "synthetic-test-fixture",
        "detail": f"synthetic(seed={seed}, now={now})",
        "map_display": False,
        "path": _rel(dem_path),
        "rows": dem_rows,
        "sha256": sha256_file(dem_path) if dem_path.exists() else "",
        "fetched_at": _now_iso(),
        "dq_passed": dem_passed,
        "dq_suite": "tests/data_quality/test_demand.py",
    }

    # ---- road graph (LIVE: Overpass/OpenStreetMap, synthetic fallback) ----- #
    roads_path = roadgraph_mod.ROADS_PATH
    road_passed, road_rows, road_live, road_detail = True, 0, False, ""
    try:
        stats = roadgraph_mod.build_roadgraph(allow_network=allow_network)
        road_rows = stats.get("rows", 0)
        road_live = bool(stats.get("live", False))
        road_detail = stats.get("source", "")
    except Exception as e:  # noqa: BLE001
        road_passed = False
        print(f"[roadgraph] DQ FAILED: {e}")
    datasets["roads"] = {
        "source": "live-with-fallback",
        "live": road_live,
        "provider": road_detail or "overpass-osm / synthetic-grid-fallback",
        "path": _rel(roads_path),
        "rows": road_rows,
        "sha256": sha256_file(roads_path) if roads_path.exists() else "",
        "fetched_at": _now_iso(),
        "dq_passed": road_passed,
        "dq_suite": "tests/data_quality/test_road_graph.py",
    }

    # ---- signals: Tower Bridge lift schedule ------------------------------ #
    sample_date = now[:10]  # validate the scenario day
    tb_path = towerbridge_mod.TOWERBRIDGE_PATH
    tb_passed, tb_rows = True, 0
    try:
        towerbridge_mod.write_towerbridge(tb_path)
        lifts = towerbridge_mod.lift_events(sample_date)
        tb_rows = len(lifts)
        quality.validate_timed_events(lifts)
        if not all(quality.is_fresh(l["fetched_at"], now=now) for l in lifts):
            raise AssertionError("Tower Bridge records are stale")
    except Exception as e:  # noqa: BLE001
        tb_passed = False
        print(f"[towerbridge] DQ FAILED: {e}")
    datasets["towerbridge"] = {
        "source": "scheduled",
        "path": _rel(tb_path),
        "rows": tb_rows,
        "sha256": sha256_file(tb_path) if tb_path.exists() else "",
        "fetched_at": towerbridge_mod.BUNDLE_FETCHED_AT,
        "dq_passed": tb_passed,
        "dq_suite": "tests/data_quality/test_signals.py",
    }

    # ---- signals: public-event congestion --------------------------------- #
    ev_path = events_mod.EVENTS_PATH
    ev_passed, ev_rows = True, 0
    try:
        events_mod.write_events(ev_path)
        ev_rows = len(events_mod.BUNDLED_EVENTS)
        quality.validate_timed_events(events_mod.event_disruptions(sample_date))
        # also validate the full merged signal timeline for the scenario day
        quality.validate_timed_events(signals_mod.timed_events(sample_date))
        if not quality.is_fresh(events_mod.BUNDLE_FETCHED_AT, now=now):
            raise AssertionError("event records are stale")
    except Exception as e:  # noqa: BLE001
        ev_passed = False
        print(f"[events] DQ FAILED: {e}")
    datasets["events"] = {
        "source": "scheduled",
        "path": _rel(ev_path),
        "rows": ev_rows,
        "sha256": sha256_file(ev_path) if ev_path.exists() else "",
        "fetched_at": events_mod.BUNDLE_FETCHED_AT,
        "dq_passed": ev_passed,
        "dq_suite": "tests/data_quality/test_signals.py",
    }

    # ---- junctions: signalised junctions + green-wave signal model -------- #
    jct_path = junctions_mod.JUNCTIONS_PATH
    jct_passed, jct_rows = True, 0
    try:
        js = junctions_mod.write_junctions(jct_path)
        jct_rows = len(js)
        quality.validate_junctions(js)
        # green_wave_advice must produce a usable SignalAdvice for a sample call.
        advice = junctions_mod.green_wave_advice(js[0], distance_m=200.0, now_s=1000.0, current_speed_mps=8.0)
        if not advice.get("message"):
            raise AssertionError("green_wave_advice produced no message")
    except Exception as e:  # noqa: BLE001
        jct_passed = False
        print(f"[junctions] DQ FAILED: {e}")
    datasets["junctions"] = {
        "source": "bundled-central-london-signals",
        "path": _rel(jct_path),
        "rows": jct_rows,
        "sha256": sha256_file(jct_path) if jct_path.exists() else "",
        "fetched_at": _now_iso(),
        "dq_passed": jct_passed,
        "dq_suite": "tests/data_quality/test_junctions.py",
    }

    # ---- weather: representative states + congestion multiplier ----------- #
    wx_path = weather_mod.WEATHER_PATH
    wx_passed, wx_rows = True, 0
    wx_source, wx_live, wx_fetched_at = weather_mod.SOURCE, False, weather_mod.BUNDLE_FETCHED_AT
    try:
        payload = weather_mod.write_weather(wx_path, allow_network=allow_network)
        wx_rows = len(payload.get("days", {}))
        wx_source = payload.get("source", weather_mod.SOURCE)
        wx_live = bool(payload.get("live", False))
        wx_fetched_at = payload.get("fetched_at", weather_mod.BUNDLE_FETCHED_AT)
        mult = weather_mod.congestion_multiplier(sample_date)
        if not (1.0 <= mult <= 1.8):
            raise AssertionError(f"congestion_multiplier {mult} outside [1.0, 1.8]")
        if weather_mod.weather_for(sample_date)["condition"] not in weather_mod.CONDITIONS:
            raise AssertionError("weather_for returned an unknown condition")
    except Exception as e:  # noqa: BLE001
        wx_passed = False
        print(f"[weather] DQ FAILED: {e}")
    datasets["weather"] = {
        "source": wx_source,
        "live": wx_live,
        "path": _rel(wx_path),
        "rows": wx_rows,
        "sha256": sha256_file(wx_path) if wx_path.exists() else "",
        "fetched_at": wx_fetched_at,
        "dq_passed": wx_passed,
        "dq_suite": "tests/data_quality/test_weather.py",
    }

    # ---- probes: crowdsourced driver GPS snapshot ------------------------- #
    pr_path = probes_mod.PROBES_SNAPSHOT_PATH
    pr_passed, pr_rows = True, 0
    try:
        pings = probes_mod.write_snapshot(pr_path, now=now)
        pr_rows = len(pings)
        quality.validate_pings(pings)
    except Exception as e:  # noqa: BLE001
        pr_passed = False
        print(f"[probes] DQ FAILED: {e}")
    datasets["probes"] = {
        "source": "synthetic-test-fixture",
        "detail": f"simulated(seed={probes_mod.SNAPSHOT_SEED}, drivers={probes_mod.SNAPSHOT_DRIVERS}, now={now})",
        "map_display": False,
        "path": _rel(pr_path),
        "rows": pr_rows,
        "sha256": sha256_file(pr_path) if pr_path.exists() else "",
        "fetched_at": _now_iso(),
        "dq_passed": pr_passed,
        "dq_suite": "tests/data_quality/test_probes.py",
    }

    manifest = {"generated_at": _now_iso(), "scenario_now": now, "datasets": datasets}
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> dict:
    manifest = build()
    print(f"\nwrote {MANIFEST_PATH}")
    for name, d in manifest["datasets"].items():
        flag = "PASS" if d["dq_passed"] else "FAIL"
        src = d.get("source", "")
        if d.get("live"):
            label = "live"
        elif src == "synthetic-test-fixture":
            label = "fixture"
        elif src == "live-with-fallback":
            label = "fallback"
        else:
            label = src or "bundled"
        print(f"  [{flag}] {name:11s} {label:18s} rows={d['rows']:<5} sha={d['sha256'][:12]}")
    return manifest


if __name__ == "__main__":
    main()
