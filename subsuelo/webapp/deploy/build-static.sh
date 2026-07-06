#!/usr/bin/env bash
# Build a fully self-contained static bundle in webapp/dist/ — the JS/CSS/HTML
# plus a real copy of the region data (the dev setup symlinks public/regions to
# ../out/web/regions; a deployable bundle must ship the actual files).
#
#   ./deploy/build-static.sh
#
# Result: webapp/dist/ is a static site you can drop on any host (Netlify,
# Vercel, GitHub Pages, S3, Cloudflare Pages…). See DEPLOY.md.
set -euo pipefail
cd "$(dirname "$0")/.."          # webapp/

DATA="../out/web"
if [ ! -f "$DATA/regions.json" ]; then
  echo "✗ no region data at $DATA — run the pipeline first:  (cd .. && python build.py)" >&2
  exit 1
fi

echo "▶ vite build (js/css/html)…"
npm run build                    # → dist/ (tsc -b && vite build)

echo "▶ copying region data into dist/ (dereferencing the symlink)…"
rm -rf dist/regions dist/regions.json
cp -RL "$DATA/regions" dist/regions
cp -L  "$DATA/regions.json" dist/regions.json
# the app never reads build.json, but ship it as a public manifest of freshness
[ -f "$DATA/build.json" ] && cp -L "$DATA/build.json" dist/build.json || true

BYTES=$(du -sh dist | cut -f1)
echo "✓ dist/ ready ($BYTES) — deploy this directory. See webapp/DEPLOY.md"
