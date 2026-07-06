"""End-to-end demo: synthetic Extremadura-style Sn-W-Li window.

Outputs (./out):
  prospectivity.tif        WofE posterior probability raster
  parcels_scored.geojson   parcels with score components
  top_parcels.csv          top 25 ranked parcels
  demo_map.png             overview figure
"""

from __future__ import annotations

import os

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import rasterio
from rasterio.transform import from_origin

from subsuelo.config import BBOX, CELL_SIZE, CRS
from subsuelo.ingest import synthetic as syn
from subsuelo.model.wofe import posterior_probability
from subsuelo.score.parcels import score_parcels


def main(seed: int = 7, outdir: str = "out") -> None:
    os.makedirs(outdir, exist_ok=True)
    rng = np.random.default_rng(seed)

    # --- ingest (synthetic; swap for ingest.live with network) ---
    dist_contact, granite, _, _ = syn.make_geology(rng)
    dist_fault, faults = syn.make_faults(rng)
    occurrences = syn.make_occurrences(rng, dist_contact, granite)
    geochem = syn.make_geochem(rng, dist_contact, occurrences)
    parcels = syn.make_parcels(rng)
    protected = syn.make_protected(rng)

    # deposits grid for training
    ny, nx = syn.grid_shape()
    dep = np.zeros((ny, nx), dtype=bool)
    for pt in occurrences.geometry:
        c = int((pt.x - BBOX[0]) / CELL_SIZE)
        r = int((BBOX[3] - pt.y) / CELL_SIZE)
        if 0 <= r < ny and 0 <= c < nx:
            dep[r, c] = True

    # --- model ---
    layers = {
        "near_contact": (dist_contact, 2_000.0, "<="),
        "geochem_anom": (geochem, float(np.percentile(geochem, 85)), ">="),
        "near_fault": (dist_fault, 3_000.0, "<="),
    }
    posterior, weights = posterior_probability(layers, dep)
    print("WofE weights (W+, W-):")
    for k, (wp, wm) in weights.items():
        print(f"  {k:14s} W+={wp:+.2f}  W-={wm:+.2f}")

    transform = from_origin(BBOX[0], BBOX[3], CELL_SIZE, CELL_SIZE)
    with rasterio.open(
        f"{outdir}/prospectivity.tif", "w", driver="GTiff", height=ny, width=nx,
        count=1, dtype="float32", crs=CRS, transform=transform,
    ) as dst:
        dst.write(posterior.astype("float32"), 1)

    # --- score ---
    scored = score_parcels(parcels, posterior, protected)
    scored.to_file(f"{outdir}/parcels_scored.geojson", driver="GeoJSON")
    cols = ["parcel_id", "score", "prospectivity", "prospectivity_raw", "eur_ha_effective",
            "cheapness", "protected_frac", "listed", "area_ha"]
    scored[cols].head(25).to_csv(f"{outdir}/top_parcels.csv", index=False)

    listed_top = scored[scored.listed].head(5)
    print("\nTop 5 LISTED parcels:")
    print(listed_top[["parcel_id", "score", "prospectivity", "prospectivity_raw",
                      "eur_ha_effective", "protected_frac"]].to_string(index=False))

    # --- map ---
    fig, axes = plt.subplots(1, 2, figsize=(15, 7.5))
    extent = (BBOX[0], BBOX[2], BBOX[1], BBOX[3])

    ax = axes[0]
    im = ax.imshow(posterior, extent=extent, cmap="inferno", origin="upper")
    faults.plot(ax=ax, color="cyan", linewidth=0.8, alpha=0.7)
    occurrences.plot(ax=ax, color="lime", markersize=12, marker="^")
    protected.boundary.plot(ax=ax, color="deepskyblue", linewidth=1.5)
    ax.set_title("WofE posterior · occurrences (▲) · faults · protected (blue)")
    plt.colorbar(im, ax=ax, fraction=0.04)

    ax = axes[1]
    scored.plot(ax=ax, column="score", cmap="viridis", legend=True,
                edgecolor="grey", linewidth=0.2,
                legend_kwds={"fraction": 0.04, "label": "composite score"})
    sl = scored[scored.listed]
    sl.centroid.plot(ax=ax, color="red", markersize=10, marker="o")
    ax.set_title("Parcel composite score · listed parcels (red)")

    for ax in axes:
        ax.set_xticks([]), ax.set_yticks([])
    plt.tight_layout()
    plt.savefig(f"{outdir}/demo_map.png", dpi=140)
    print(f"\nOutputs in ./{outdir}/")


if __name__ == "__main__":
    main()
