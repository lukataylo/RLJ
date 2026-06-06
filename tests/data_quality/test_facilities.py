"""Facility dataset DQ — bbox + completeness/uniqueness."""
from __future__ import annotations

import facilities as facilities_mod
import quality


def test_within_london_bbox():
    """Every facility coordinate lies within the Greater-London bbox."""
    df = quality.facilities_dataframe(facilities_mod.build_facilities())
    inside = quality.within_london_bbox(df)
    assert inside.all(), (
        "facilities outside London bbox:\n"
        + df.loc[~inside, ["id", "name", "lat", "lng"]].to_string(index=False)
    )
    # ~25 real facilities expected
    assert len(df) >= 20


def test_required_fields_and_unique():
    """No missing required fields; ids are unique (pandera-enforced)."""
    facilities = facilities_mod.build_facilities()
    df = quality.facilities_dataframe(facilities)

    # pandera schema enforces presence, types, enum, bbox and uniqueness.
    validated = quality.validate_facilities(df)
    assert len(validated) == len(df)

    # explicit no-missing / unique-id checks for a readable failure message.
    required = ["id", "name", "type", "lat", "lng"]
    for col in required:
        assert col in df.columns, f"missing column {col}"
        assert df[col].notna().all(), f"null values in {col}"
    assert df["id"].is_unique, "duplicate facility ids"


# --------------------------------------------------------------------------- #
# LIVE NHS ODS path — HTTP fully mocked so the test is deterministic + offline.
# --------------------------------------------------------------------------- #
# Canned ODS organisations: a healthy spread of real-style roles + a couple of
# non-facility orgs (a CCG and a data centre) that MUST be filtered out.
def _canned_ods() -> dict:
    orgs = []
    for i in range(24):
        role, pc = ("RO76", "EC1A 1BB") if i % 2 == 0 else ("RO182", "WC1N 3JH")
        orgs.append(
            {
                "OrgId": f"FAC{i:03d}",
                "Name": f"Example {'Surgery' if role == 'RO76' else 'Pharmacy'} {i}",
                "PostCode": pc,
                "Status": "Active",
                "PrimaryRoleId": role,
            }
        )
    # a real hospital trust site (refined to "hospital" by name)
    orgs.append({"OrgId": "FACHOSP", "Name": "St Example Hospital", "PostCode": "SE1 7EH",
                 "Status": "Active", "PrimaryRoleId": "RO198"})
    # a trust site WITHOUT "hospital" in the name -> classified "clinic"
    orgs.append({"OrgId": "FACCLIN", "Name": "Example Community Health Centre", "PostCode": "N1 9AG",
                 "Status": "Active", "PrimaryRoleId": "RO198"})
    # non-facility orgs that must be dropped (unmapped roles)
    orgs.append({"OrgId": "CCG1", "Name": "Some CCG", "PostCode": "EC1A 1BB",
                 "Status": "Active", "PrimaryRoleId": "RO98"})
    orgs.append({"OrgId": "DATA1", "Name": "Optum Data Centre", "PostCode": "EC1A 1BB",
                 "Status": "Active", "PrimaryRoleId": "RO216"})
    # a real GP whose postcode geocodes OUTSIDE the London bbox -> dropped
    orgs.append({"OrgId": "FAROUT", "Name": "Faraway Surgery", "PostCode": "ZZ1 1ZZ",
                 "Status": "Active", "PrimaryRoleId": "RO76"})
    return {"Organisations": orgs}


# In-bbox geocodes for the canned postcodes; ZZ1 1ZZ resolves far outside it.
_CANNED_COORDS = {
    "EC1A1BB": (51.5202, -0.1000),
    "WC1N3JH": (51.5224, -0.1199),
    "SE17EH": (51.4979, -0.1188),
    "N19AG": (51.5340, -0.1050),
    "ZZ11ZZ": (55.9533, -3.1883),  # Edinburgh — outside the London bbox
}


def _fake_postcodes(postcodes):
    result = []
    for pc in postcodes:
        key = pc.upper().replace(" ", "")
        ll = _CANNED_COORDS.get(key)
        result.append({"query": pc, "result": ({"latitude": ll[0], "longitude": ll[1]} if ll else None)})
    return {"result": result}


def test_live_ods_fetch_parsed_and_in_bbox(monkeypatch):
    """The live NHS ODS path parses real org records, geocodes + bbox-filters,
    classifies by role, and drops non-facility organisations."""
    monkeypatch.setattr(facilities_mod, "_ods_fetch_raw", lambda prefix, limit=100: _canned_ods())
    monkeypatch.setattr(facilities_mod, "_postcodes_fetch_raw", _fake_postcodes)

    facilities, live = facilities_mod.fetch_facilities(allow_network=True)
    assert live is True, "live fetch should have succeeded"
    assert len(facilities) >= 20

    # all coordinates inside the London bbox; the out-of-bbox GP was dropped.
    df = quality.facilities_dataframe(facilities)
    assert quality.within_london_bbox(df).all()
    ids = {f["id"] for f in facilities}
    assert "FAROUT" not in ids, "out-of-bbox facility should be filtered"

    # pandera schema (types, enum, uniqueness, bbox) passes on the live data.
    quality.validate_facilities(facilities)

    # non-facility administrative orgs are not present.
    assert "CCG1" not in ids and "DATA1" not in ids

    # role-based classification: GP, pharmacy, hospital, and trust-site clinic.
    by_id = {f["id"]: f for f in facilities}
    assert by_id["FAC000"]["type"] == "gp"
    assert by_id["FAC001"]["type"] == "pharmacy"
    assert by_id["FACHOSP"]["type"] == "hospital"
    assert by_id["FACCLIN"]["type"] == "clinic"


def test_live_ods_fetch_falls_back_to_bundle(monkeypatch):
    """If the ODS API is unreachable, fetch_facilities returns the bundle."""
    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(facilities_mod, "_ods_fetch_raw", _boom)
    monkeypatch.setattr(facilities_mod, "_postcodes_fetch_raw", _boom)

    facilities, live = facilities_mod.fetch_facilities(allow_network=True)
    assert live is False, "fallback must report live=False"
    assert facilities == [dict(f) for f in facilities_mod.BUNDLED_FACILITIES]
    quality.validate_facilities(facilities)
