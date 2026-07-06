# Subsuelo

**Mineral-prospectivity + land-acquisition screening for the European Sn-W-Li
and base-metal belts.** State a target metal and a budget, and get a ranked
list of land parcels you could actually acquire — fusing open geoscience,
cadastres, permitting friction, and land prices into one screening tool.

🌐 **Live demo: https://alpibrusl.github.io/subsuelo/**

## What it does

- **Prospectivity models** — Weights-of-Evidence over open geology (IGME, EGDI)
  for 16 commodities across two mineral systems: granite-related
  (Sn·W·Li·Ta·Nb·U·Mo·Be·Bi, + Ba·As·Sb as proxies) and VMS base metals
  (Cu·Zn·Pb·Ag — the Iberian Pyrite Belt).
- **Open cadastres** — hotspots drill to real land parcels in Spain, France,
  Czechia, and Germany (Saxony), border-aware where belts straddle frontiers.
- **Permitting friction** — legal mining concessions (Catastro Minero / IDECyL)
  as an acquirability signal.
- **Land prices** — real transactions (France DVF) + estimated priors (Eurostat
  NUTS-region arable-land prices, Destatis for Germany), so the budget search
  works Europe-wide.
- **Budget funnel** — a cross-region ranked buy-list: pick a metal + budget,
  see what you can acquire, click through to the parcel on the map.

## Repository

- `subsuelo/` — the Python geospatial pipeline (region-provider engine, live
  data ingestors, WofE model). Run `python build.py` to (re)build all regions.
- `subsuelo/webapp/` — the Vite + React + TypeScript front-end.
- `CLAUDE.md` — detailed architecture + data-source notes.
- `subsuelo/webapp/DEPLOY.md` — how the static site is built and deployed.

Everything is reproducible: `python build.py` fetches (or replays a cache of)
every open data source and runs deterministic transforms. See `CLAUDE.md`.

## Licence

[EUPL-1.2](LICENSE) — European Union Public Licence v1.2.

Data is derived from open sources (IGME, EGDI, Catastro, IGN, ČÚZK, GeoSN,
Eurostat, Destatis, Natural Earth); please check each provider's terms for reuse
of the underlying data.
