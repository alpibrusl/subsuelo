#!/usr/bin/env bash
# Scheduled full refresh: re-fetch every data source, re-run the deterministic
# transforms, rebuild the static bundle, then (optionally) deploy it.
#
#   ./deploy/refresh.sh                       # rebuild data + bundle
#   DEPLOY_CMD="netlify deploy --prod --dir=dist" ./deploy/refresh.sh
#
# Put it on a schedule (cron / GitHub Actions / a host's scheduled job). Sources
# are cached under out/cache, so a failed endpoint falls back to its last copy
# instead of breaking the site (see subsuelo/ingest/net.py).
set -euo pipefail
cd "$(dirname "$0")/../.."       # subsuelo/ (repo inner root)

echo "▶ refreshing region data (SUBSUELO_REFRESH=1 python build.py)…"
SUBSUELO_REFRESH=1 python build.py

echo "▶ building static bundle…"
( cd webapp && ./deploy/build-static.sh )

if [ -n "${DEPLOY_CMD:-}" ]; then
  echo "▶ deploying: $DEPLOY_CMD"
  ( cd webapp && eval "$DEPLOY_CMD" )
else
  echo "✓ webapp/dist refreshed — set DEPLOY_CMD to auto-deploy (see DEPLOY.md)"
fi
