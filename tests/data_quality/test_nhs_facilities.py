"""Real London NHS facilities geocode + normalize into the facilities schema.

Offline + deterministic: the postcodes.io client is monkeypatched so no network
is touched. We assert the returned records conform to the facilities schema
(``quality.validate_facilities``), every coordinate is inside the London bbox,
every type is allowed, and ids are unique.
"""
from __future__ import annotations

import nhs_facilities
import quality


class _FakePostcodesIoClient:
    """Stand-in geocoder: returns deterministic, in-bbox coordinates."""

    def __init__(self, *args, **kwargs):
        self.calls = []

    def bulk_lookup(self, postcodes):
        self.calls.append(list(postcodes))
        # Hand back a fixed, plainly in-London coordinate for every postcode.
        return {
            nhs_facilities._norm_postcode(pc): (51.5074, -0.1278)
            for pc in postcodes
        }


def test_fetch_nhs_london_conforms_to_facilities_schema():
    client = _FakePostcodesIoClient()
    records = nhs_facilities.fetch_nhs_london(allow_network=True, client=client)

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
    records = nhs_facilities.fetch_nhs_london(allow_network=True, client=_BoomClient())

    assert records
    quality.validate_facilities(records)


def test_limit_is_respected():
    records = nhs_facilities.fetch_nhs_london(allow_network=False, limit=5)
    assert 0 < len(records) <= 5
