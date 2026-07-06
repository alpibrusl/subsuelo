"""Run the prospectivity pipeline for any registered region.

    python run_region.py spain     # peninsular Spain (IGME) + Catastro drill
    python run_region.py europe    # Variscan Europe (EGDI), raster-only
    python run_region.py           # lists available regions

Then: python run_ui.py --no-run
"""

import sys

from subsuelo import pipeline, regions

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("regions:", ", ".join(sorted(regions.REGIONS)))
        raise SystemExit(f"usage: python run_region.py <{'|'.join(sorted(regions.REGIONS))}>")
    pipeline.run(regions.get(sys.argv[1]))
