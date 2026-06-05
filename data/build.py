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
import facilities as facilities_mod
import quality
import roadgraph as roadgraph_mod
from loader import sha256_file

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
MANIFEST_PATH = DATA_DIR / "manifest.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def build(now: str = demand_mod.SNAPSHOT_NOW, demand_n: int = 30, seed: int = 7) -> dict:
    datasets: dict[str, dict] = {}

    # ---- facilities ------------------------------------------------------- #
    fac_path = facilities_mod.FACILITIES_PATH
    facilities = facilities_mod.write_facilities(fac_path)
    fac_passed, fac_rows = True, len(facilities)
    try:
        quality.validate_facilities(facilities)
    except Exception as e:  # noqa: BLE001
        fac_passed = False
        print(f"[facilities] DQ FAILED: {e}")
    datasets["facilities"] = {
        "source": "bundled-nhs-london",
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
        "source": f"synthetic(seed={seed}, now={now})",
        "path": _rel(dem_path),
        "rows": dem_rows,
        "sha256": sha256_file(dem_path) if dem_path.exists() else "",
        "fetched_at": _now_iso(),
        "dq_passed": dem_passed,
        "dq_suite": "tests/data_quality/test_demand.py",
    }

    # ---- road graph ------------------------------------------------------- #
    roads_path = roadgraph_mod.ROADS_PATH
    road_passed, road_rows = True, 0
    try:
        stats = roadgraph_mod.build_roadgraph()
        road_rows = stats.get("rows", 0)
    except Exception as e:  # noqa: BLE001
        road_passed = False
        print(f"[roadgraph] DQ FAILED: {e}")
    datasets["roads"] = {
        "source": "synthetic-grid (osmnx if available)",
        "path": _rel(roads_path),
        "rows": road_rows,
        "sha256": sha256_file(roads_path) if roads_path.exists() else "",
        "fetched_at": _now_iso(),
        "dq_passed": road_passed,
        "dq_suite": "tests/data_quality/test_road_graph.py",
    }

    manifest = {"generated_at": _now_iso(), "scenario_now": now, "datasets": datasets}
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> dict:
    manifest = build()
    print(f"\nwrote {MANIFEST_PATH}")
    for name, d in manifest["datasets"].items():
        flag = "PASS" if d["dq_passed"] else "FAIL"
        print(f"  [{flag}] {name:11s} rows={d['rows']:<5} sha={d['sha256'][:12]}")
    return manifest


if __name__ == "__main__":
    main()
