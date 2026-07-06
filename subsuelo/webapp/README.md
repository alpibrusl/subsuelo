# Subsuelo webapp (React + TypeScript)

A Vite + React + **TypeScript** + react-leaflet front-end for the prospectivity
pipeline — the guided UI (region switch → prospectivity/metal selector → ranked
hotspots → drill to parcels), on-map legend, and intro.

Data contracts (`meta.json`, hotspots, GeoJSON props) are typed in
`src/types.ts`. `npm run typecheck` (`tsc --noEmit`) must pass.

## Dev workflow

The app reads region data from `public/regions/` — a **symlink** to the pipeline
output at `../out/web/regions`:

```
public/regions       -> ../../out/web/regions
public/regions.json  -> ../../out/web/regions.json
```

So the data flow is: run the pipeline, then the app serves whatever's there.

```bash
# 1. build ALL region data reproducibly (from the subsuelo project root)
cd ..                    # subsuelo/
source .venv/bin/activate
python build.py                       # fetch (or replay cache) + transform + export every region
# SUBSUELO_REFRESH=1 python build.py  # force-refetch all sources (scheduled update)
# SUBSUELO_OFFLINE=1 python build.py   # rebuild from cache only, no network
# (writes out/web/regions/<key>/ + regions.json + a build.json manifest)

# 2. run the app
cd webapp
npm install              # first time
npm run dev              # http://localhost:5175
```

`build.py` is the reproducible entry point (see the root `CLAUDE.md`): downloads
are disk-cached under `out/cache/` and every fetch is logged to
`regions/<key>/provenance.json`, so the transforms replay deterministically and
the page can be regenerated on a schedule.

If the symlinks are missing (e.g. fresh checkout), recreate them:

```bash
ln -sfn ../../out/web/regions      public/regions
ln -sfn ../../out/web/regions.json public/regions.json
```

## Structure

- `src/types.ts` — shared interfaces (`Meta`, `Hotspot`, `RegionData`, `Toggles`…).
- `src/App.tsx` — top-level state (region, target metal, active hotspot, drill,
  toggles) + data loading.
- `src/data.ts` — typed fetch helpers + shared colours (commodity, viridis ramp).
- `src/components/Sidebar.tsx` — header, region picker, the mode tabs
  (**Find land by budget** / Explore the map), and the guided 1-2-3 flow.
- `src/components/SearchPanel.tsx` — the budget/intent funnel: filter the
  cross-region parcel pool (`parcels_index.json`) by metal, budget, size, and
  claimed-status; ranked buy-list. `data.searchParcels` does the filter/rank +
  total-budget affordability; picking a row navigates the whole app to that
  parcel (`App.onPickParcel`).
- `src/components/MapView.tsx` — `MapContainer` + a `useMap()` layer manager that
  imperatively builds/updates the raster overlay, occurrences, hotspots,
  parcels and concessions from props.
- `src/components/Legend.tsx` — on-map legend, adapts to active layers.
- `src/components/ParcelDetail.tsx` — detail card for a selected parcel.
- `src/components/Intro.tsx` — first-load explainer.

Loading states: a spinner shows while a region loads and while a hotspot's
parcels are fetched. Clicking a parcel (list or map) opens the detail card and
highlights the row.

Shareable views: the URL carries `?region=&metal=&hotspot=` (kept in sync via
`history.replaceState`); opening such a URL restores region + metal + drilled
hotspot. The **share** button in the header copies the current link.

## Notes

- Vite serves `index.html` (200) for missing files, so `data.js#getJSON` guards
  on content-type/parse errors — a missing region asset resolves to `null`.
- The vanilla single-file UI (`../subsuelo/web/index.html`, served by
  `run_ui.py`) still works and is kept as the reference implementation.
