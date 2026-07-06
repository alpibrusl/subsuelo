"""Peninsular-Spain prospectivity + hotspots + Catastro parcel drill.

Thin wrapper over the shared engine (subsuelo/pipeline.py) with the 'spain'
region (subsuelo/regions.py) — a single pass now does what run_national +
run_hotspots used to do in two.

    python run_national.py     # then: python run_ui.py --no-run
"""

from subsuelo import pipeline, regions

if __name__ == "__main__":
    pipeline.run(regions.get("spain"))
