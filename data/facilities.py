"""Real London NHS facilities — LIVE from the NHS ODS API, offline-safe fallback.

The build pipeline fetches REAL facilities from the NHS Organisation Data Service
(ODS) directory, geocodes their postcodes to lat/lng via the free postcodes.io
API, classifies each by its ODS role (gp / pharmacy / hospital / clinic) and
keeps only those inside ``quality.LONDON_BBOX``. If anything is unreachable we fall
back to the bundled literal of ~25 well-known London facilities with hand-checked
coordinates, so the demo / build / tests always work with no network.

``build_facilities(allow_network=True)`` performs the live fetch; the default is
``allow_network=False`` (the offline bundle) so deterministic consumers — the
demand generator and the data-quality unit tests — never touch the network.
"""
from __future__ import annotations

import json
from pathlib import Path

import quality

DATA_DIR = Path(__file__).resolve().parent
ROOT = DATA_DIR.parent
FACILITIES_PATH = DATA_DIR / "facilities.json"
FRONTEND_FACILITIES_PATH = ROOT / "frontend" / "public" / "data" / "facilities.json"

# ---- NHS ODS (live) ------------------------------------------------------- #
ODS_URL = "https://directory.spineservices.nhs.uk/ORD/2-0-0/organisations"
POSTCODES_URL = "https://api.postcodes.io/postcodes"
USER_AGENT = "RLJ-PulseGo-data-build/1.0 (central-London NHS facilities)"
# Central-London postcode districts to enumerate from ODS.
CENTRAL_POSTCODE_PREFIXES = (
    "EC1", "EC2", "EC3", "EC4", "WC1", "WC2",
    "SE1", "SW1", "W1", "NW1", "N1", "E1",
)
ODS_LIMIT = 100          # orgs requested per postcode district
MIN_FACILITIES = 20      # below this the live fetch is rejected -> fallback
MAX_FACILITIES = 60      # cap the exported set so the map stays legible
_HTTP_TIMEOUT_S = 10

# ODS PrimaryRoleId -> our facility taxonomy. Only these roles are real
# care-delivery sites; everything else (CCGs, data centres, HQs, ...) is dropped
# so the map shows genuine NHS facilities, not administrative organisations.
_GP_ROLES = {"RO76", "RO96"}                 # GP PRACTICE / BRANCH SURGERY
_PHARMACY_ROLES = {"RO182", "RO280"}         # PHARMACY / PHARMACY SITE
_TRUST_SITE_ROLES = {"RO198", "RO150"}       # NHS TRUST SITE / MILITARY HOSPITAL


def _facility_type(role: str | None, name: str) -> str | None:
    """Map an ODS PrimaryRoleId (+ name) to a facility type, or None to drop it."""
    if role in _GP_ROLES:
        return "gp"
    if role in _PHARMACY_ROLES:
        return "pharmacy"
    if role in _TRUST_SITE_ROLES:
        # Trust sites span hospitals + community clinics; refine by name.
        return "hospital" if "HOSPITAL" in (name or "").upper() else "clinic"
    return None

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
    """Return the facility list. Bundled by default; live NHS ODS when allowed."""
    facilities, _live = fetch_facilities(allow_network=allow_network)
    return facilities


def fetch_facilities(allow_network: bool = False) -> tuple[list[dict], bool]:
    """Return ``(facilities, live)`` — live=True iff the NHS ODS fetch succeeded."""
    if allow_network:
        fetched = _try_fetch_ods()
        if fetched:
            return fetched, True
    return [dict(f) for f in BUNDLED_FACILITIES], False


def _norm_postcode(pc: str) -> str:
    return (pc or "").upper().replace(" ", "")


# --------------------------------------------------------------------------- #
# Network seams — tests monkeypatch these to canned responses (offline-safe).
# --------------------------------------------------------------------------- #
def _ods_fetch_raw(postcode_prefix: str, limit: int = ODS_LIMIT) -> dict:
    """GET active organisations for a postcode district from the NHS ODS API."""
    import requests

    resp = requests.get(
        ODS_URL,
        params={"PostCode": postcode_prefix, "Status": "Active", "Limit": limit},
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=_HTTP_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json()


def _postcodes_fetch_raw(postcodes: list[str]) -> dict:
    """Bulk-geocode postcodes via postcodes.io (free, no key)."""
    import requests

    resp = requests.post(
        POSTCODES_URL,
        json={"postcodes": postcodes},
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=_HTTP_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json()


def _geocode_postcodes(postcodes: list[str]) -> dict[str, tuple[float, float]]:
    """Return {normalised_postcode: (lat, lng)} for the resolvable postcodes."""
    out: dict[str, tuple[float, float]] = {}
    for i in range(0, len(postcodes), 100):
        chunk = postcodes[i : i + 100]
        try:
            raw = _postcodes_fetch_raw(chunk)
        except Exception:  # noqa: BLE001
            continue
        for item in raw.get("result") or []:
            res = item.get("result")
            if not res:
                continue
            lat, lng = res.get("latitude"), res.get("longitude")
            if lat is None or lng is None:
                continue
            out[_norm_postcode(item.get("query", ""))] = (float(lat), float(lng))
    return out


def _try_fetch_ods() -> list[dict] | None:
    """Best-effort REAL NHS facilities (ODS + postcodes.io). None on any failure.

    1. enumerate active organisations across central-London postcode districts;
    2. geocode their postcodes to lat/lng;
    3. classify each by name and keep those inside the London bbox.
    Returns at least :data:`MIN_FACILITIES` records, else None (-> bundle).
    """
    orgs: dict[str, dict] = {}
    for prefix in CENTRAL_POSTCODE_PREFIXES:
        try:
            raw = _ods_fetch_raw(prefix)
        except Exception:  # noqa: BLE001
            continue
        for o in raw.get("Organisations") or []:
            oid = o.get("OrgId")
            name = o.get("Name")
            pc = o.get("PostCode")
            ftype = _facility_type(o.get("PrimaryRoleId"), name or "")
            if not oid or not name or not pc or not ftype:
                continue  # skip non-facility orgs (CCGs, HQs, data centres, ...)
            if o.get("Status") and o["Status"] != "Active":
                continue
            orgs.setdefault(
                oid,
                {"id": oid, "name": name.title(), "type": ftype, "postcode": pc},
            )

    if not orgs:
        return None

    coords = _geocode_postcodes(sorted({_norm_postcode(o["postcode"]) for o in orgs.values()}))

    facilities: list[dict] = []
    for o in orgs.values():
        ll = coords.get(_norm_postcode(o["postcode"]))
        if not ll:
            continue
        lat, lng = ll
        if not quality.point_in_bbox(lat, lng):
            continue
        facilities.append(
            {
                "id": o["id"],
                "name": o["name"],
                "type": o["type"],
                "lat": round(lat, 6),
                "lng": round(lng, 6),
            }
        )

    facilities.sort(key=lambda f: f["id"])
    if len(facilities) < MIN_FACILITIES:
        return None
    return facilities[:MAX_FACILITIES]


def write_facilities(
    path: Path | str = FACILITIES_PATH,
    allow_network: bool = False,
    mirror_frontend: bool = True,
) -> tuple[list[dict], bool]:
    """Write facilities JSON; return ``(facilities, live)``.

    Also mirrors the file into ``frontend/public/data/facilities.json`` (the copy
    the map loads) unless ``mirror_frontend`` is False.
    """
    facilities, live = fetch_facilities(allow_network=allow_network)
    blob = json.dumps(facilities, indent=2) + "\n"
    Path(path).write_text(blob)
    if mirror_frontend:
        FRONTEND_FACILITIES_PATH.parent.mkdir(parents=True, exist_ok=True)
        FRONTEND_FACILITIES_PATH.write_text(blob)
    return facilities, live


if __name__ == "__main__":
    fac, live = write_facilities(allow_network=True)
    print(f"wrote {len(fac)} facilities (live={live}) -> {FACILITIES_PATH}")
