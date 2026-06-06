"""Gazetteer builder DQ — offline-safe build + schema + categorization.

Hermetic: never touches the real ~121 MB PBF. We exercise the offline path
(``allow_osm=False`` and "pbf missing") end-to-end, plus the pure tag→category
and record-normalization helpers that the osmium handler delegates to.
"""
from __future__ import annotations

import json

import build_gazetteer as gz
import facilities as facilities_mod
import quality

_SCHEMA_KEYS = {"name", "lat", "lng", "type", "source"}


def _read(path) -> list[dict]:
    return json.loads(path.read_text())


# --------------------------------------------------------------------------- #
# Offline build end-to-end
# --------------------------------------------------------------------------- #
def test_offline_build_writes_facilities(tmp_path):
    out = tmp_path / "gazetteer.json"
    prov = gz.build_gazetteer(allow_osm=False, out_path=out)

    # provenance shape
    assert set(prov) == {"path", "count", "sources", "generated_at"}
    assert prov["path"] == str(out)
    assert prov["sources"] == ["nhs"], "offline build must be NHS-only"
    assert prov["count"] >= 20

    records = _read(out)
    assert len(records) == prov["count"]

    # every record matches the {name,lat,lng,type,source} schema, in-bbox
    for r in records:
        assert set(r) == _SCHEMA_KEYS, f"unexpected keys: {set(r)}"
        assert isinstance(r["name"], str) and r["name"]
        assert isinstance(r["lat"], float) and isinstance(r["lng"], float)
        assert quality.point_in_bbox(r["lat"], r["lng"]), f"out of bbox: {r}"
        assert r["source"] == "nhs"

    # curated NHS facilities are all present (matched by normalized name)
    gaz_names = {gz._normalize_name(r["name"]) for r in records}
    for f in facilities_mod.build_facilities():
        assert gz._normalize_name(f["name"]) in gaz_names, f"missing facility {f['name']}"


def test_missing_pbf_is_offline_safe(tmp_path):
    """allow_osm=True but a bogus pbf path must not raise and stays NHS-only."""
    out = tmp_path / "gazetteer.json"
    prov = gz.build_gazetteer(
        pbf_path=tmp_path / "does-not-exist.osm.pbf", out_path=out, allow_osm=True
    )
    assert prov["sources"] == ["nhs"]
    assert prov["count"] >= 20
    assert out.exists()


def test_records_unique(tmp_path):
    """Deduped output: no two records share normalized-name + rounded coords."""
    out = tmp_path / "gazetteer.json"
    gz.build_gazetteer(allow_osm=False, out_path=out)
    records = _read(out)
    keys = {
        (gz._normalize_name(r["name"]), round(r["lat"], 5), round(r["lng"], 5))
        for r in records
    }
    assert len(keys) == len(records), "duplicate (name, coords) entries"


# --------------------------------------------------------------------------- #
# Pure helpers the osmium handler delegates to (mock the tag dicts)
# --------------------------------------------------------------------------- #
def test_categorize_health_place_transport():
    assert gz._categorize({"amenity": "pharmacy", "name": "Bow Road Pharmacy"}) == "health"
    assert gz._categorize({"amenity": "doctors"}) == "health"
    assert gz._categorize({"amenity": "social_facility"}) == "health"
    assert gz._categorize({"healthcare": "centre"}) == "health"
    assert gz._categorize({"place": "suburb"}) == "place"
    assert gz._categorize({"place": "neighbourhood"}) == "place"
    assert gz._categorize({"railway": "station"}) == "transport"
    assert gz._categorize({"public_transport": "station"}) == "transport"
    # non-matches
    assert gz._categorize({"amenity": "cafe"}) is None
    assert gz._categorize({"place": "country"}) is None
    assert gz._categorize({}) is None


def test_make_record_bbox_and_schema():
    # central London -> kept
    rec = gz._make_record("Finsbury Park", 51.5642, -0.1066, "place", "osm")
    assert rec is not None and set(rec) == _SCHEMA_KEYS
    assert rec["source"] == "osm" and rec["type"] == "place"
    # outside the London bbox -> dropped
    assert gz._make_record("Paris", 48.8566, 2.3522, "place", "osm") is None
    # missing name / bad coords -> dropped
    assert gz._make_record("", 51.5, -0.1, "place", "osm") is None
    assert gz._make_record("X", "nan-ish", None, "place", "osm") is None


def test_dedupe_first_wins():
    recs = [
        {"name": "Victoria Medical Centre", "lat": 51.5, "lng": -0.1, "type": "health", "source": "nhs"},
        {"name": "victoria medical centre", "lat": 51.500001, "lng": -0.1, "type": "health", "source": "osm"},
    ]
    out = gz._dedupe(recs)
    assert len(out) == 1
    assert out[0]["source"] == "nhs", "NHS record (first) must win the collision"
