# Data

Shared inputs for routing + the demo. Keep large artifacts out of git (see `.gitignore`).

## Sources

| What | Source | Notes |
|------|--------|-------|
| London road network | OpenStreetMap via **OSMnx** | `ox.graph_from_place("London, UK", network_type="drive")`; cache to `data/cache/london.graphml` |
| Live disruptions / closures | **TfL Unified API** (optional free key) | `data/integrations.py` maps road disruptions to `DisruptionEvent`; orchestrator can sync them via `/integrations/tfl/disruptions/sync` |
| Bike/dock availability | **TfL BikePoint** | normalized to courier staging-point metadata for demos and future courier positioning |
| Public transport service risk | **TfL Line Status** | compact mode status for agent narration and future ETA risk scoring |
| Air quality | **LondonAir API** | hourly station index flattened to London-bbox station records |
| Dataset discovery | **London Datastore CKAN** | searchable catalogue metadata for transport/health datasets |
| Citymapper | **Web deep link only** | public self-serve APIs ended in 2023; use `citymapper_directions_url()` for launch links, not live routing data |
| Facilities (GP / hospital / lab / pharmacy) | NHS ODS or London Datastore; OSM `amenity=hospital\|clinic\|pharmacy` | seeds job origins/destinations |
| Demand (delivery requests) | **synthesised** | realistic clinic→lab pairs, STAT/urgent/routine mix, clinical stability windows |

## Demand generator (routing/frontend share this)

A small script that emits `DeliveryJob[]` over a simulated morning is the cleanest way to
drive the demo deterministically. Put it here (`data/generate_demand.py`) so all streams
replay the same scenario. Until it exists, use `contracts/samples/optimize_request.json`.

> Real courier data isn't available — say so in the pitch and keep the generator clinically
> plausible (sample stability windows, STAT vs routine ratios).

## Live snapshot

The deterministic data gate stays offline. To cache current public feeds when the demo
machine has network access:

```bash
python data/sync_live.py
```

This writes `data/live/london-open-data-snapshot.json` with TfL road disruptions,
TfL BikePoint, TfL line status, LondonAir stations, London Datastore matches and
the Citymapper fallback metadata.
