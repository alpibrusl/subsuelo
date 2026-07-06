"""Pan-European (Variscan belt) Sn-W-Li prospectivity via EGDI.

Thin wrapper over the shared engine (subsuelo/pipeline.py) with the 'europe'
region (subsuelo/regions.py). Raster-only + ranked hotspots (cadastres are
per-country, so no parcel drill).

    python run_europe.py       # then: python run_ui.py --no-run
"""

from subsuelo import pipeline, regions

if __name__ == "__main__":
    pipeline.run(regions.get("europe"))
