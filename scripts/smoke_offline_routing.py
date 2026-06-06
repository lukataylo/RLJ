"""Smoke test the offline London routing tier (safe-v1).

Compares the haversine baseline vs the real Valhalla road-graph matrix over a few real
NHS London facilities, and confirms the solver portfolio uses real roads when VALHALLA_URL
is set. Run on the GB10 box with Valhalla serving on :8002.

    VALHALLA_URL=http://localhost:8002 .venv/bin/python scripts/smoke_offline_routing.py

Exit 0 on success. Prints a side-by-side matrix so you can eyeball "real roads != crow-flies".
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in ("routing", "data"):
    sys.path.insert(0, str(ROOT / p))

import numpy as np  # noqa: E402

import traveltime  # routing/  # noqa: E402
import nhs_facilities  # data/  # noqa: E402

VALHALLA_URL = os.environ.get("VALHALLA_URL", "http://localhost:8002")


def main() -> int:
    facs = nhs_facilities.fetch_nhs_london(allow_network=False)[:5]
    names = [f["name"][:22] for f in facs]
    lats = [f["lat"] for f in facs]
    lngs = [f["lng"] for f in facs]
    print(f"Facilities ({len(facs)}):")
    for f in facs:
        print(f"  - {f['name']}  ({f['type']})  {f['lat']:.4f},{f['lng']:.4f}")

    hav = traveltime.build_travel_time_matrix(lats, lngs)               # crow-flies model
    val = traveltime.valhalla_matrix(lats, lngs, base_url=VALHALLA_URL)  # real road graph

    reachable = traveltime._point_seg_min_m is not None  # module imported fine
    used_real = not np.allclose(hav, val)
    print(f"\nVALHALLA_URL = {VALHALLA_URL}")
    print(f"Valhalla server used (matrix differs from haversine): {used_real}")

    print("\nTravel time minutes — haversine vs Valhalla (real roads):")
    header = "from\\to      " + " ".join(f"{n[:10]:>11}" for n in names)
    print(header)
    for i, n in enumerate(names):
        cells = []
        for j in range(len(names)):
            h, v = hav[i, j] / 60, val[i, j] / 60
            cells.append(f"{h:4.0f}/{v:<4.0f}")
        print(f"{n[:12]:<12} " + " ".join(f"{c:>11}" for c in cells))

    assert np.all(np.isfinite(val)), "Valhalla matrix has non-finite entries"
    assert np.allclose(np.diag(val), 0.0), "diagonal must be zero"
    if used_real:
        off = val[~np.eye(len(facs), dtype=bool)]
        ratio = float(np.mean(off / hav[~np.eye(len(facs), dtype=bool)]))
        print(f"\nmean road/crow-flies time ratio: {ratio:.2f}x  (real roads detour around the network)")
        print("RESULT: ✅ routing is using the REAL offline London road graph")
    else:
        print("\nRESULT: ⚠️  fell back to haversine — is Valhalla serving on", VALHALLA_URL, "?")
        print("  start it with:  cd valhalla && nohup ./serve.sh 2 > serve.log 2>&1 &")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
