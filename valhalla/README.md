# Valhalla — Offline Routing for Greater London (PulseGo)

Self-contained [Valhalla](https://github.com/valhalla/valhalla) routing engine for the DGX Spark
(GB10, ARM64, Ubuntu 24.04). It serves drive-time routes and time/distance matrices for Greater
London **fully offline** — patient/courier data never leaves the box. The orchestrator
(`:8000`) and routing service (`:8100`) call it on `:8002`.

We use the turnkey image [`ghcr.io/nilsnolde/docker-valhalla`](https://github.com/nilsnolde/docker-valhalla),
which auto-downloads the OSM extract, builds the routing tiles, and starts the HTTP server.
The image is **multi-arch and supports ARM64**, so no source build is needed on the Spark.

## Bring it up

```bash
docker compose up -d
docker compose logs -f valhalla     # watch the first build
```

The **first run** downloads the Greater London extract (~tens of MB) from Geofabrik and cuts the
routing tiles. Expect:

- Download: a few minutes (one-time, only outbound network needed).
- Tile build: a few minutes on the Spark.
- Disk: a few hundred MB of tiles in `./custom_files` (kept on the Spark's big disk).

After tiles exist, the server reuses them on every restart — startup is then seconds and
**everything is offline** (the extract download is the only network step, ever).

Check it's serving:

```bash
curl -s http://localhost:8002/status | head
```

## Verify routing works

### Time/distance matrix (`/sources_to_targets`)

A ready-made body lives in [`sources_to_targets.example.json`](./sources_to_targets.example.json)
(central-London points: near Liverpool St, Waterloo, Euston, Holborn).

```bash
curl -s http://localhost:8002/sources_to_targets \
  -H 'Content-Type: application/json' \
  --data @sources_to_targets.example.json | jq .
```

Returns a `sources_to_targets` matrix with `time` (s) and `distance` (km) for every source→target
pair.

### Point-to-point route (`/route`)

```bash
curl -s http://localhost:8002/route \
  -H 'Content-Type: application/json' \
  -d '{
        "locations": [
          {"lat": 51.51790, "lon": -0.08700},
          {"lat": 51.52460, "lon": -0.13380}
        ],
        "costing": "auto"
      }' | jq '.trip.summary'
```

## Force a tile rebuild

When you want fresh OSM data (e.g. a new Geofabrik extract):

```bash
# wipe cached tiles and let the container rebuild from the latest extract
docker compose down
rm -rf custom_files/*
docker compose up -d
```

Or, for a one-off rebuild without clearing the volume, override the env:

```bash
force_rebuild=True docker compose up -d --force-recreate
# remember to flip it back to the default afterwards
```

## Notes

- Bound to `0.0.0.0:8002` so the orchestrator / routing service on the box can reach it; restrict
  with the host firewall if exposed beyond the Spark's LAN.
- `use_tiles_ignore_pbf=True` means if a prebuilt `valhalla_tiles.tar` is dropped in
  `custom_files/`, it's loaded directly instead of re-cutting from the pbf — handy for shipping
  prebuilt tiles to an air-gapped box.
- Large artifacts (`custom_files/`, `*.osm.pbf`, `*.tar`, tiles) are git-ignored — they live on
  the Spark, not in the repo.

## Attribution

Map data © OpenStreetMap contributors, licensed under the
[Open Database License (ODbL)](https://www.openstreetmap.org/copyright). Extracts courtesy of
[Geofabrik](https://download.geofabrik.de/).
