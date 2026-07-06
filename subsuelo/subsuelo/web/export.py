"""Export pipeline outputs into web-friendly assets for the Leaflet UI.

Pipeline outputs are in EPSG:25830 (metric UTM), which web maps can't display
directly. This module reprojects them to EPSG:4326 (lat/lon):

  out/web/parcels.geojson     parcels + score components, WGS84
  out/web/prospectivity.png   colorized (inferno) posterior overlay, WGS84
  out/web/meta.json           raster bounds, score domain, top parcels

Run `python -m subsuelo.web.export` after `run_demo.py`, or use `run_ui.py`
which chains both and serves the UI.
"""

from __future__ import annotations

import json
import os

import numpy as np
import geopandas as gpd
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling
import matplotlib
matplotlib.use("Agg")
from matplotlib import colormaps
from PIL import Image

import subsuelo.config as config

WEB_CRS = "EPSG:4326"


def _warp_raster_to_wgs84(src_path: str, land=None):
    """Warp a single-band raster to EPSG:4326. Returns (array, bounds) where
    bounds is [[south, west], [north, east]] for Leaflet's imageOverlay.
    If `land` (EPSG:4326 polygons) is given, sea cells are set to NaN."""
    with rasterio.open(src_path) as src:
        transform, width, height = calculate_default_transform(
            src.crs, WEB_CRS, src.width, src.height, *src.bounds
        )
        dst = np.zeros((height, width), dtype="float32")
        reproject(
            source=rasterio.band(src, 1),
            destination=dst,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=transform,
            dst_crs=WEB_CRS,
            resampling=Resampling.bilinear,
        )
        # bounds of the warped grid
        west = transform.c
        north = transform.f
        east = west + transform.a * width
        south = north + transform.e * height
    # mask sea cells → NaN so the heatmap doesn't bleed offshore (distance-to-
    # granite/fault is nonzero over water near coastal features)
    if land is not None and len(land):
        from rasterio.features import rasterize as _rio_rasterize
        shapes = [(g, 1) for g in land.geometry if g is not None and not g.is_empty]
        if shapes:
            lm = _rio_rasterize(shapes, out_shape=(height, width), transform=transform,
                                fill=0, all_touched=True, dtype="uint8").astype(bool)
            dst = np.where(lm, dst, np.nan)
    return dst, [[south, west], [north, east]]


def _colorize(arr: np.ndarray, cmap: str = "inferno") -> Image.Image:
    """Normalize to [0,1] and apply a matplotlib colormap → RGBA PNG."""
    finite = np.isfinite(arr)
    vmin = float(np.nanmin(arr[finite])) if finite.any() else 0.0
    vmax = float(np.nanmax(arr[finite])) if finite.any() else 1.0
    span = vmax - vmin or 1.0
    norm = np.clip((arr - vmin) / span, 0, 1)
    rgba = (colormaps[cmap](norm) * 255).astype("uint8")
    # alpha ramp: sea (non-finite) fully transparent; on land, faint for low
    # prospectivity → opaque for high, so the whole gradient reads as a heatmap
    alpha = np.where(finite, (60 + norm * 175), 0).astype("uint8")
    rgba[..., 3] = alpha
    return Image.fromarray(rgba, mode="RGBA")


def _num(v):
    """Float or None (drops NaN) for clean JSON."""
    try:
        f = float(v)
        return None if f != f else round(f, 4)
    except (TypeError, ValueError):
        return None


def _build_parcel_index(webdir: str, region: str, outdir: str) -> None:
    """Flatten every drilled hotspot's parcels into one lightweight per-region
    index (`parcels_index.json`) for the cross-hotspot budget search: one row per
    parcel with the filterable attributes + a centroid (no geometry). The full
    polygon is still fetched from hotspot_parcels_<rank>.geojson on click.

    Each parcel also gets a per-metal prospectivity (`prosp_<C>`) sampled from
    that metal's raster at its centroid — so a "find Li land" search ranks by the
    Li posterior on the exact ground, not the hotspot's dominant (usually Sn) tag.
    """
    import glob
    hs_path = os.path.join(webdir, "hotspots.geojson")
    if not os.path.exists(hs_path):
        return
    hs = gpd.read_file(hs_path)
    by_rank = {int(r["rank"]): (r.get("top_commodity") or None, r.get("provincia") or None)
               for _, r in hs.iterrows()} if "rank" in hs.columns else {}
    rows = []
    for src in glob.glob(os.path.join(webdir, "hotspot_parcels_*.geojson")):
        try:
            rank = int(os.path.basename(src).split("_")[-1].split(".")[0])
        except ValueError:
            continue
        g = gpd.read_file(src)   # already EPSG:4326 in webdir
        if not len(g):
            continue
        metal, hs_country = by_rank.get(rank, (None, None))
        cen = g.geometry.representative_point()
        for (_, row), pt in zip(g.iterrows(), cen):
            if pt is None or pt.is_empty:
                continue
            eur = _num(row.get("eur_ha_effective"))
            rows.append({
                "parcel_id": str(row.get("parcel_id")),
                "region": region,
                "rank": rank,
                "metal": metal,
                "country": (row.get("country") if "country" in g.columns and row.get("country")
                            else hs_country),
                "municipio": str(row.get("municipio") or ""),
                "area_ha": _num(row.get("area_ha")),
                "eur_ha": None if eur is None else round(eur),
                "price_kind": "real" if eur is not None else "na",
                "prospectivity": _num(row.get("prospectivity")),
                "score": _num(row.get("score")),
                "claimed": bool(_num(row.get("claimed_frac")) or 0),
                "lon": round(float(pt.x), 5), "lat": round(float(pt.y), 5),
            })
    _sample_per_metal(rows, outdir)
    _fill_estimated_prices(rows)
    with open(os.path.join(webdir, "parcels_index.json"), "w") as f:
        json.dump(rows, f)


def _fill_estimated_prices(rows: list) -> None:
    """For parcels with no real price (Spain/Germany/Czechia — France keeps DVF),
    attach an *estimated* €/ha from Eurostat NUTS2 arable-land prices by locating
    the parcel centroid in its NUTS2 region. Sets price_kind='est'."""
    unpriced = [r for r in rows if r.get("eur_ha") is None]
    if not unpriced:
        return
    from ..ingest import live
    nuts = live.nuts_price_polygons()
    if not len(nuts):
        return
    pts = gpd.GeoDataFrame(
        {"_i": list(range(len(unpriced)))},
        geometry=gpd.points_from_xy([r["lon"] for r in unpriced], [r["lat"] for r in unpriced]),
        crs="EPSG:4326")
    joined = gpd.sjoin(pts, nuts, how="left", predicate="within").drop_duplicates("_i")
    for _, jr in joined.iterrows():
        price = jr.get("eur_ha")
        if price is not None and price == price:   # not NaN
            r = unpriced[int(jr["_i"])]
            r["eur_ha"] = round(float(price))
            r["price_kind"] = "est"


def _sample_per_metal(rows: list, outdir: str) -> None:
    """Attach `prosp_<C>` to each row by sampling prospectivity_<C>.tif at the
    parcel centroid (reprojected to the raster CRS). Cheap: one pass per metal."""
    if not rows:
        return
    from pyproj import Transformer
    lons = [r["lon"] for r in rows]
    lats = [r["lat"] for r in rows]
    import glob
    for tif in glob.glob(os.path.join(outdir, "prospectivity_*.tif")):
        C = os.path.basename(tif)[len("prospectivity_"):-len(".tif")]
        with rasterio.open(tif) as ds:
            tr = Transformer.from_crs("EPSG:4326", ds.crs, always_xy=True)
            xs, ys = tr.transform(lons, lats)
            vals = [v[0] for v in ds.sample(zip(xs, ys))]
        for r, v in zip(rows, vals):
            fv = float(v) if v is not None else float("nan")
            r[f"prosp_{C}"] = None if (fv != fv or fv < 0) else round(fv, 4)


def export(outdir: str = "out") -> str:
    webdir = os.path.join(outdir, "web")
    os.makedirs(webdir, exist_ok=True)

    # --- parcels → WGS84 GeoJSON (absent in raster-only / national runs) ---
    parcels_path = os.path.join(outdir, "parcels_scored.geojson")
    parcels = None
    web_parcels = os.path.join(webdir, "parcels.geojson")
    if os.path.exists(parcels_path):
        parcels = gpd.read_file(parcels_path).to_crs(WEB_CRS)
        parcels.to_file(web_parcels, driver="GeoJSON", COORDINATE_PRECISION=5)
    elif os.path.exists(web_parcels):
        os.remove(web_parcels)   # stale parcels from a previous run

    # --- prospectivity rasters → colorized PNG overlays (combined + per metal) ---
    from ..ingest import live
    land = live.natural_earth_land()   # to mask sea cells out of the heatmap
    arr, bounds = _warp_raster_to_wgs84(os.path.join(outdir, "prospectivity.tif"), land)
    _colorize(arr).save(os.path.join(webdir, "prospectivity.png"))
    import glob as _glob
    for stale in _glob.glob(os.path.join(webdir, "prospectivity_*.png")):
        os.remove(stale)   # drop a prior region's per-metal overlays
    for tif in _glob.glob(os.path.join(outdir, "prospectivity_*.tif")):
        c = os.path.basename(tif)[len("prospectivity_"):-len(".tif")]
        arr_c, _ = _warp_raster_to_wgs84(tif, land)
        _colorize(arr_c).save(os.path.join(webdir, f"prospectivity_{c}.png"))

    # --- occurrences (live pipeline only): real BDMIN mineral showings ---
    occ_meta = {"commodities": {}, "top_showings": [], "n_occurrences": 0}
    occ_path = os.path.join(outdir, "occurrences.geojson")
    if os.path.exists(occ_path):
        occ = gpd.read_file(occ_path).to_crs(WEB_CRS)
        occ.to_file(os.path.join(webdir, "occurrences.geojson"), driver="GeoJSON", COORDINATE_PRECISION=5)
        occ_meta["n_occurrences"] = int(len(occ))
        occ_meta["commodities"] = {
            str(k): int(v) for k, v in occ["commodity"].value_counts().items()
        }
        targets = occ   # occurrences.geojson is already the region's commodity set
        show_cols = [c for c in ["name", "sustancia", "municipio", "commodity"]
                     if c in targets.columns]
        occ_meta["top_showings"] = json.loads(
            targets[show_cols].head(30).to_json(orient="records"))

    # --- mine workings (BDMIN Explotaciones): existing-activity overlay ---
    work_web = os.path.join(webdir, "mining_workings.geojson")
    work_path = os.path.join(outdir, "mining_workings.geojson")
    if os.path.exists(work_path):
        works = gpd.read_file(work_path).to_crs(WEB_CRS)
        works.to_file(work_web, driver="GeoJSON", COORDINATE_PRECISION=5)
        occ_meta["n_workings"] = int(len(works))
        occ_meta["n_workings_active"] = int(works["active"].sum()) if "active" in works else 0
    else:
        occ_meta["n_workings"] = 0
        if os.path.exists(work_web):
            os.remove(work_web)

    # --- legal mining concessions (Catastro Minero): "already claimed" overlay ---
    conc_web = os.path.join(webdir, "mining_concessions.geojson")
    conc_path = os.path.join(outdir, "mining_concessions.geojson")
    if os.path.exists(conc_path):
        conc = gpd.read_file(conc_path).to_crs(WEB_CRS)
        conc.to_file(conc_web, driver="GeoJSON", COORDINATE_PRECISION=5)
        occ_meta["n_concessions"] = int(len(conc))
        occ_meta["n_concessions_blocking"] = int(conc["blocks"].sum()) if "blocks" in conc else 0
    else:
        occ_meta["n_concessions"] = 0
        if os.path.exists(conc_web):
            os.remove(conc_web)

    # --- hotspots + per-hotspot drill files (national → hotspot → parcels) ---
    import glob
    for stale in glob.glob(os.path.join(webdir, "hotspot_parcels_*.geojson")) + \
                 glob.glob(os.path.join(webdir, "hotspot_concessions_*.geojson")):
        os.remove(stale)
    occ_meta["hotspots"] = []
    hs_web = os.path.join(webdir, "hotspots.geojson")
    hs_path = os.path.join(outdir, "hotspots.geojson")
    if os.path.exists(hs_path):
        hs = gpd.read_file(hs_path).to_crs(WEB_CRS)
        hs.to_file(hs_web, driver="GeoJSON", COORDINATE_PRECISION=5)
        keep = [c for c in ["rank", "provincia", "area_km2", "n_occ", "mean_post",
                            "top_commodity", "municipios", "n_parcels", "n_claimed",
                            "n_conc"] if c in hs.columns]
        occ_meta["hotspots"] = json.loads(hs[keep].to_json(orient="records"))
        # copy each hotspot's drill files (parcels + concessions), reprojected
        for src in glob.glob(os.path.join(outdir, "hotspot_parcels_*.geojson")) + \
                   glob.glob(os.path.join(outdir, "hotspot_concessions_*.geojson")):
            gpd.read_file(src).to_crs(WEB_CRS).to_file(
                os.path.join(webdir, os.path.basename(src)), driver="GeoJSON", COORDINATE_PRECISION=5)
    elif os.path.exists(hs_web):
        os.remove(hs_web)

    # --- per-commodity model metadata (from commodities.json) ---
    commodity_models = []
    occ_meta["region"] = None
    cpath = os.path.join(outdir, "commodities.json")
    if os.path.exists(cpath):
        with open(cpath) as f:
            cj = json.load(f)
        occ_meta["region"] = cj.get("region")
        occ_meta["region_label"] = cj.get("region_label")
        for cm in cj.get("commodities", []):
            col = f"score_{cm['key']}"
            entry = dict(cm)
            if parcels is not None and col in parcels.columns:
                entry["score_min"] = float(parcels[col].min())
                entry["score_max"] = float(parcels[col].max())
            commodity_models.append(entry)

    # --- meta: bounds, score domain, ranked top parcels ---
    raster_center = [(bounds[0][0] + bounds[1][0]) / 2, (bounds[0][1] + bounds[1][1]) / 2]
    meta = {
        "raster_bounds": bounds,
        "center": raster_center,
        "commodity_models": commodity_models,
        "n_parcels": 0,
        "n_listed": 0,
        "has_price": False,
        "top": [],
        **occ_meta,
    }
    if parcels is not None:
        ranked = parcels.sort_values("score", ascending=False)
        top_cols = [c for c in [
            "parcel_id", "municipio", "score", "prospectivity", "cheapness",
            "friction", "eur_ha_effective", "protected_frac", "listed", "area_ha",
            "listing_url",
        ] if c in parcels.columns]
        meta.update({
            "score_min": float(parcels["score"].min()),
            "score_max": float(parcels["score"].max()),
            "center": [parcels.geometry.union_all().centroid.y,
                       parcels.geometry.union_all().centroid.x],
            "n_parcels": int(len(parcels)),
            "n_listed": int(parcels["listed"].sum()) if "listed" in parcels else 0,
            "has_price": bool(parcels["eur_ha_effective"].notna().any())
                if "eur_ha_effective" in parcels.columns else False,
            "top": json.loads(ranked[top_cols].head(25).to_json(orient="records")),
        })
    with open(os.path.join(webdir, "meta.json"), "w") as f:
        json.dump(meta, f)

    # --- keep each region's assets so the UI can switch between them ---
    region = occ_meta.get("region")
    if region:
        import shutil
        _build_parcel_index(webdir, region, outdir)   # flat buy-list index for budget search
        rdir = os.path.join(webdir, "regions", region)
        os.makedirs(rdir, exist_ok=True)
        # drop stale hotspot drills from a prior run (rank numbering shifts as the
        # model changes), else the UI could fetch parcels for a rank that no
        # longer drills there
        for stale in glob.glob(os.path.join(rdir, "hotspot_parcels_*.geojson")) + \
                     glob.glob(os.path.join(rdir, "hotspot_concessions_*.geojson")) + \
                     glob.glob(os.path.join(rdir, "prospectivity_*.png")):
            os.remove(stale)
        for fn in os.listdir(webdir):
            if fn.endswith((".json", ".geojson", ".png")) and fn != "regions.json":
                shutil.copy(os.path.join(webdir, fn), os.path.join(rdir, fn))
        # registry of available regions (key + label + a couple of stats)
        reg_path = os.path.join(webdir, "regions.json")
        registry = {}
        if os.path.exists(reg_path):
            with open(reg_path) as f:
                registry = {r["key"]: r for r in json.load(f)}
        registry[region] = {"key": region, "label": occ_meta.get("region_label") or region,
                            "n_occurrences": meta.get("n_occurrences", 0),
                            "n_hotspots": len(meta.get("hotspots", []))}
        with open(reg_path, "w") as f:
            json.dump(sorted(registry.values(), key=lambda r: r["key"]), f)

    return webdir


if __name__ == "__main__":
    path = export()
    print(f"Web assets written to {path}/")
