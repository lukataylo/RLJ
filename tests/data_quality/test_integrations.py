"""London open-data integration adapters normalize external payloads safely."""
from __future__ import annotations

import integrations
import quality


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append(
            {"url": url, "params": params or {}, "timeout": timeout, "headers": headers or {}}
        )
        return _FakeResponse(self.payload)


def test_tfl_client_adds_app_key_and_fetches_json():
    session = _FakeSession([{"id": "ok"}])
    client = integrations.TflClient(app_key="secret", session=session)

    payload = client.road_disruptions()

    assert payload == [{"id": "ok"}]
    assert session.calls[0]["url"] == "https://api.tfl.gov.uk/Road/All/Disruption"
    assert session.calls[0]["params"]["app_key"] == "secret"
    assert "RLJ" in session.calls[0]["headers"]["user-agent"]


def test_tfl_road_disruptions_normalize_to_contract_shape(validate_entity):
    raw = [
        {
            "id": "TIMS-1",
            "severity": "Serious",
            "hasClosures": True,
            "lastModifiedTime": "2026-06-05T20:00:00Z",
            "geography": {"type": "Point", "coordinates": [-0.12, 51.5]},
        },
        {
            "id": "outside-london",
            "geography": {"type": "Point", "coordinates": [-4.0, 55.0]},
        },
    ]

    events = integrations.normalize_tfl_road_disruptions(raw)

    assert len(events) == 1
    assert events[0]["kind"] == "road_closure"
    assert events[0]["source"] == "tfl"
    validate_entity("DisruptionEvent", events[0])


def test_bike_points_and_air_quality_stay_in_london_bbox():
    bikes = integrations.normalize_tfl_bike_points(
        [
            {
                "id": "BikePoints_1",
                "commonName": "River Street, Clerkenwell",
                "lat": 51.5292,
                "lon": -0.1099,
                "additionalProperties": [
                    {"key": "NbBikes", "value": "6"},
                    {"key": "NbEmptyDocks", "value": "13"},
                    {"key": "Installed", "value": "true"},
                    {"key": "Locked", "value": "false"},
                ],
            }
        ]
    )
    air = integrations.normalize_london_air_index(
        {
            "HourlyAirQualityIndex": {
                "LocalAuthority": {
                    "Site": {
                        "@SiteCode": "CT3",
                        "@SiteName": "City of London - Walbrook Wharf",
                        "@Latitude": "51.51050",
                        "@Longitude": "-0.09650",
                        "@BulletinDate": "2026-06-05 22:00:00",
                        "Species": [
                            {"@SpeciesCode": "NO2", "@AirQualityIndex": "2", "@AirQualityBand": "Low"},
                            {"@SpeciesCode": "PM10", "@AirQualityIndex": "3", "@AirQualityBand": "Low"},
                        ],
                    }
                }
            }
        }
    )

    assert bikes[0]["bikes"] == 6
    assert bikes[0]["empty_docks"] == 13
    assert air[0]["max_index"] == 3
    assert quality.point_in_bbox(bikes[0]["lat"], bikes[0]["lng"])
    assert quality.point_in_bbox(air[0]["lat"], air[0]["lng"])


def test_london_datastore_and_citymapper_fallbacks():
    datasets = integrations.normalize_london_datastore_search(
        {
            "result": {
                "results": [
                    {
                        "id": "roads",
                        "title": "Road traffic counts",
                        "metadata_modified": "2026-06-01T10:00:00",
                        "resources": [{"name": "CSV", "format": "CSV", "url": "https://example.test/roads.csv"}],
                    }
                ]
            }
        }
    )
    url = integrations.citymapper_directions_url(
        start_lat=51.5, start_lng=-0.12, end_lat=51.52, end_lng=-0.08
    )

    assert datasets[0]["source"] == "london-datastore"
    assert datasets[0]["resources"][0]["format"] == "CSV"
    assert url.startswith("https://citymapper.com/directions?")
    assert "startcoord=51.5%2C-0.12" in url
