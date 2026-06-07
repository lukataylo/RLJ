"""Live London open-data integrations for the RLJ demo.

The production demo must remain local-first, so these clients are deliberately
small adapters around public feeds. They fetch only operational context, then
normalize it into the repo's existing contracts or into lightweight metadata
that can be cached and inspected offline.

Supported feeds:
  * TfL Unified API: road disruptions, BikePoint, line status
  * LondonAir/ERG: hourly London air-quality index
  * London Datastore CKAN: dataset discovery for transport/health context
  * Citymapper: no public self-serve API since 2023; expose deep links only
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlencode

import requests

import quality

DEFAULT_TIMEOUT_S = 10.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _point_in_london(lat: float | None, lng: float | None) -> bool:
    return lat is not None and lng is not None and quality.point_in_bbox(lat, lng)


@dataclass
class JsonFeedClient:
    """Tiny requests wrapper that keeps auth, timeout and user-agent consistent."""

    base_url: str
    default_params: dict[str, Any] = field(default_factory=dict)
    timeout_s: float = DEFAULT_TIMEOUT_S
    session: requests.Session | None = None

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        session = self.session or requests.Session()
        merged = {k: v for k, v in self.default_params.items() if v not in (None, "")}
        if params:
            merged.update({k: v for k, v in params.items() if v not in (None, "")})
        url = self.base_url.rstrip("/") + "/" + path.lstrip("/")
        response = session.get(
            url,
            params=merged,
            timeout=self.timeout_s,
            headers={"user-agent": "RLJ medical-logistics-demo/1.0"},
        )
        response.raise_for_status()
        return response.json()


class TflClient(JsonFeedClient):
    """TfL Unified API adapter.

    Many endpoints currently work without auth. If ``TFL_APP_KEY`` is set, it is
    appended as ``app_key`` as requested by TfL's portal.
    """

    def __init__(self, app_key: str | None = None, **kwargs: Any):
        params = {"app_key": app_key or os.getenv("TFL_APP_KEY")}
        super().__init__("https://api.tfl.gov.uk", default_params=params, **kwargs)

    def road_disruptions(self, road_id: str = "All") -> list[dict]:
        return self.get_json(f"/Road/{road_id}/Disruption")

    def bike_points(self) -> list[dict]:
        return self.get_json("/BikePoint")

    def line_status(self, mode: str = "tube") -> list[dict]:
        return self.get_json(f"/Line/Mode/{mode}/Status")


class LondonAirClient(JsonFeedClient):
    """Imperial College LondonAir/ERG air-quality API adapter."""

    def __init__(self, **kwargs: Any):
        super().__init__("https://api.erg.ic.ac.uk/AirQuality", **kwargs)

    def hourly_monitoring_index(self, group_name: str = "London") -> dict:
        return self.get_json(f"/Hourly/MonitoringIndex/GroupName={group_name}/Json")


class LondonDatastoreClient(JsonFeedClient):
    """London Datastore CKAN discovery adapter."""

    def __init__(self, **kwargs: Any):
        super().__init__("https://data.london.gov.uk/api/action", **kwargs)

    def search_datasets(self, query: str, rows: int = 10) -> dict:
        return self.get_json("/package_search", {"q": query, "rows": rows})


def normalize_tfl_road_disruptions(payload: Iterable[dict], limit: int | None = None) -> list[dict]:
    """Convert TfL road disruptions to contract-shaped ``DisruptionEvent`` dicts."""
    out: list[dict] = []
    for item in payload:
        coords = _extract_tfl_geometry(item)
        if not coords:
            continue
        event = {
            "id": item.get("id") or f"tfl-{len(out) + 1}",
            "kind": "road_closure" if item.get("hasClosures") else "traffic",
            "geometry": coords,
            "source": "tfl",
            "at": item.get("lastModifiedTime")
            or item.get("currentUpdateDateTime")
            or item.get("startDateTime")
            or _now_iso(),
        }
        out.append(event)
        if limit is not None and len(out) >= limit:
            break
    return out


def _extract_tfl_geometry(item: dict) -> list[dict]:
    geography = item.get("geography") or {}
    geom_type = geography.get("type")
    coords = geography.get("coordinates")
    if geom_type == "Point" and isinstance(coords, list) and len(coords) >= 2:
        lng, lat = _coerce_float(coords[0]), _coerce_float(coords[1])
        if _point_in_london(lat, lng):
            return [{"lat": lat, "lng": lng}]
    if geom_type == "LineString" and isinstance(coords, list):
        points = []
        for pair in coords:
            if not isinstance(pair, list) or len(pair) < 2:
                continue
            lng, lat = _coerce_float(pair[0]), _coerce_float(pair[1])
            if _point_in_london(lat, lng):
                points.append({"lat": lat, "lng": lng})
        if points:
            return points

    # Some TfL payloads carry closure lines separately.
    for line in item.get("roadDisruptionLines") or []:
        line_coords = ((line.get("geometry") or {}).get("coordinates") or [])
        points = []
        for pair in line_coords:
            if not isinstance(pair, list) or len(pair) < 2:
                continue
            lng, lat = _coerce_float(pair[0]), _coerce_float(pair[1])
            if _point_in_london(lat, lng):
                points.append({"lat": lat, "lng": lng})
        if points:
            return points
    return []


def normalize_tfl_road_hazards(payload: Iterable[dict], limit: int | None = None) -> list[dict]:
    """Convert TfL road disruptions into driver-facing hazard point records.

    Output shape matches the bundled ``data/hazards.py`` snapshot:
    ``{id, description, lat, lng, severity, category}`` with the coordinate taken
    from the first in-bbox geometry vertex.
    """
    import hazards as hazards_mod

    out: list[dict] = []
    for item in payload:
        coords = _extract_tfl_geometry(item)
        if not coords:
            continue
        first = coords[0]
        lat, lng = first.get("lat"), first.get("lng")
        if not _point_in_london(lat, lng):
            continue
        description = (
            item.get("comments")
            or item.get("currentUpdate")
            or item.get("location")
            or item.get("category")
            or "TfL road disruption"
        )
        category = str(item.get("category") or "disruption").lower()
        starts = item.get("startDateTime") or item.get("constructionStartDate")
        ends = item.get("endDateTime") or item.get("constructionEndDate")
        record = {
            "id": str(item.get("id") or f"haz-{len(out) + 1}"),
            "description": str(description),
            "lat": float(lat),
            "lng": float(lng),
            "severity": hazards_mod.severity_band(item.get("severity")),
            "category": category,
        }
        # Forward-looking enrichment: planned works carry start/end dates; flag them so
        # the courier sees what is *coming*, not just what is live now.
        if starts:
            record["starts"] = str(starts)
        if ends:
            record["ends"] = str(ends)
        record["planned"] = bool(starts) and ("works" in category or "planned" in category)
        out.append(record)
        if limit is not None and len(out) >= limit:
            break
    return out


def _hhmm(ts: str | None) -> str | None:
    """Extract HH:MM from an ISO datetime string (best-effort)."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).strftime("%H:%M")
    except Exception:  # noqa: BLE001
        return None


def _ymd(ts: str | None) -> str | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).date().isoformat()
    except Exception:  # noqa: BLE001
        return None


def normalize_tfl_planned_streetworks(payload: Iterable[dict], limit: int | None = None) -> list[dict]:
    """Pull planned street/road works (with start/end dates) out of TfL road disruptions.

    Returns records in the same shape as ``data/streetworks.py``'s bundle so the result
    can be written straight to ``data/streetworks.json``. Defensive: skips anything that
    is not a dated, in-bbox planned work.
    """
    import hazards as hazards_mod

    out: list[dict] = []
    for item in payload:
        category = str(item.get("category") or "").lower()
        sub = str(item.get("subCategory") or item.get("subcategory") or "").lower()
        starts = item.get("startDateTime") or item.get("constructionStartDate")
        ends = item.get("endDateTime") or item.get("constructionEndDate")
        is_works = ("works" in category or "works" in sub or "planned" in category)
        if not (is_works and starts and ends):
            continue
        coords = _extract_tfl_geometry(item)
        if not coords:
            continue
        first = coords[0]
        lat, lng = first.get("lat"), first.get("lng")
        if not _point_in_london(lat, lng):
            continue
        date = _ymd(starts)
        start_hhmm, end_hhmm = _hhmm(starts), _hhmm(ends)
        if not (date and start_hhmm and end_hhmm):
            continue
        out.append(
            {
                "id": str(item.get("id") or f"stw-{len(out) + 1}"),
                "description": str(
                    item.get("comments") or item.get("currentUpdate")
                    or item.get("location") or "Planned street works"),
                "lat": float(lat),
                "lng": float(lng),
                "start": start_hhmm,
                "end": end_hhmm,
                "date": date,
                "authority": str(item.get("highwayAuthority") or item.get("authority") or "TfL"),
                "permit_reference": str(item.get("id") or ""),
                "traffic_management": str(item.get("subCategory") or "lane_closure").lower().replace(" ", "_"),
                "severity": hazards_mod.severity_band(item.get("severity")),
            }
        )
        if limit is not None and len(out) >= limit:
            break
    return out


def fetch_planned_streetworks(limit: int = 25) -> list[dict]:
    """Best-effort live planned-streetworks records from the keyless TfL Road API."""
    tfl = TflClient()
    return normalize_tfl_planned_streetworks(tfl.road_disruptions(), limit=limit)


class PlanningDataClient(JsonFeedClient):
    """National Planning Data platform adapter (planning.data.gov.uk, keyless)."""

    def __init__(self, **kwargs: Any):
        super().__init__("https://www.planning.data.gov.uk", **kwargs)

    def planning_applications(self, lat: float, lng: float, limit: int = 50) -> dict:
        return self.get_json(
            "/entity.json",
            {"dataset": "planning-application", "latitude": lat, "longitude": lng, "limit": limit},
        )


def normalize_planning_applications(payload: dict, limit: int | None = None) -> list[dict]:
    """Flatten Planning Data entities into major-development records (defensive)."""
    entities = payload.get("entities") or payload.get("results") or []
    out: list[dict] = []
    for e in entities:
        lat = _coerce_float(e.get("latitude") or e.get("lat"))
        lng = _coerce_float(e.get("longitude") or e.get("lng") or e.get("long"))
        point = e.get("point") or e.get("geometry")
        if (lat is None or lng is None) and isinstance(point, dict):
            coords = point.get("coordinates")
            if isinstance(coords, list) and len(coords) >= 2:
                lng, lat = _coerce_float(coords[0]), _coerce_float(coords[1])
        if not _point_in_london(lat, lng):
            continue
        out.append(
            {
                "id": str(e.get("entity") or e.get("reference") or f"pln-{len(out) + 1}"),
                "reference": str(e.get("reference") or e.get("entity") or ""),
                "description": str(e.get("name") or e.get("description") or "Planning application"),
                "lat": float(lat),
                "lng": float(lng),
                "status": str(e.get("status") or e.get("decision") or "pending").lower(),
                "authority": str(e.get("organisation-entity") or e.get("organisation") or "LPA"),
                "received_date": str(e.get("start-date") or e.get("entry-date") or ""),
                "decision_date": str(e.get("decision-date") or ""),
                "scale": "major",
                "category": str(e.get("development-type") or "development").lower(),
            }
        )
        if limit is not None and len(out) >= limit:
            break
    return out


def fetch_planning_applications(limit: int = 50, lat: float = 51.5072, lng: float = -0.1276) -> list[dict]:
    """Best-effort live major-development records from the keyless Planning Data platform."""
    client = PlanningDataClient()
    return normalize_planning_applications(client.planning_applications(lat, lng, limit), limit=limit)


def fetch_road_hazards(limit: int = 25) -> dict:
    """Refresh the live road-hazard snapshot from the keyless TfL Road API.

    Returns a payload in the same shape as ``data/hazards.py``'s bundle so it can
    be written straight to ``data/hazards.json``.
    """
    tfl = TflClient()
    hazards = normalize_tfl_road_hazards(tfl.road_disruptions(), limit=limit)
    return {
        "source": "live",
        "live": True,
        "fetched_at": _now_iso(),
        "provider": "TfL Unified API Road/All/Disruption",
        "hazards": hazards,
    }


def normalize_tfl_bike_points(payload: Iterable[dict], limit: int | None = None) -> list[dict]:
    """Return operational staging points derived from live Santander Cycle docks."""
    out: list[dict] = []
    for item in payload:
        lat, lng = _coerce_float(item.get("lat")), _coerce_float(item.get("lon"))
        if not _point_in_london(lat, lng):
            continue
        props = {
            p.get("key"): p.get("value")
            for p in item.get("additionalProperties") or []
            if isinstance(p, dict)
        }
        bikes = int(props.get("NbBikes") or 0)
        docks = int(props.get("NbEmptyDocks") or 0)
        out.append(
            {
                "id": item.get("id"),
                "name": item.get("commonName"),
                "lat": lat,
                "lng": lng,
                "bikes": bikes,
                "empty_docks": docks,
                "installed": props.get("Installed") == "true",
                "locked": props.get("Locked") == "true",
                "updated_at": props.get("TerminalNameModified") or _now_iso(),
                "source": "tfl-bikepoint",
            }
        )
        if limit is not None and len(out) >= limit:
            break
    return out


def normalize_tfl_line_status(payload: Iterable[dict]) -> list[dict]:
    """Compact mode status for agent narration and future ETA risk scoring."""
    lines: list[dict] = []
    for line in payload:
        statuses = line.get("lineStatuses") or []
        worst = min(statuses, key=lambda s: s.get("statusSeverity", 10), default={})
        lines.append(
            {
                "id": line.get("id"),
                "name": line.get("name"),
                "mode": line.get("modeName"),
                "severity": worst.get("statusSeverity"),
                "description": worst.get("statusSeverityDescription"),
                "source": "tfl-line-status",
            }
        )
    return lines


def normalize_london_air_index(payload: dict, limit: int | None = None) -> list[dict]:
    """Flatten the LondonAir hourly index to station-level records."""
    root = payload.get("HourlyAirQualityIndex") or {}
    authorities = root.get("LocalAuthority") or []
    if isinstance(authorities, dict):
        authorities = [authorities]
    out: list[dict] = []
    for authority in authorities:
        sites = authority.get("Site") or []
        if isinstance(sites, dict):
            sites = [sites]
        for site in sites:
            lat = _coerce_float(site.get("@Latitude"))
            lng = _coerce_float(site.get("@Longitude"))
            if not _point_in_london(lat, lng):
                continue
            species = site.get("Species") or []
            if isinstance(species, dict):
                species = [species]
            out.append(
                {
                    "site_code": site.get("@SiteCode"),
                    "site_name": site.get("@SiteName"),
                    "lat": lat,
                    "lng": lng,
                    "bulletin_at": site.get("@BulletinDate"),
                    "max_index": max(
                        int(s.get("@AirQualityIndex") or 0)
                        for s in species
                        if isinstance(s, dict)
                    )
                    if species
                    else 0,
                    "bands": sorted(
                        {
                            s.get("@AirQualityBand")
                            for s in species
                            if isinstance(s, dict) and s.get("@AirQualityBand")
                        }
                    ),
                    "source": "london-air",
                }
            )
            if limit is not None and len(out) >= limit:
                return out
    return out


def normalize_london_datastore_search(payload: dict, limit: int | None = None) -> list[dict]:
    result = payload.get("result") or {}
    datasets = result.get("results") or result.get("result") or []
    out: list[dict] = []
    for dataset in datasets:
        resources = [
            {"name": r.get("name"), "format": r.get("format"), "url": r.get("url")}
            for r in dataset.get("resources") or []
        ]
        out.append(
            {
                "id": dataset.get("id"),
                "title": dataset.get("title"),
                "notes": dataset.get("notes"),
                "metadata_modified": dataset.get("metadata_modified"),
                "resources": resources,
                "source": "london-datastore",
            }
        )
        if limit is not None and len(out) >= limit:
            break
    return out


def citymapper_directions_url(
    *,
    start_lat: float,
    start_lng: float,
    end_lat: float,
    end_lng: float,
) -> str:
    """Fallback integration: launch Citymapper web directions, not an API call."""
    query = urlencode(
        {
            "startcoord": f"{start_lat},{start_lng}",
            "endcoord": f"{end_lat},{end_lng}",
        }
    )
    return f"https://citymapper.com/directions?{query}"


def fetch_live_snapshot(limit: int = 25) -> dict:
    """Fetch a compact multi-feed snapshot for demos and smoke tests."""
    tfl = TflClient()
    london_air = LondonAirClient()
    datastore = LondonDatastoreClient()
    return {
        "fetched_at": _now_iso(),
        "tfl_disruptions": normalize_tfl_road_disruptions(tfl.road_disruptions(), limit=limit),
        "tfl_bike_points": normalize_tfl_bike_points(tfl.bike_points(), limit=limit),
        "tfl_line_status": normalize_tfl_line_status(tfl.line_status("tube")),
        "london_air": normalize_london_air_index(london_air.hourly_monitoring_index(), limit=limit),
        "london_datastore": normalize_london_datastore_search(
            datastore.search_datasets("transport health london", rows=limit),
            limit=limit,
        ),
        "citymapper": {
            "available": False,
            "reason": "Public self-serve APIs were discontinued on 2023-06-23.",
            "fallback": "web-directions-deep-link",
        },
    }
