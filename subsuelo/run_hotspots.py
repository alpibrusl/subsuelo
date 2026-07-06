"""Deprecated — hotspot detection + drill are now part of the single-pass
`run_national.py` (drill is a property of the 'spain' region). Kept as an alias.

    python run_national.py     # does raster + hotspots + parcel drill
"""

from subsuelo import pipeline, regions

if __name__ == "__main__":
    print("note: run_hotspots is folded into run_national.py — running 'spain' region")
    pipeline.run(regions.get("spain"))
