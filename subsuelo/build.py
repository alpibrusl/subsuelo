"""Reproducible one-command build of every region's web assets.

This is the entry point for automatic updates: it fetches (or replays from
cache) all data sources, runs the deterministic transforms, and writes the web
assets + a build manifest — for every region — in one shot.

    python build.py                     # build all regions (replays raw-download cache)
    python build.py spain europe        # only these
    SUBSUELO_REFRESH=1 python build.py  # refetch all sources, overwrite cache (scheduled refresh)
    SUBSUELO_OFFLINE=1 python build.py   # rebuild from cache only, no network (CI / source outage)

Outputs (under out/web/):
    regions/<key>/…         per-region assets consumed by the webapp
    regions/<key>/provenance.json   every fetch for that region (url, bytes, cache hit, UTC)
    regions.json            region registry the UI reads
    build.json              manifest: UTC time, mode, per-region source counts + status

Each region is isolated: a failure (or a down source with no cache) is recorded
and the build moves on, leaving that region's previous assets untouched.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback

from subsuelo import pipeline, regions
from subsuelo.ingest import net
from subsuelo.web import export


def _mode() -> str:
    if net._flag("SUBSUELO_OFFLINE"):
        return "offline (cache only)"
    if net._flag("SUBSUELO_REFRESH"):
        return "refresh (refetch all)"
    if net._flag("SUBSUELO_NO_CACHE"):
        return "no-cache (fetch, don't store)"
    return "cache (replay, fetch on miss)"


def build(keys: list[str], outdir: str = "out") -> dict:
    built_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    manifest = {"built_at": built_at, "mode": _mode(), "regions": {}}

    for key in keys:
        print(f"\n{'='*70}\n▶ region: {key}\n{'='*70}")
        net.reset_provenance()
        t0 = time.time()
        try:
            summary = pipeline.run(regions.get(key), outdir=outdir) or {}
            export.export(outdir=outdir)   # mirrors out/web → out/web/regions/<key>/
            rdir = os.path.join(outdir, "web", "regions", key)
            os.makedirs(rdir, exist_ok=True)
            net.dump_provenance(os.path.join(rdir, "provenance.json"))
            fetches = list(net.PROVENANCE)
            summary.update({
                "status": "ok",
                "elapsed_s": round(time.time() - t0, 1),
                "fetches": len(fetches),
                "fetched_live": sum(1 for f in fetches if not f.get("cache")),
                "from_cache": sum(1 for f in fetches if f.get("cache")),
                "stale_fallbacks": sum(1 for f in fetches if f.get("stale")),
                "bytes_downloaded": sum(f.get("bytes", 0) for f in fetches if not f.get("cache")),
            })
            _stamp_region_meta(rdir, built_at, summary)
            print(f"✓ {key}: {summary.get('occurrences', 0)} occ, "
                  f"{summary.get('hotspots_drilled', 0)} drilled, {summary['fetches']} fetches "
                  f"({summary['fetched_live']} live / {summary['from_cache']} cache)")
        except Exception as e:
            summary = {"status": "failed", "error": f"{type(e).__name__}: {e}",
                       "elapsed_s": round(time.time() - t0, 1)}
            print(f"✗ {key} FAILED: {summary['error']}", file=sys.stderr)
            traceback.print_exc()
        manifest["regions"][key] = summary

    os.makedirs(os.path.join(outdir, "web"), exist_ok=True)
    with open(os.path.join(outdir, "web", "build.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    ok = [k for k, s in manifest["regions"].items() if s.get("status") == "ok"]
    bad = [k for k, s in manifest["regions"].items() if s.get("status") != "ok"]
    print(f"\n{'='*70}\nbuild {built_at} [{manifest['mode']}] — ok: {ok or '—'}"
          + (f", FAILED: {bad}" if bad else ""))
    print(f"manifest → {outdir}/web/build.json")
    return manifest


def _stamp_region_meta(rdir: str, built_at: str, summary: dict) -> None:
    """Add data-freshness + source volumes to the region's meta.json so the UI
    can show 'data as of …' without a separate fetch."""
    mpath = os.path.join(rdir, "meta.json")
    if not os.path.exists(mpath):
        return
    with open(mpath) as f:
        meta = json.load(f)
    meta["built_at"] = built_at
    meta["sources"] = {k: summary[k] for k in
                       ("occurrences", "granite_polygons", "fault_traces",
                        "commodity_models", "hotspots_drilled", "parcels_total")
                       if k in summary}
    with open(mpath, "w") as f:
        json.dump(meta, f)


if __name__ == "__main__":
    keys = [a for a in sys.argv[1:] if not a.startswith("-")] or list(regions.REGIONS)
    unknown = [k for k in keys if k not in regions.REGIONS]
    if unknown:
        raise SystemExit(f"unknown region(s) {unknown}; known: {sorted(regions.REGIONS)}")
    m = build(keys)
    # non-zero exit if any region failed → a scheduler/CI can detect it
    if any(s.get("status") != "ok" for s in m["regions"].values()):
        raise SystemExit(1)
