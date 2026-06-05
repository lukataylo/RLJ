"""Real London NHS-type facilities (offline-safe, bundled literal).

~25 well-known London hospitals, GP surgeries, pathology labs and pharmacies
with approximate real coordinates. Coordinates are hand-checked to sit inside
the Greater-London bbox defined in ``quality.LONDON_BBOX``.

By default we use the bundled literal so the demo always works with no network.
``build_facilities(allow_network=True)`` will *try* an NHS ODS fetch first and
silently fall back to the bundle if anything is unreachable.
"""
from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent
FACILITIES_PATH = DATA_DIR / "facilities.json"

# id, name, type, lat, lng  — real names, approximate real coords.
BUNDLED_FACILITIES: list[dict] = [
    # ---- hospitals -------------------------------------------------------- #
    {"id": "RJ1-STH", "name": "St Thomas' Hospital", "type": "hospital", "lat": 51.4980, "lng": -0.1188},
    {"id": "RJ1-GUY", "name": "Guy's Hospital", "type": "hospital", "lat": 51.5033, "lng": -0.0875},
    {"id": "R1H-RLH", "name": "Royal London Hospital", "type": "hospital", "lat": 51.5190, "lng": -0.0590},
    {"id": "RRV-UCH", "name": "University College Hospital (UCLH)", "type": "hospital", "lat": 51.5246, "lng": -0.1357},
    {"id": "RJZ-KCH", "name": "King's College Hospital", "type": "hospital", "lat": 51.4685, "lng": -0.0937},
    {"id": "RRV-BART", "name": "St Bartholomew's Hospital", "type": "hospital", "lat": 51.5176, "lng": -0.1003},
    {"id": "RYJ-CXH", "name": "Charing Cross Hospital", "type": "hospital", "lat": 51.4870, "lng": -0.2186},
    {"id": "RAL-RFH", "name": "Royal Free Hospital", "type": "hospital", "lat": 51.5530, "lng": -0.1647},
    {"id": "RQM-CWH", "name": "Chelsea and Westminster Hospital", "type": "hospital", "lat": 51.4842, "lng": -0.1817},
    {"id": "RYJ-SMH", "name": "St Mary's Hospital, Paddington", "type": "hospital", "lat": 51.5170, "lng": -0.1736},
    {"id": "RYJ-HMH", "name": "Hammersmith Hospital", "type": "hospital", "lat": 51.5167, "lng": -0.2360},
    {"id": "RKE-WHT", "name": "Whittington Hospital", "type": "hospital", "lat": 51.5658, "lng": -0.1390},
    {"id": "RQX-HOM", "name": "Homerton University Hospital", "type": "hospital", "lat": 51.5497, "lng": -0.0445},
    # ---- pathology / labs ------------------------------------------------- #
    {"id": "LAB-HSL", "name": "Health Services Laboratories (The Halo Building)", "type": "lab", "lat": 51.5290, "lng": -0.1200},
    {"id": "LAB-SYN", "name": "Synnovis Pathology (Guy's)", "type": "lab", "lat": 51.5030, "lng": -0.0882},
    {"id": "LAB-TDL", "name": "The Doctors Laboratory (TDL)", "type": "lab", "lat": 51.5210, "lng": -0.1390},
    {"id": "LAB-VPK", "name": "Viapath North Pathology Hub", "type": "lab", "lat": 51.4690, "lng": -0.0930},
    # ---- GP surgeries / clinics ------------------------------------------ #
    {"id": "GP-HURLEY", "name": "The Hurley Clinic", "type": "gp", "lat": 51.4920, "lng": -0.1100},
    {"id": "GP-SPF", "name": "Spitalfields Practice", "type": "gp", "lat": 51.5190, "lng": -0.0750},
    {"id": "GP-BLOOM", "name": "Bloomsbury Surgery", "type": "gp", "lat": 51.5230, "lng": -0.1280},
    {"id": "GP-HAMP", "name": "Hampstead Group Practice", "type": "gp", "lat": 51.5550, "lng": -0.1780},
    {"id": "CL-VICT", "name": "Victoria Medical Centre", "type": "clinic", "lat": 51.4935, "lng": -0.1420},
    # ---- pharmacies ------------------------------------------------------- #
    {"id": "PH-BOOTS-PIC", "name": "Boots Pharmacy, Piccadilly Circus", "type": "pharmacy", "lat": 51.5098, "lng": -0.1342},
    {"id": "PH-JBC", "name": "John Bell & Croyden Pharmacy", "type": "pharmacy", "lat": 51.5176, "lng": -0.1510},
    {"id": "PH-ZAFASH", "name": "Zafash 24hr Pharmacy", "type": "pharmacy", "lat": 51.4910, "lng": -0.1930},
    {"id": "PH-BLISS", "name": "Bliss Chemist, Marble Arch", "type": "pharmacy", "lat": 51.5135, "lng": -0.1600},
]


def build_facilities(allow_network: bool = False) -> list[dict]:
    """Return the facility list. Bundled by default; optionally try NHS ODS."""
    if allow_network:
        fetched = _try_fetch_ods()
        if fetched:
            return fetched
    return [dict(f) for f in BUNDLED_FACILITIES]


def _try_fetch_ods() -> list[dict] | None:
    """Best-effort NHS ODS fetch. Returns None on any failure (stays offline)."""
    try:  # pragma: no cover - network path not exercised in CI
        import requests

        url = "https://directory.spineservices.nhs.uk/ORD/2-0-0/organisations"
        resp = requests.get(url, params={"Limit": 25}, timeout=3)
        resp.raise_for_status()
        # ODS payload shape is non-trivial; we deliberately do NOT trust it for
        # coordinates (the API does not return lat/lng), so we keep the bundle.
        return None
    except Exception:
        return None


def write_facilities(path: Path | str = FACILITIES_PATH, allow_network: bool = False) -> list[dict]:
    facilities = build_facilities(allow_network=allow_network)
    Path(path).write_text(json.dumps(facilities, indent=2) + "\n")
    return facilities


if __name__ == "__main__":
    fac = write_facilities()
    print(f"wrote {len(fac)} facilities -> {FACILITIES_PATH}")
