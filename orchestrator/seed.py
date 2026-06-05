"""Seed the running orchestrator with demo couriers + jobs from the sample payload.
Usage:  python seed.py   (orchestrator must be running on :8000)
"""
import json, pathlib, httpx

BASE = "http://localhost:8000"
sample = json.loads((pathlib.Path(__file__).parent.parent /
                     "contracts/samples/optimize_request.json").read_text())

with httpx.Client(timeout=10) as c:
    for crt in sample["couriers"]:
        c.post(f"{BASE}/couriers", json=crt)
    for job in sample["jobs"]:
        c.post(f"{BASE}/jobs", json=job)
    print("seeded:", c.get(f"{BASE}/plan").json()["objective"])
