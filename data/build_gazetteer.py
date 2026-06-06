"""Full-coverage offline London gazetteer — named places from the local OSM extract.

The natural-language delivery intake needs to turn a free-text place
("Spitalfields Practice", "Victoria Medical Centre", "Finsbury Park",
"Bow Road pharmacy") into real WGS84 coordinates *without any network*. This
module builds that lookup table by streaming the Greater-London OpenStreetMap
PBF extract with ``pyosmium`` and extracting every NAMED feature we care about:
health sites, residential places, and transport landmarks. It then merges in the
curated NHS facilities (so those well-known sites are always present) and writes a
single JSON array to ``data/gazetteer.json``.

Design goals (mirroring the rest of the data pipeline, see ``data/integrations.py``
and ``data/facilities.py``):
  * **Offline-safe / never-raise.** If ``pyosmium`` is missing, the PBF is absent,
    or ``allow_osm=False``, we still write a valid gazetteer containing just the
    curated NHS facilities and return provenance with ``sources=["nhs"]``.
  * **Local-first.** The PBF lives on the GB10 box at
    ``data/cache/osm/greater-london-latest.osm.pbf`` (~121 MB). We stream it via
    an ``osmium.SimpleHandler`` so we never hold the raw file in memory.
  * **Single source of bbox truth.** All coordinates are filtered through
    ``quality.point_in_bbox`` / ``quality.LONDON_BBOX``.

Run the real build on the box::

    uv pip install osmium
    .venv/bin/python data/build_gazetteer.py
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import quality

DATA_DIR = Path(__file__).resolve().parent
DEFAULT_PBF = DATA_DIR / "cache" / "osm" / "greater-london-latest.osm.pbf"
DEFAULT_OUT = DATA_DIR / "gazetteer.json"
FACILITIES_PATH = DATA_DIR / "facilities.json"

# --------------------------------------------------------------------------- #
# What we extract from OSM, by category. The category becomes the record
# ``type`` so the intake resolver can prefer health sites for medical jobs.
# --------------------------------------------------------------------------- #
HEALTH_AMENITIES = {"hospital", "clinic", "doctors", "pharmacy", "dentist"}
PLACE_KINDS = {"suburb", "neighbourhood", "quarter", "town", "village", "city"}

CATEGORY_HEALTH = "health"
CATEGORY_PLACE = "place"
CATEGORY_TRANSPORT = "transport"

# Round coords to ~5 decimal places (~1 m) for dedupe keying.
_DEDUPE_DP = 5


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_name(name: str) -> str:
    """Lowercase, trim, collapse internal whitespace — for dedupe keys only."""
    return re.sub(r"\s+", " ", str(name).strip().lower())


def _categorize(tags) -> str | None:
    """Map an OSM feature's tags to a gazetteer category, or ``None`` to skip.

    ``tags`` is anything supporting ``key in tags`` and ``tags.get(key)`` — a
    pyosmium ``TagList`` or a plain dict (used by the tests).
    """
    # Health: amenity in set OR any healthcare=* tag OR amenity=social_facility.
    amenity = tags.get("amenity")
    if amenity in HEALTH_AMENITIES or amenity == "social_facility":
        return CATEGORY_HEALTH
    if "healthcare" in tags:
        return CATEGORY_HEALTH
    # Places.
    if tags.get("place") in PLACE_KINDS:
        return CATEGORY_PLACE
    # Transport landmarks.
    if tags.get("railway") == "station" or tags.get("public_transport") == "station":
        return CATEGORY_TRANSPORT
    return None


def _make_record(name: str, lat: float, lng: float, category: str, source: str) -> dict | None:
    """Normalize + bbox-filter a single entry; ``None`` if invalid/out-of-bbox."""
    if not name:
        return None
    try:
        lat = float(lat)
        lng = float(lng)
    except (TypeError, ValueError):
        return None
    if not quality.point_in_bbox(lat, lng):
        return None
    return {
        "name": str(name),
        "lat": lat,
        "lng": lng,
        "type": category,
        "source": source,
    }


# --------------------------------------------------------------------------- #
# OSM streaming
# --------------------------------------------------------------------------- #
def _extract_osm(pbf_path: Path) -> list[dict]:
    """Stream the PBF and return normalized, in-bbox, named OSM records.

    Returns an empty list (never raises) if pyosmium is unavailable or the file
    cannot be parsed. Way geometries are reduced to the centroid (mean) of their
    member node coordinates, which requires ``apply_file(..., locations=True)``.
    """
    try:
        import osmium  # noqa: WPS433 — optional dep, only present on the box
    except Exception:  # pragma: no cover - exercised only without pyosmium
        return []

    out: list[dict] = []

    class _Handler(osmium.SimpleHandler):  # type: ignore[misc]
        def _add(self, name: str, lat: float, lng: float, category: str) -> None:
            rec = _make_record(name, lat, lng, category, "osm")
            if rec is not None:
                out.append(rec)

        def node(self, n) -> None:  # noqa: N802 - osmium callback name
            try:
                name = n.tags.get("name")
                if not name:
                    return
                category = _categorize(n.tags)
                if category is None:
                    return
                loc = n.location
                if not loc.valid():
                    return
                self._add(name, loc.lat, loc.lon, category)
            except Exception:
                # A single malformed feature must never abort the whole build.
                return

        def way(self, w) -> None:  # noqa: N802 - osmium callback name
            try:
                name = w.tags.get("name")
                if not name:
                    return
                category = _categorize(w.tags)
                if category is None:
                    return
                lats: list[float] = []
                lngs: list[float] = []
                for nd in w.nodes:
                    loc = nd.location
                    if loc.valid():
                        lats.append(loc.lat)
                        lngs.append(loc.lon)
                if not lats:
                    return
                self._add(name, sum(lats) / len(lats), sum(lngs) / len(lngs), category)
            except Exception:
                return

    try:
        _Handler().apply_file(str(pbf_path), locations=True)
    except Exception:  # pragma: no cover - corrupt/missing pbf at parse time
        return out  # whatever we managed to collect before the failure
    return out


# --------------------------------------------------------------------------- #
# NHS facilities (always present)
# --------------------------------------------------------------------------- #
def _load_facilities() -> list[dict]:
    """Load curated NHS facilities as gazetteer records (source ``nhs``)."""
    try:
        raw = json.loads(FACILITIES_PATH.read_text())
    except Exception:
        return []
    records: list[dict] = []
    for f in raw:
        rec = _make_record(
            f.get("name"), f.get("lat"), f.get("lng"), f.get("type") or "facility", "nhs"
        )
        if rec is not None:
            records.append(rec)
    return records


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #
def _resolve_pbf(pbf_path: str | Path | None) -> Path:
    if pbf_path:
        return Path(pbf_path)
    env_dir = os.getenv("OSM_DIR")
    if env_dir:
        return Path(env_dir) / "greater-london-latest.osm.pbf"
    return DEFAULT_PBF


def _dedupe(records: list[dict]) -> list[dict]:
    """Dedupe by (normalized-name + coords rounded to ~5dp). First wins.

    Callers pass NHS records first so curated sites survive collisions.
    """
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for r in records:
        key = (
            _normalize_name(r["name"]),
            round(r["lat"], _DEDUPE_DP),
            round(r["lng"], _DEDUPE_DP),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped


def build_gazetteer(
    pbf_path: str | Path | None = None,
    out_path: str | Path | None = None,
    *,
    allow_osm: bool = True,
) -> dict:
    """Build the offline London gazetteer and write it to ``out_path``.

    Curated NHS facilities are always included (source ``nhs``); when the OSM
    extract is available it is streamed for thousands more named health sites,
    places and transport landmarks (source ``osm``). Offline-safe: this function
    never raises — a missing PBF / missing pyosmium / ``allow_osm=False`` simply
    yields the NHS-only gazetteer.

    Returns provenance ``{path, count, sources, generated_at}``.
    """
    out = Path(out_path) if out_path else DEFAULT_OUT

    # NHS facilities first so they win any dedupe collision with OSM.
    records: list[dict] = _load_facilities()

    osm_records: list[dict] = []
    if allow_osm:
        pbf = _resolve_pbf(pbf_path)
        if pbf.exists():
            osm_records = _extract_osm(pbf)
    records.extend(osm_records)

    records = _dedupe(records)

    sources = sorted({r["source"] for r in records}) or ["nhs"]

    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(records, indent=2))
    except Exception:
        # Even a write failure must not raise from the build entrypoint.
        pass

    return {
        "path": str(out),
        "count": len(records),
        "sources": sources,
        "generated_at": _now_iso(),
    }


if __name__ == "__main__":
    provenance = build_gazetteer()
    print(json.dumps(provenance, indent=2))
