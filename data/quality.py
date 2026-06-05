"""Single source of data-quality (DQ) truth for the RLJ data pipeline.

Both ``data/build.py`` (the build pipeline) and the external pytest suites in
``tests/data_quality/`` import their validators from here, so there is exactly
one definition of "what good data looks like".

Everything is pure-stdlib + pandas + pandera + jsonschema (offline-safe).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import pandas as pd
import pandera.pandas as pa

# --------------------------------------------------------------------------- #
# London bounding box — the canonical constant. Lives HERE so every consumer
# (facilities builder, demand generator, road graph, and the tests) agrees.
# --------------------------------------------------------------------------- #
LONDON_BBOX = {
    "lat_min": 51.28,
    "lat_max": 51.69,
    "lng_min": -0.51,
    "lng_max": 0.33,
}

# Facility taxonomy used across the pipeline.
FACILITY_TYPES = ("gp", "hospital", "lab", "pharmacy", "clinic")

# Allowed kinds for a TimedEvent / signal-derived disruption.
TIMED_EVENT_KINDS = ("road_closure", "traffic")

# Provenance vocabulary every signal record must use.
VALID_PROVENANCE = ("scheduled", "synthetic", "live")

# Priority mix + window expectations (minutes from ready_at) per priority.
# These bound how "tight" each clinical window may be; the demand generator
# stays inside these and the tests assert the ordering (stat < urgent < routine).
PRIORITY_WINDOW_MAX_MIN = {"stat": 75, "urgent": 150, "routine": 200}
PRIORITY_WINDOW_MIN_MIN = {"stat": 40, "urgent": 90, "routine": 150}

_ROOT = Path(__file__).resolve().parent.parent
_SCHEMAS_PATH = _ROOT / "contracts" / "schemas.json"


# --------------------------------------------------------------------------- #
# bbox helpers
# --------------------------------------------------------------------------- #
def within_london_bbox(df: pd.DataFrame, lat_col: str = "lat", lng_col: str = "lng") -> pd.Series:
    """Return a boolean Series: True where the row's coordinate is in the bbox."""
    lat = pd.to_numeric(df[lat_col], errors="coerce")
    lng = pd.to_numeric(df[lng_col], errors="coerce")
    return (
        lat.between(LONDON_BBOX["lat_min"], LONDON_BBOX["lat_max"])
        & lng.between(LONDON_BBOX["lng_min"], LONDON_BBOX["lng_max"])
    )


def point_in_bbox(lat: float, lng: float) -> bool:
    return (
        LONDON_BBOX["lat_min"] <= lat <= LONDON_BBOX["lat_max"]
        and LONDON_BBOX["lng_min"] <= lng <= LONDON_BBOX["lng_max"]
    )


# --------------------------------------------------------------------------- #
# facilities
# --------------------------------------------------------------------------- #
FACILITIES_SCHEMA = pa.DataFrameSchema(
    {
        "id": pa.Column(str, nullable=False, unique=True),
        "name": pa.Column(str, nullable=False, checks=pa.Check.str_length(min_value=2)),
        "type": pa.Column(str, checks=pa.Check.isin(list(FACILITY_TYPES))),
        "lat": pa.Column(
            float,
            checks=pa.Check.in_range(LONDON_BBOX["lat_min"], LONDON_BBOX["lat_max"]),
            coerce=True,
        ),
        "lng": pa.Column(
            float,
            checks=pa.Check.in_range(LONDON_BBOX["lng_min"], LONDON_BBOX["lng_max"]),
            coerce=True,
        ),
    },
    strict=False,
    coerce=True,
)


def facilities_dataframe(records: Sequence[Mapping]) -> pd.DataFrame:
    return pd.DataFrame(list(records))


def validate_facilities(df: pd.DataFrame) -> pd.DataFrame:
    """Validate the facilities table; raise ``pandera.errors.SchemaErrors`` on fail.

    Accepts either a DataFrame or a list of dict records.
    """
    if not isinstance(df, pd.DataFrame):
        df = facilities_dataframe(df)  # type: ignore[arg-type]
    return FACILITIES_SCHEMA.validate(df, lazy=True)


# --------------------------------------------------------------------------- #
# demand (DeliveryJob[]) — schema + window sanity
# --------------------------------------------------------------------------- #
def _load_delivery_job_validator():
    schemas = json.loads(_SCHEMAS_PATH.read_text())
    from jsonschema import Draft202012Validator

    return Draft202012Validator(
        {"$ref": "#/$defs/DeliveryJob", "$defs": schemas["$defs"]}
    )


def _parse_iso(ts: str):
    from datetime import datetime

    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def validate_demand(
    records: Iterable[Mapping],
    now: str | None = None,
    horizon_hours: int = 6,
) -> list[dict]:
    """Validate generated demand.

    Checks, in order:
      1. every record conforms to ``$defs/DeliveryJob`` (jsonschema);
      2. ``due_by`` > ``ready_at`` for every job;
      3. each job's window length is inside the per-priority bounds, which
         guarantees stat windows are tighter than routine ones;
      4. (if ``now`` given) every window falls inside ``now .. now+horizon``.

    Raises ``AssertionError`` describing the first batch of problems.
    Returns the records (as a list) on success.
    """
    records = [dict(r) for r in records]
    validator = _load_delivery_job_validator()

    errors: list[str] = []
    for i, job in enumerate(records):
        for e in validator.iter_errors(job):
            errors.append(f"[{i}] schema {list(e.path)}: {e.message}")
    if errors:
        raise AssertionError("DeliveryJob schema failures:\n" + "\n".join(errors[:15]))

    now_dt = _parse_iso(now) if now else None
    for i, job in enumerate(records):
        tw = job.get("time_window") or {}
        ra, db = tw.get("ready_at"), tw.get("due_by")
        if not ra or not db:
            errors.append(f"[{i}] missing time_window.ready_at/due_by")
            continue
        ra_dt, db_dt = _parse_iso(ra), _parse_iso(db)
        if db_dt <= ra_dt:
            errors.append(f"[{i}] due_by ({db}) not after ready_at ({ra})")
        win_min = (db_dt - ra_dt).total_seconds() / 60.0
        prio = job["priority"]
        lo = PRIORITY_WINDOW_MIN_MIN[prio]
        hi = PRIORITY_WINDOW_MAX_MIN[prio]
        if not (lo - 1 <= win_min <= hi + 1):
            errors.append(
                f"[{i}] {prio} window {win_min:.0f}min outside [{lo},{hi}]"
            )
        if now_dt is not None:
            horizon = now_dt.timestamp() + horizon_hours * 3600
            # allow ready_at to be slightly before now (clock skew); cap at +5min.
            if ra_dt.timestamp() < now_dt.timestamp() - 300:
                errors.append(f"[{i}] ready_at before now")
            if db_dt.timestamp() > horizon:
                errors.append(f"[{i}] due_by beyond {horizon_hours}h horizon")
    if errors:
        raise AssertionError("Demand window failures:\n" + "\n".join(errors[:15]))
    return records


# --------------------------------------------------------------------------- #
# road graph / geojson
# --------------------------------------------------------------------------- #
def _iter_linestring_coords(features: Sequence[Mapping]):
    for f in features:
        geom = f.get("geometry", {})
        if geom.get("type") == "LineString":
            for lng, lat in geom["coordinates"]:
                yield lat, lng
        elif geom.get("type") == "Polygon":
            for ring in geom["coordinates"]:
                for lng, lat in ring:
                    yield lat, lng


def validate_geojson_bbox(geojson: Mapping) -> bool:
    """True iff the FeatureCollection is non-empty and every vertex is in bbox."""
    feats = geojson.get("features", [])
    if not feats:
        raise AssertionError("geojson has no features")
    bad = [
        (lat, lng)
        for lat, lng in _iter_linestring_coords(feats)
        if not point_in_bbox(lat, lng)
    ]
    if bad:
        raise AssertionError(f"{len(bad)} geojson vertices outside London bbox, e.g. {bad[0]}")
    return True


def roads_graph(geojson: Mapping):
    """Build a networkx graph from a roads FeatureCollection (LineStrings)."""
    import networkx as nx

    g = nx.Graph()
    for f in geojson.get("features", []):
        geom = f.get("geometry", {})
        if geom.get("type") != "LineString":
            continue
        coords = geom["coordinates"]
        for (lng0, lat0), (lng1, lat1) in zip(coords, coords[1:]):
            n0 = (round(lat0, 6), round(lng0, 6))
            n1 = (round(lat1, 6), round(lng1, 6))
            g.add_edge(n0, n1)
    return g


def validate_roads(geojson: Mapping, require_connected: bool = True) -> dict:
    """Validate a roads FeatureCollection. Returns stats; raises on failure."""
    import networkx as nx

    validate_geojson_bbox(geojson)
    g = roads_graph(geojson)
    if g.number_of_edges() == 0:
        raise AssertionError("road graph has no edges")
    connected = nx.is_connected(g) if g.number_of_nodes() else False
    if require_connected and not connected:
        comps = nx.number_connected_components(g)
        raise AssertionError(f"road graph is not connected ({comps} components)")
    return {
        "nodes": g.number_of_nodes(),
        "edges": g.number_of_edges(),
        "connected": connected,
    }


# --------------------------------------------------------------------------- #
# signals (TimedEvent[]) — schema + bbox + window + intensity sanity
# --------------------------------------------------------------------------- #
def validate_timed_events(events: Iterable[Mapping]) -> list[dict]:
    """Validate a list of TimedEvent dicts (towerbridge / events / signals).

    Checks each record:
      * has required keys ``id, kind, geometry, start, end, intensity, source,
        label``;
      * ``kind`` in :data:`TIMED_EVENT_KINDS`;
      * non-empty ``geometry`` with every vertex inside :data:`LONDON_BBOX`;
      * ``end`` strictly after ``start`` (both ISO-8601);
      * ``intensity`` in the half-open range (0, 1];
      * ``source`` in :data:`VALID_PROVENANCE`.

    Returns the records (list) on success; raises ``AssertionError`` otherwise.
    An empty input is vacuously valid (a quiet day has no signals).
    """
    records = [dict(e) for e in events]
    errors: list[str] = []
    required = ("id", "kind", "geometry", "start", "end", "intensity", "source", "label")
    for i, e in enumerate(records):
        for k in required:
            if e.get(k) is None or (k != "intensity" and e.get(k) == ""):
                errors.append(f"[{i}] missing required key {k!r}")
        kind = e.get("kind")
        if kind is not None and kind not in TIMED_EVENT_KINDS:
            errors.append(f"[{i}] invalid kind {kind!r} (allowed {TIMED_EVENT_KINDS})")
        geom = e.get("geometry") or []
        if not geom:
            errors.append(f"[{i}] empty geometry")
        for p in geom:
            lat, lng = p.get("lat"), p.get("lng")
            if lat is None or lng is None or not point_in_bbox(lat, lng):
                errors.append(f"[{i}] geometry vertex {(lat, lng)} outside London bbox")
        s, en = e.get("start"), e.get("end")
        if s and en:
            try:
                if _parse_iso(en) <= _parse_iso(s):
                    errors.append(f"[{i}] end ({en}) not after start ({s})")
            except ValueError:
                errors.append(f"[{i}] unparseable start/end ({s!r}/{en!r})")
        inten = e.get("intensity")
        if inten is None or not (0.0 < float(inten) <= 1.0):
            errors.append(f"[{i}] intensity {inten!r} outside (0, 1]")
        src = e.get("source")
        if src is not None and src not in VALID_PROVENANCE:
            errors.append(f"[{i}] source {src!r} not in {VALID_PROVENANCE}")
    if errors:
        raise AssertionError("TimedEvent failures:\n" + "\n".join(errors[:15]))
    return records


def is_fresh(fetched_at: str, max_age_days: float = 400.0, now: str | datetime | None = None) -> bool:
    """Freshness helper: True iff ``fetched_at`` is within ``max_age_days`` of now.

    ``now`` may be an ISO string, a datetime, or None (-> current UTC time).
    A ``fetched_at`` in the future (negative age) is treated as not fresh.
    """
    if isinstance(now, datetime):
        ref = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    elif isinstance(now, str):
        ref = _parse_iso(now)
    else:
        ref = datetime.now(timezone.utc)
    ts = _parse_iso(fetched_at)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age_days = (ref - ts).total_seconds() / 86400.0
    return 0.0 <= age_days <= max_age_days
