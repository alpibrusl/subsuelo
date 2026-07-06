"""End-to-end LIVE pipeline: real IGME geology/occurrences + Catastro parcels.

Fetches over the network (see subsuelo/ingest/live.py), runs the same WofE
model + parcel scoring as run_demo.py, and writes the same ./out artifacts
plus out/occurrences.geojson (real BDMIN mineral showings) for the UI.

    python run_live.py                 # default municipios (config.CATASTRO_MUNICIPIOS)
    python run_live.py --municipios 10118 10004

Prices: idealista needs an approved OAuth token, so cadastral value is
unavailable here — the cheapness component is neutralized and the score is
driven by real prospectivity + protected-area friction. Everything else is live.
"""

from __future__ import annotations

import argparse
import os

import numpy as np
import geopandas as gpd
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin

import subsuelo.config as config
from subsuelo.config import (BBOX, CELL_SIZE, CRS, CATASTRO_MUNICIPIOS,
                             PARCEL_MIN_AREA_HA, TARGET_COMMODITIES)
from subsuelo.ingest import live, rasterize
from subsuelo.model.wofe import posterior_probability
from subsuelo.score.parcels import score_parcels


def bbox_4326() -> tuple:
    t = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
    xmin, ymin = t.transform(BBOX[0], BBOX[1])
    xmax, ymax = t.transform(BBOX[2], BBOX[3])
    return (xmin, ymin, xmax, ymax)


def main(municipios=None, outdir: str = "out") -> None:
    os.makedirs(outdir, exist_ok=True)
    municipios = municipios or CATASTRO_MUNICIPIOS
    bb = bbox_4326()
    print(f"window (lon/lat): {tuple(round(v, 3) for v in bb)}")

    # --- ingest: IGME geology + occurrences ---
    print("· IGME geology lines (contacts + faults) …")
    lines = live.igme_geology_lines(bb)
    tipo = lines.get("TIPO", pd.Series([""] * len(lines))).fillna("")
    contacts = lines[tipo.str.contains("Contacto", case=False)]
    faults = lines[tipo.str.startswith("Falla")]
    print(f"    {len(contacts)} contact traces, {len(faults)} fault traces")

    print("· IGME granite/pegmatite lithologies …")
    granite = live.igme_granite(bb)
    print(f"    {len(granite)} granite host-rock polygons")

    print("· IGME BDMIN mineral occurrences …")
    occ = live.igme_occurrences(bb)
    targets = occ[occ["commodity"].isin(["Sn", "W", "Li"])]
    print(f"    {len(occ)} occurrences total, {len(targets)} Sn/W/Li (training)")

    # --- grids ---
    dist_contact = rasterize.distance_grid(contacts.geometry)
    dist_fault = rasterize.distance_grid(faults.geometry)
    granite_mask = rasterize.burn_mask(granite.geometry).astype("float32")
    dep = rasterize.deposits_grid(targets)
    if dep.sum() == 0:  # fall back to all occurrences if no Sn/W/Li in window
        dep = rasterize.deposits_grid(occ)
        print("    (no Sn/W/Li occurrences — training on all substances)")

    # --- model ---
    layers = {
        "near_contact": (dist_contact, 2_000.0, "<="),
        "near_fault":   (dist_fault, 3_000.0, "<="),
        "in_granite":   (granite_mask, 0.5, ">="),
    }
    posterior, weights = posterior_probability(layers, dep)
    print("\nWofE weights (combined, W+, W-):")
    for k, (wp, wm) in weights.items():
        print(f"  {k:14s} W+={wp:+.2f}  W-={wm:+.2f}")

    ny, nx = dep.shape
    transform = from_origin(BBOX[0], BBOX[3], CELL_SIZE, CELL_SIZE)

    def write_raster(arr, path):
        with rasterio.open(path, "w", driver="GTiff", height=ny, width=nx,
                           count=1, dtype="float32", crs=CRS, transform=transform) as dst:
            dst.write(arr.astype("float32"), 1)

    write_raster(posterior, f"{outdir}/prospectivity.tif")

    # per-commodity posteriors: same evidence, trained on every showing whose
    # substance MENTIONS that metal (so "Estaño, Litio" trains both Sn and Li).
    # MIN_TRAIN flags statistically thin models (e.g. Li here) as indicative.
    MIN_TRAIN = 8
    sub = occ["sustancia"].fillna("").str.lower()
    per_commodity, train_counts = {}, {}
    for c in ("Sn", "W", "Li"):
        bearing = occ[sub.apply(lambda s: any(k in s for k in TARGET_COMMODITIES[c]))]
        n = len(bearing)
        train_counts[c] = n
        if n == 0:
            continue
        dep_c = rasterize.deposits_grid(bearing)
        post_c, _ = posterior_probability(layers, dep_c)
        per_commodity[c] = post_c
        write_raster(post_c, f"{outdir}/prospectivity_{c}.tif")
        print(f"  {c}: trained on {n} showings"
              + ("  (sparse — indicative only)" if n < MIN_TRAIN else ""))

    # --- ingest: Catastro parcels ---
    print("\n· Catastro parcels …")
    frames = []
    for code, name in municipios:
        try:
            g = live.catastro_parcels(code, name, min_area_ha=PARCEL_MIN_AREA_HA)
            print(f"    {name:24s} {len(g):5d} parcels ≥ {PARCEL_MIN_AREA_HA} ha")
            frames.append(g)
        except Exception as e:
            print(f"    {name:24s} FAILED: {type(e).__name__}: {str(e)[:80]}")
    if not frames:
        raise SystemExit("no parcels fetched — aborting")
    parcels = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=CRS)

    # --- ingest: friction layers (protected areas + existing mining rights) ---
    print("· Natura 2000 protected areas …")
    protected = live.natura2000(bb)
    print(f"    {len(protected)} protected polygons"
          + ("" if len(protected) else "  (none / WFS unavailable → friction=0)"))
    print("· IGME BDMIN mine workings …")
    workings = live.mining_workings(bb)
    n_active = int(workings["active"].sum()) if len(workings) else 0
    print(f"    {len(workings)} workings ({n_active} active) in window")
    if len(workings):
        workings.to_file(f"{outdir}/mining_workings.geojson", driver="GeoJSON")
    elif os.path.exists(f"{outdir}/mining_workings.geojson"):
        os.remove(f"{outdir}/mining_workings.geojson")

    print("· Catastro Minero legal concessions (MITECO WFS) …")
    concessions = live.mining_concessions(bb)
    blocking = concessions[concessions["blocks"]] if len(concessions) else concessions
    print(f"    {len(concessions)} concessions ({len(blocking)} block acquisition)")
    if len(concessions):
        concessions.to_file(f"{outdir}/mining_concessions.geojson", driver="GeoJSON")
    elif os.path.exists(f"{outdir}/mining_concessions.geojson"):
        os.remove(f"{outdir}/mining_concessions.geojson")

    # real friction: parcels overlapping a granted/pending concession are claimed
    claimed = blocking if len(blocking) else None

    # drop national-flow artifacts so the Cáceres view is consistent
    for stale in ("hotspots.geojson", "hotspot_parcels.geojson",
                  "web/hotspots.geojson", "web/hotspot_parcels.geojson"):
        p = os.path.join(outdir, stale)
        if os.path.exists(p):
            os.remove(p)

    # --- score (combined + per-commodity; legal concessions raise friction) ---
    scored = score_parcels(parcels, posterior, protected,
                           extra_posteriors=per_commodity, claimed=claimed)
    scored.to_file(f"{outdir}/parcels_scored.geojson", driver="GeoJSON")

    # commodity metadata for the UI selector
    import json
    with open(f"{outdir}/commodities.json", "w") as f:
        json.dump({
            "min_train": MIN_TRAIN,
            "commodities": [
                {"key": c, "n_train": train_counts.get(c, 0),
                 "reliable": train_counts.get(c, 0) >= MIN_TRAIN,
                 "raster": f"prospectivity_{c}.png"}
                for c in ("Sn", "W", "Li") if c in per_commodity
            ],
        }, f)
    occ.to_crs(CRS).to_file(f"{outdir}/occurrences.geojson", driver="GeoJSON")
    cols = ["parcel_id", "municipio", "score", "prospectivity", "prospectivity_raw",
            "cheapness", "protected_frac", "area_ha"]
    scored[cols].head(25).to_csv(f"{outdir}/top_parcels.csv", index=False)

    # --- mineral summary (what the user asked for) ---
    print("\nMineral occurrences by commodity:")
    for sub, n in occ["commodity"].value_counts().items():
        print(f"  {sub:6s} {n}")
    print("\nTop Sn/W/Li showings in window:")
    tt = targets[["name", "sustancia", "municipio"]].head(10)
    print(tt.to_string(index=False) if len(tt) else "  (none)")

    print(f"\nTop parcels:\n{scored[['parcel_id','municipio','score','prospectivity']].head(5).to_string(index=False)}")
    print(f"\nOutputs in ./{outdir}/")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--municipios", nargs="*", help="INE codes, e.g. 10118 10004")
    args = ap.parse_args()
    munis = None
    if args.municipios:
        by_code = {c: (c, n) for c, n in CATASTRO_MUNICIPIOS}
        munis = [by_code.get(c, (c, c)) for c in args.municipios]
    main(municipios=munis)
