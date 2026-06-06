"""Real London NHS facilities geocode + normalize into the facilities schema.

Offline + deterministic: both the NHS ODS hospital-sites CSV fetch AND the
postcodes.io client are monkeypatched so no network is touched. We assert the
returned records conform to the facilities schema (``quality.validate_facilities``),
every coordinate is inside the London bbox, every type is allowed, and ids are
unique.
"""
from __future__ import annotations

import nhs_facilities
import quality

# Coordinates used by the fake geocoder.
_IN_LONDON = (51.5074, -0.1278)        # central London — inside the bbox
_OUT_OF_LONDON = (53.4631, -2.2913)    # Manchester — outside the bbox


def _no_ods() -> str:
    """ODS fetcher stub that yields no hospital rows (seed-only path)."""
    return ""


class _FakePostcodesIoClient:
    """Stand-in geocoder: returns deterministic, in-bbox coordinates."""

    def __init__(self, *args, **kwargs):
        self.calls = []

    def bulk_lookup(self, postcodes):
        self.calls.append(list(postcodes))
        # Hand back a fixed, plainly in-London coordinate for every postcode.
        return {
            nhs_facilities._norm_postcode(pc): _IN_LONDON
            for pc in postcodes
        }


def test_fetch_nhs_london_conforms_to_facilities_schema():
    client = _FakePostcodesIoClient()
    records = nhs_facilities.fetch_nhs_london(
        allow_network=True, client=client, ods_fetcher=_no_ods
    )

    assert records, "expected at least one NHS facility record"
    # The geocoder was actually consulted (real pipeline, not bundled-only).
    assert client.calls and client.calls[0]

    # Exact schema shape per record.
    for rec in records:
        assert set(rec.keys()) == {"id", "name", "type", "lat", "lng"}
        assert rec["type"] in quality.FACILITY_TYPES
        assert isinstance(rec["name"], str) and len(rec["name"]) >= 2
        assert quality.point_in_bbox(rec["lat"], rec["lng"])

    # ids unique.
    ids = [r["id"] for r in records]
    assert len(ids) == len(set(ids))

    # Pandera facilities schema (single source of truth) accepts them.
    quality.validate_facilities(records)


def test_fetch_nhs_london_offline_falls_back_to_bundled():
    # No network: must not raise and must use bundled coordinates.
    records = nhs_facilities.fetch_nhs_london(allow_network=False)

    assert records
    for rec in records:
        assert quality.point_in_bbox(rec["lat"], rec["lng"])
        assert rec["type"] in quality.FACILITY_TYPES
    quality.validate_facilities(records)


def test_fetch_nhs_london_survives_geocoder_failure():
    class _BoomClient:
        def bulk_lookup(self, postcodes):
            raise RuntimeError("network down")

    # Geocoder explosion must be swallowed; bundled coords carry the result.
    records = nhs_facilities.fetch_nhs_london(
        allow_network=True, client=_BoomClient(), ods_fetcher=_no_ods
    )

    assert records
    quality.validate_facilities(records)


def test_fetch_nhs_london_survives_ods_fetch_failure():
    def _boom_ods() -> str:
        raise RuntimeError("ODS download failed")

    # ODS explosion must be swallowed and degrade to the seed.
    records = nhs_facilities.fetch_nhs_london(
        allow_network=True,
        client=_FakePostcodesIoClient(),
        ods_fetcher=_boom_ods,
    )
    assert records
    quality.validate_facilities(records)


def test_limit_is_respected():
    records = nhs_facilities.fetch_nhs_london(allow_network=False, limit=5)
    assert 0 < len(records) <= 5


# --------------------------------------------------------------------------- #
# Live ODS ingest (monkeypatched): seed ∪ ODS hospitals, bbox/type/id filtered.
# --------------------------------------------------------------------------- #
# Headerless ODS ``ets.csv`` fixture. Column layout per the ODS spec:
#   col 0 = org code, col 1 = name, col 9 = postcode (0-indexed).
# Three rows: one valid London hospital, one valid-postcode hospital that
# geocodes OUTSIDE London, and one with a junk postcode (dropped at parse).
_FAKE_ODS_CSV = (
    'RAA01,New London ODS Hospital,Nat,Geo,1 A St,Area,London,,,SE1 9RT,'
    '2020-01-01,,,,A,0,,,,,,,,\r\n'
    'RBB02,Manchester Royal Infirmary,Nat,Geo,2 B St,Area,Manchester,,,M13 9WL,'
    '2020-01-01,,,,A,0,,,,,,,,\r\n'
    'RCC03,Broken Postcode Hospital,Nat,Geo,3 C St,Area,Nowhere,,,NOT A PC,'
    '2020-01-01,,,,A,0,,,,,,,,\r\n'
    'RDD04,,Nat,Geo,4 D St,Area,Anon,,,EC1A 7BE,'   # missing name -> dropped
    '2020-01-01,,,,A,0,,,,,,,,\r\n'
)


class _RoutingPostcodesIoClient:
    """Geocoder that sends the Manchester postcode out of the bbox."""

    def __init__(self):
        self.calls = []

    def bulk_lookup(self, postcodes):
        self.calls.append(list(postcodes))
        out = {}
        for pc in postcodes:
            key = nhs_facilities._norm_postcode(pc)
            if key == nhs_facilities._norm_postcode("M13 9WL"):
                out[key] = _OUT_OF_LONDON
            else:
                out[key] = _IN_LONDON
        return out


def test_ods_merge_filters_and_conforms():
    client = _RoutingPostcodesIoClient()
    records = nhs_facilities.fetch_nhs_london(
        allow_network=True,
        client=client,
        ods_fetcher=lambda: _FAKE_ODS_CSV,
    )

    names = {r["name"] for r in records}
    # The valid London ODS hospital is merged in (beyond the seed).
    assert "New London ODS Hospital" in names
    # Out-of-bbox row dropped by the bbox filter.
    assert "Manchester Royal Infirmary" not in names
    # Junk-postcode + nameless rows dropped at parse.
    assert "Broken Postcode Hospital" not in names

    # Merged set is strictly larger than the seed alone.
    seed_only = nhs_facilities.fetch_nhs_london(allow_network=False)
    assert len(records) == len(seed_only) + 1

    # Schema / bbox / type / unique-id invariants hold for the merged set.
    for rec in records:
        assert set(rec.keys()) == {"id", "name", "type", "lat", "lng"}
        assert rec["type"] in quality.FACILITY_TYPES
        assert quality.point_in_bbox(rec["lat"], rec["lng"])
    ids = [r["id"] for r in records]
    assert len(ids) == len(set(ids))
    quality.validate_facilities(records)


def test_parse_ods_hospitals_drops_bad_rows():
    rows = nhs_facilities.parse_ods_hospitals(_FAKE_ODS_CSV)
    # Only the two valid-postcode, named rows survive parse.
    assert [r["id"] for r in rows] == ["RAA01", "RBB02"]
    for r in rows:
        assert r["type"] == "hospital"
        assert set(r.keys()) == {"id", "name", "type", "postcode"}
