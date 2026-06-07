# Data

Shared inputs for routing + the demo. Keep large artifacts out of git (see `.gitignore`).

## Sources

| What | Source | Notes |
|------|--------|-------|
| London road network | OpenStreetMap via **OSMnx** | `ox.graph_from_place("London, UK", network_type="drive")`; cache to `data/cache/london.graphml` |
| Live disruptions / closures | **TfL Unified API** (free key) | road status + planned closures → `DisruptionEvent` |
| Facilities (GP / hospital / lab / pharmacy) | NHS ODS or London Datastore; OSM `amenity=hospital\|clinic\|pharmacy` | seeds job origins/destinations |
| Demand (delivery requests) | **synthesised** | realistic clinic→lab pairs, STAT/urgent/routine mix, clinical stability windows |
| Planned works | Street Manager-style works bundle | timed road closures for anticipatory routing |
| Roadside message signs | TfL Unified API `VariableMessageSign` | live/fallback VMS messages for NemoClaw narration |
| Kerbside loading / handoff | borough kerbside/loading restrictions | legal stop points near labs and hospitals |
| Weather / air / flood / NHS pressure / cycle infra | Open-Meteo, LAQN, Environment Agency, NHS/TfL representative feeds | civic risk modifiers and operational overlays |

## Demand generator (routing/frontend share this)

A small script that emits `DeliveryJob[]` over a simulated morning is the cleanest way to
drive the demo deterministically. Put it here (`data/generate_demand.py`) so all streams
replay the same scenario. Until it exists, use `contracts/samples/optimize_request.json`.

> Real courier data isn't available — say so in the pitch and keep the generator clinically
> plausible (sample stability windows, STAT vs routine ratios).
