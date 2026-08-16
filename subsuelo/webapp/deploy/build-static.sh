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

# The OpenGraph/canonical/sitemap URLs in index.html must be ABSOLUTE (link
# preview scrapers don't resolve relative ones), so they're hardcoded to the
# GitHub Pages origin. Deploying anywhere else? Point SUBSUELO_SITE_URL at the
# public base URL and they get rewritten here — everything else in the bundle
# is relative (vite base:'./') and needs no change.
CANON="https://alpibrusl.github.io/subsuelo/"
SITE_URL="${SUBSUELO_SITE_URL:-$CANON}"
case "$SITE_URL" in */) ;; *) SITE_URL="$SITE_URL/" ;; esac
if [ "$SITE_URL" != "$CANON" ]; then
  echo "▶ rewriting absolute URLs → $SITE_URL"
  for f in dist/index.html dist/robots.txt dist/sitemap.xml; do
    if [ -f "$f" ]; then sed -i.bak "s|$CANON|$SITE_URL|g" "$f"; rm -f "$f.bak"; fi
  done
fi

echo "▶ copying region data into dist/ (dereferencing the symlink)…"
rm -rf dist/regions dist/regions.json
cp -RL "$DATA/regions" dist/regions
cp -L  "$DATA/regions.json" dist/regions.json
# the app never reads build.json, but ship it as a public manifest of freshness
[ -f "$DATA/build.json" ] && cp -L "$DATA/build.json" dist/build.json || true

# the social card has to exist — a link preview without it is the whole reason
# the boot shell and meta tags are there in the first place
[ -f dist/og-cover.png ] || { echo "✗ dist/og-cover.png missing — is webapp/public/ intact?" >&2; exit 1; }

BYTES=$(du -sh dist | cut -f1)
echo "✓ dist/ ready ($BYTES) — deploy this directory. See webapp/DEPLOY.md"
