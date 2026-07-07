"""Shared prospectivity engine — runs any Region (see regions.py) identically:

    fetch evidence → rasterize → WofE (combined + per-commodity) → hotspots
    (+ optional parcel drill) → write ./out artifacts for the UI.

Adding a new area needs no changes here — only a new Region entry.
"""

from __future__ import annotations

import glob
import json
import os

import numpy as np
import geopandas as gpd
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.features import shapes
from rasterio.transform import from_origin
from scipy.ndimage import label, gaussian_filter
from shapely.geometry import shape as shapely_shape

import subsuelo.config as config
from .regions import Region
from .ingest import rasterize
from .model.wofe import posterior_probability
from .score.parcels import score_parcels

MIN_TRAIN = 8   # occurrences below this → per-commodity model flagged "indicative"


def _apply_region(region: Region):
    """Point the (dynamically-read) region config at this Region and return the
    snapped bbox in the region CRS + the lon/lat bbox for the fetchers."""
    config.CRS = region.crs
    config.CELL_SIZE = region.cell_size
    t = Transformer.from_crs("EPSG:4326", region.crs, always_xy=True)
    lon0, lat0, lon1, lat1 = region.lonlat
    xs, ys = [], []
    for lon in np.linspace(lon0, lon1, 25):
        for lat in (lat0, lat1):
            x, y = t.transform(lon, lat); xs.append(x); ys.append(y)
    for lat in np.linspace(lat0, lat1, 25):
        for lon in (lon0, lon1):
            x, y = t.transform(lon, lat); xs.append(x); ys.append(y)
    s = region.cell_size
    config.BBOX = (np.floor(min(xs)/s)*s, np.floor(min(ys)/s)*s,
                   np.ceil(max(xs)/s)*s, np.ceil(max(ys)/s)*s)
    return config.BBOX, region.lonlat


def _grid_shape():
    nx = int((config.BBOX[2]-config.BBOX[0])/config.CELL_SIZE)
    ny = int((config.BBOX[3]-config.BBOX[1])/config.CELL_SIZE)
    return ny, nx


def _model_layers(region, dist_contact, dist_fault, granite_mask):
    return {
        "near_granite": (dist_contact, region.near_granite_m, "<="),
        "near_fault":   (dist_fault, region.near_fault_m, "<="),
        "in_granite":   (granite_mask, 0.5, ">="),
    }


def _cell_of(x, y):
    return (int((config.BBOX[3]-y)/config.CELL_SIZE), int((x-config.BBOX[0])/config.CELL_SIZE))


def detect_hotspots(region, posterior, targets, transform):
    """Prospectivity × Sn/W/Li occurrence-density → ranked hotspot dicts."""
    ny, nx = posterior.shape
    cnt = np.zeros_like(posterior, dtype="float32")
    for g in targets.geometry:
        r, c = _cell_of(g.x, g.y)
        if 0 <= r < ny and 0 <= c < nx:
            cnt[r, c] += 1
    dens = gaussian_filter(cnt, sigma=region.dens_sigma)
    pn = (posterior-posterior.min())/((posterior.max()-posterior.min()) or 1)
    tgt = pn * (dens/(dens.max() or 1))
    tz = tgt[tgt > 0]
    hot = tgt >= (float(np.percentile(tz, region.target_pctl)) if tz.size else tgt.max())
    lab, n = label(hot, structure=np.ones((3, 3)))
    targets = targets.copy()
    targets["_lab"] = [lab[r, c] if 0 <= r < ny and 0 <= c < nx else 0
                       for r, c in (_cell_of(g.x, g.y) for g in targets.geometry)]
    comps = []
    for lid in range(1, n+1):
        mask = lab == lid
        cells = int(mask.sum()); occ_in = targets[targets["_lab"] == lid]
        if cells < region.min_cells and not len(occ_in):
            continue
        geoms = [shapely_shape(s) for s, v in shapes(mask.astype("uint8"), mask=mask, transform=transform) if v == 1]
        comps.append({
            "geometry": gpd.GeoSeries(geoms, crs=config.CRS).union_all(),
            "area_km2": round(cells*(config.CELL_SIZE/1000)**2, 1),
            "mean_post": float(posterior[mask].mean()), "n_occ": int(len(occ_in)),
            "provincia": (occ_in["provincia"].mode().iloc[0] if len(occ_in) and occ_in["provincia"].notna().any() else ""),
            "municipios": occ_in.get("municipio", occ_in.get("name", pd.Series(dtype=str))).value_counts().index.tolist()[:6],
            "top_commodity": (occ_in["commodity"].mode().iloc[0] if len(occ_in) else ""),
            "n_parcels": 0, "n_claimed": 0, "n_conc": 0,
        })
    comps.sort(key=lambda d: (d["n_occ"], d["mean_post"]), reverse=True)
    comps = comps[:region.top_k]
    for i, c in enumerate(comps, 1):
        c["rank"] = i
    return comps


def drill_hotspot(region, comp, posterior, outdir):
    """Fetch + score a hotspot's parcels and (Spain) its concessions; write
    hotspot_parcels_<rank>.geojson / hotspot_concessions_<rank>.geojson.

    Two modes: Spain resolves the hotspot's municipios to Catastro; Europe
    fetches a per-country cadastre in a small bbox around the hotspot centre."""
    rank, prov = comp["rank"], comp["provincia"]
    conc = None
    if region.parcels_bbox_provider is not None:
        # bbox mode: a `drill_radius_km` box around the hotspot's representative point
        pt = comp["geometry"].representative_point()
        r_m = region.drill_radius_km * 1000
        box = gpd.GeoSeries([pt.buffer(r_m)], crs=region.crs).to_crs("EPSG:4326").total_bounds
        parcels = region.parcels_bbox_provider(prov, tuple(box), region.parcel_min_area_ha)
    else:
        parcels = region.parcels_provider(prov, comp["municipios"],
                                          n_munis=region.drill_munis,
                                          min_area_ha=region.parcel_min_area_ha)
    if not len(parcels):
        print(f"· #{rank} {prov}: no parcels"); return
    if region.concessions_provider is not None:
        minx, miny, maxx, maxy = parcels.to_crs("EPSG:4326").total_bounds
        conc = region.concessions_provider(prov, (minx, miny, maxx, maxy))
    blocking = conc[conc["blocks"]] if conc is not None and len(conc) else None
    empty = gpd.GeoDataFrame({"site": []}, geometry=[], crs=config.CRS)
    claimed = blocking if blocking is not None and len(blocking) else None
    scored = score_parcels(parcels, posterior, empty, claimed=claimed)
    scored.to_file(f"{outdir}/hotspot_parcels_{rank}.geojson", driver="GeoJSON")
    if conc is not None and len(conc):
        conc.to_file(f"{outdir}/hotspot_concessions_{rank}.geojson", driver="GeoJSON")
    comp["n_parcels"] = int(len(scored))
    comp["n_claimed"] = int((scored["claimed_frac"] > 0).sum())
    comp["n_conc"] = int(len(conc)) if conc is not None else 0
    print(f"· #{rank} {prov}: {len(scored)} parcels, {comp['n_claimed']} claimed ({comp['n_conc']} concessions)")


def run(region: Region, outdir: str = "out") -> None:
    os.makedirs(outdir, exist_ok=True)
    # drop stale per-metal rasters from a prior region (commodity sets differ, e.g.
    # granite Sn/W/… vs VMS Cu/Zn/…), else export globs them into the wrong region
    _clear(outdir, "prospectivity_*.tif")
    bbox, bb = _apply_region(region)
    ny, nx = _grid_shape()
    print(f"[{region.key}] grid {nx}×{ny} @ {region.cell_size/1000:.0f} km ({region.crs})")

    print("· granite/granitoid lithology …")
    granite = region.granite(bb);  print(f"    {len(granite)} polygons")
    print("· faults …")
    faults = region.faults(bb);    print(f"    {len(faults)} traces")
    print("· Sn/W/Li occurrences …")
    occ = region.occurrences(bb)
    targets = occ[occ["commodity"].isin(region.hotspot_commodities)].copy()
    print(f"    {len(occ)} occurrences, {len(targets)} primary ({occ['commodity'].value_counts().to_dict()})")

    granite_mask = rasterize.burn_mask(granite.geometry).astype("float32")
    dist_contact = rasterize.distance_grid(granite.geometry.boundary)
    dist_fault = rasterize.distance_grid(faults.geometry)
    layers = _model_layers(region, dist_contact, dist_fault, granite_mask)

    posterior, weights = posterior_probability(layers, rasterize.deposits_grid(targets))
    print("WofE weights:", {k: (round(wp, 2), round(wm, 2)) for k, (wp, wm) in weights.items()})

    transform = from_origin(bbox[0], bbox[3], region.cell_size, region.cell_size)

    def write_raster(a, path):
        with rasterio.open(path, "w", driver="GTiff", height=ny, width=nx, count=1,
                           dtype="float32", crs=region.crs, transform=transform) as d:
            d.write(a.astype("float32"), 1)

    write_raster(posterior, f"{outdir}/prospectivity.tif")

    sub = occ["sustancia"].fillna("").str.lower()
    train = {}
    for c in region.commodities:
        bearing = occ[(occ["commodity"] == c) |
                      sub.apply(lambda s: any(k in s for k in config.TARGET_COMMODITIES[c]))]
        train[c] = len(bearing)
        if len(bearing):
            post_c, _ = posterior_probability(layers, rasterize.deposits_grid(bearing))
            write_raster(post_c, f"{outdir}/prospectivity_{c}.tif")

    # export dots for every selectable commodity (Ta/Nb included), not just the
    # Sn/W/Li primaries that drive hotspots
    occ[occ["commodity"].isin(region.commodities)].to_crs(region.crs) \
        .to_file(f"{outdir}/occurrences.geojson", driver="GeoJSON")
    with open(f"{outdir}/commodities.json", "w") as f:
        json.dump({"min_train": MIN_TRAIN, "region": region.key,
                   "region_label": region.menu or region.label,
                   "region_description": region.label, "commodities": [
            {"key": c, "n_train": train.get(c, 0),
             # proxy commodities are host-mismatched → always "indicative"
             "reliable": train.get(c, 0) >= MIN_TRAIN and c not in region.proxy_commodities,
             "proxy": c in region.proxy_commodities,
             "raster": f"prospectivity_{c}.png"} for c in region.commodities if train.get(c, 0) > 0]}, f)

    # --- hotspots (+ optional parcel drill) ---
    _clear(outdir, "hotspot_parcels_*.geojson", "hotspot_concessions_*.geojson")
    comps = detect_hotspots(region, posterior, targets, transform)
    print(f"hotspots: {len(comps)}; top {comps[0]['provincia']} "
          f"({comps[0]['n_occ']} showings, {comps[0]['area_km2']} km²)" if comps else "no hotspots")
    if region.drill:
        for c in comps[:region.drill_hotspots]:
            drill_hotspot(region, c, posterior, outdir)

    keys = ["rank", "provincia", "area_km2", "n_occ", "mean_post", "top_commodity",
            "municipios", "n_parcels", "n_claimed", "n_conc"]
    gpd.GeoDataFrame([{k: (json.dumps(c[k]) if k == "municipios" else c[k]) for k in keys}
                      | {"geometry": c["geometry"]} for c in comps],
                     geometry="geometry", crs=region.crs).to_crs("EPSG:4326") \
        .to_file(f"{outdir}/hotspots.geojson", driver="GeoJSON")

    # drop artifacts from other run types so the view is consistent
    _clear(outdir, "parcels_scored.geojson", "mining_workings.geojson", "mining_concessions.geojson",
           "hotspot_parcels.geojson")
    print(f"\n[{region.key}] outputs in ./{outdir}/  →  python run_ui.py --no-run")

    # summary for the build manifest (build.py) — source volumes + model + drill
    return {
        "region": region.key,
        "granite_polygons": int(len(granite)),
        "fault_traces": int(len(faults)),
        "occurrences": int(len(occ)),
        "commodity_counts": {str(k): int(v) for k, v in occ["commodity"].value_counts().items()},
        "commodity_models": {c: int(train.get(c, 0)) for c in config.COMMODITIES if train.get(c, 0) > 0},
        "hotspots": int(len(comps)),
        "hotspots_drilled": int(sum(1 for c in comps if c.get("n_parcels", 0) > 0)),
        "parcels_total": int(sum(c.get("n_parcels", 0) for c in comps)),
    }


def _clear(outdir, *patterns):
    for pat in patterns:
        for f in glob.glob(os.path.join(outdir, pat)) + glob.glob(os.path.join(outdir, "web", pat)):
            os.remove(f)
