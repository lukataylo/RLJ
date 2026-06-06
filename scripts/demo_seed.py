"""Seed the running orchestrator with a now-anchored demo scenario.

Unlike orchestrator/seed.py (which replays the fixed-date contract sample), this anchors
all time windows to the current clock, so the live UI shows realistic ETAs and a road
closure visibly re-routes. Use this for the live demo.

    cd orchestrator && uvicorn app:app --port 8000    # (+ routing on :8100 for GPU ACO)
    python scripts/demo_seed.py
"""
from __future__ import annotations
import sys
from datetime import datetime, timedelta, timezone

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"

DEPOTS = [(51.5079, -0.0877, "London Bridge depot"), (51.5246, -0.1340, "Euston depot"),
          (51.5155, -0.0922, "Liverpool St depot")]
LABS = [(51.4980, -0.1188, "St Thomas' lab"), (51.5030, -0.0884, "Guy's lab"),
        (51.5246, -0.1357, "UCLH lab")]
PICKS = [(51.5290, -0.1225, "Somers Town surgery"), (51.5185, -0.0731, "Royal London pharmacy"),
         (51.5410, -0.1430, "Camden clinic"), (51.5141, -0.0590, "Bethnal Green surgery"),
         (51.5203, -0.1050, "Clerkenwell pharmacy"), (51.4925, -0.1465, "Pimlico surgery"),
         (51.5331, -0.1050, "Islington clinic"), (51.4769, -0.1110, "Oval health centre")]
WINS = {"stat": 70, "urgent": 130, "routine": 190}
MIX = ["stat", "urgent", "routine", "routine", "urgent", "routine", "stat", "routine"]


def main():
    now = datetime.now(timezone.utc)
    with httpx.Client(base_url=BASE, timeout=10) as c:
        # mix of vans (cold-capable, higher capacity) and scooters (faster, no fridge)
        fleet = [("van", 6, True), ("scooter", 3, False), ("van", 6, True)]
        for i, (la, lo, n) in enumerate(DEPOTS):
            vt, cap, cold = fleet[i % len(fleet)]
            label = "Van" if vt == "van" else "Scooter"
            c.post("/couriers", json={"id": f"crt-{i+1}", "name": f"{label} {chr(65+i)}",
                                      "capacity": cap, "cold_capable": cold,
                                      "vehicle_type": vt, "status": "idle",
                                      "location": {"lat": la, "lng": lo, "name": n},
                                      "phone": f"+44700900{i:03d}"})
        for i in range(8):
            p, l, pr = PICKS[i], LABS[i % len(LABS)], MIX[i]
            c.post("/jobs", json={
                "id": f"job-{i+1}", "type": "sample_pickup", "priority": pr,
                "cold_chain": i % 4 != 3, "capacity_units": 1, "status": "new",
                "origin": {"lat": p[0], "lng": p[1], "name": p[2]},
                "destination": {"lat": l[0], "lng": l[1], "name": l[2]},
                "time_window": {"ready_at": now.isoformat(),
                                "due_by": (now + timedelta(minutes=WINS[pr])).isoformat()},
                "raw_text": f"{pr} sample {p[2]} -> {l[2]}"})
        plan = c.get("/plan").json()
        print("seeded:", plan["objective"])


if __name__ == "__main__":
    main()
