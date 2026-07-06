# subsuelo

Prototype pipeline: mineral prospectivity × land price × availability, per parcel.
Demo window: 100×100 km, Extremadura-style Sn-W-Li setting, EPSG:25830, 500 m cells.

## Status — read this first

| Component | State |
|---|---|
| WofE prospectivity model (`model/wofe.py`) | Implemented, runs in demo |
| Parcel scoring: zonal stats + price rank + protected friction (`score/parcels.py`) | Implemented, runs in demo |
| Synthetic data generator (`ingest/synthetic.py`) | Implemented, runs in demo |
| Live ingestors: Catastro INSPIRE, IGME WFS, idealista API (`ingest/live.py`) | **Written but never executed against live services** — developed offline; IGME layer names must be pinned by browsing the services root; idealista requires approved API credentials |
| PostGIS / tiles / UI | Not started |

## Run

```bash
pip install -r requirements.txt
python run_demo.py
```

Outputs in `./out/`: `prospectivity.tif`, `parcels_scored.geojson`, `top_parcels.csv`, `demo_map.png`.

## Design

1. **Evidence layers** → binary via thresholds: distance-to-granite-contact ≤ 2 km,
   geochem ≥ P85, distance-to-fault ≤ 3 km.
2. **WofE** (Agterberg/Bonham-Carter, 0.5 continuity correction) trained on
   occurrence points → posterior probability raster. Swap for `eis_toolkit`
   (Horizon EU) for production-grade WofE/RF/CNN with identical inputs.
3. **Score** per parcel = 0.5·prospectivity-rank + 0.3·cheapness + 0.2·(1−friction).
   Cheapness uses asking €/ha when listed, cadastral €/ha otherwise. Friction is
   currently only Natura-2000 overlap; slope, mining-concession status and
   grid distance are the obvious next layers.

## Going live (order of work)

1. Pin IGME BDMIN + MAGNA WFS layer names; ingest real occurrences/geology for
   the Cáceres window.
2. Catastro INSPIRE ATOM → parcels for 3–4 municipios (rústico only).
3. Replace synthetic listings with idealista API (application needed) or a
   paste-a-URL flow.
4. Move zonal stats to `rasterstats`/PostGIS when parcel counts exceed ~10k.

Screening tool, not valuation. In Spain, metallic minerals (Sección C/D) are
state-owned; parcel scores signal exploration-access and Sección-A value, not
ore ownership.
