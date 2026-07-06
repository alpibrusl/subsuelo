# Deploying Subsuelo

The app is a **static site** — a React bundle plus the pre-built region data
(GeoJSON / PNG / JSON). There's no server or database: everything is fetched as
static files with relative URLs, so it runs on any static host at a domain root
or a subpath.

## Build a deployable bundle

```bash
# 1. build the region data (from subsuelo/, the inner project root)
python build.py                     # writes out/web/regions/…  (~2–3 min, cached after)

# 2. build the self-contained static bundle
cd webapp
npm install                         # first time
./deploy/build-static.sh            # → webapp/dist/  (js/css/html + a real copy of the data)
```

`dist/` is fully self-contained (~150 MB, mostly the region rasters/GeoJSON).
Deploy that directory to any of:

| Host | One-liner |
|------|-----------|
| **Netlify** | `netlify deploy --prod --dir=dist` (or drag `dist/` onto app.netlify.com) |
| **Vercel** | `vercel deploy dist --prod` (or point a project at `webapp`, output dir `dist`) |
| **Cloudflare Pages** | `wrangler pages deploy dist` |
| **GitHub Pages** | push `dist/` to a `gh-pages` branch (works because assets use relative paths) |
| **S3 / any bucket** | `aws s3 sync dist/ s3://your-bucket --delete` + static-website hosting |

No SPA redirect rule is needed — the app has no client-side routing, it reads
state from the query string (`?region=&metal=&hotspot=`).

## GitHub Pages

It works — the bundle is well under the limits (biggest file ~20 MB < GitHub's
100 MB/file; total ~90 MB < the 1 GB site cap) and assets use relative paths, so
a project page (`you.github.io/repo/`) needs no config. `public/.nojekyll` is
included so Pages serves the files as-is. Two ways:

**Recommended — GitHub Actions (no git bloat).** The included workflow
[`.github/workflows/deploy-pages.yml`](../../.github/workflows/deploy-pages.yml)
builds the data + bundle in CI and deploys it as a Pages *artifact*, so the
~90 MB of regenerating data is never committed to your repo history. It also runs
weekly, so the site self-refreshes. Setup: push the repo to GitHub, then
**Settings → Pages → Source = "GitHub Actions"**. Done.

**Simple — push the built bundle to a branch.** If you'd rather not run CI:
```bash
cd webapp && ./deploy/build-static.sh
npx gh-pages -d dist -t   # -t ships .nojekyll; publishes dist/ to the gh-pages branch
```
Then set **Settings → Pages → Source = "Deploy from a branch" → gh-pages**. The
downside: each rebuild commits ~90 MB of changed data, so git history grows over
time — fine for a demo, but the Actions route avoids it.

## Keeping it fresh (scheduled updates)

The data is reproducible (`SUBSUELO_REFRESH=1 python build.py` re-fetches every
source; see the root `CLAUDE.md`). To refresh the live site on a schedule:

```bash
# rebuild data + bundle, then deploy (set DEPLOY_CMD to your host's command)
DEPLOY_CMD="netlify deploy --prod --dir=dist" ./deploy/refresh.sh
```

Put `refresh.sh` on a cron job, a GitHub Actions schedule, or your host's
scheduled-job feature (weekly is plenty — the upstream registries change slowly).
Raw downloads are cached under `out/cache`, so a flaky endpoint falls back to its
last good copy instead of breaking the site.

## Notes

- **Size:** the bundle is data-heavy (rasters + parcel GeoJSON). If a host caps
  total size, the biggest wins are minifying `occurrences.geojson` and the
  `hotspot_parcels_*.geojson` (coordinate precision) — not done yet.
- **Freshness:** `dist/build.json` carries the build timestamp + per-region source
  counts, and each region's `meta.json` has `built_at` — surface it in the UI if
  you want a visible "data as of …" badge.
- **CDN:** the map tiles (CARTO) and Leaflet load from CDNs, so the deployed site
  needs public internet (same as the dev server).
