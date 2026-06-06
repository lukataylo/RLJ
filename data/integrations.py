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
