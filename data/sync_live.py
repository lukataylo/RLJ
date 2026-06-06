"""Fetch live London feeds and write a verified-ish demo snapshot.

This is intentionally not part of ``make data`` because the main data gate must
stay deterministic/offline. Run it when the demo box has network access:

    python data/sync_live.py
"""
from __future__ import annotations

import json
from pathlib import Path

import integrations

DATA_DIR = Path(__file__).resolve().parent
LIVE_DIR = DATA_DIR / "live"
SNAPSHOT_PATH = LIVE_DIR / "london-open-data-snapshot.json"


def main() -> dict:
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = integrations.fetch_live_snapshot()
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2) + "\n")
    print(f"wrote {SNAPSHOT_PATH}")
    print(f"  tfl disruptions : {len(snapshot['tfl_disruptions'])}")
    print(f"  bike points      : {len(snapshot['tfl_bike_points'])}")
    print(f"  tube statuses    : {len(snapshot['tfl_line_status'])}")
    print(f"  air sites        : {len(snapshot['london_air'])}")
    print(f"  datastore hits   : {len(snapshot['london_datastore'])}")
    return snapshot


if __name__ == "__main__":
    main()
