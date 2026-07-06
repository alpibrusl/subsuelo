"""Per-parcel composite scoring.

score = w_p * prospectivity + w_$ * cheapness + w_f * (1 - friction)

- prospectivity: mean WofE posterior over the parcel (zonal stats on the grid)
- cheapness: 1 - percentile rank of €/ha (asking price if listed, else
  cadastral value) within the region — cheaper land scores higher
- friction: fraction of parcel overlapping protected areas (extend with
  slope, mining-concession overlap, distance-to-grid as layers arrive)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import geopandas as gpd

# reference config dynamically so a national/hotspot runner can override the grid
from .. import config
from ..config import SCORE_WEIGHTS


def cell_membership(parcels: gpd.GeoDataFrame, grid_shape: tuple) -> list:
    """For each parcel, the (rows, cols) of grid cells whose centre falls inside
    it — computed once so any number of rasters can be sampled cheaply.

    Cell-center point-in-polygon sampling; adequate when parcels span many
    cells. Swap for rasterstats/exactextract in production."""
    ny, nx = grid_shape
    bbox, cell = config.BBOX, config.CELL_SIZE
    members = []
    for geom in parcels.geometry:
        minx, miny, maxx, maxy = geom.bounds
        c0 = max(int((minx - bbox[0]) / cell), 0)
        c1 = min(int((maxx - bbox[0]) / cell) + 1, nx)
        r0 = max(int((bbox[3] - maxy) / cell), 0)
        r1 = min(int((bbox[3] - miny) / cell) + 1, ny)
        rows, cols = [], []
        for r in range(r0, r1):
            cy = bbox[3] - (r + 0.5) * cell
            for c in range(c0, c1):
                cx = bbox[0] + (c + 0.5) * cell
                if geom.contains(gpd.points_from_xy([cx], [cy])[0]):
                    rows.append(r); cols.append(c)
        members.append((np.asarray(rows, int), np.asarray(cols, int)))
    return members


def zonal_mean(grid: np.ndarray, parcels: gpd.GeoDataFrame,
               members: list | None = None) -> np.ndarray:
    """Mean grid value per parcel. Pass precomputed `members` (from
    cell_membership) to sample many rasters without repeating the join."""
    if members is None:
        members = cell_membership(parcels, grid.shape)
    out = np.full(len(parcels), np.nan)
    for k, (rows, cols) in enumerate(members):
        if len(rows):
            out[k] = float(np.mean(grid[rows, cols]))
    return out


def _overlap_frac(parcels: gpd.GeoDataFrame, polys: gpd.GeoDataFrame) -> "pd.Series":
    """Fraction of each parcel covered by the union of `polys` (0 if empty)."""
    if polys is None or len(polys) == 0:
        return pd.Series(0.0, index=parcels.index)
    u = polys.union_all()
    return parcels.geometry.apply(
        lambda g: g.intersection(u).area / g.area if g.area > 0 else 0.0)


def score_parcels(
    parcels: gpd.GeoDataFrame,
    posterior: np.ndarray,
    protected: gpd.GeoDataFrame,
    extra_posteriors: dict[str, np.ndarray] | None = None,
    claimed: gpd.GeoDataFrame | None = None,
) -> gpd.GeoDataFrame:
    """Composite parcel score. `posterior` is the primary (combined) raster,
    written to `prospectivity`/`score`. `extra_posteriors` maps a commodity tag
    (e.g. 'Sn') to its own posterior raster; each adds `prospectivity_<tag>` and
    `score_<tag>` columns so the UI can switch heatmap + ranking per mineral.
    `claimed` = existing mining-rights polygons (Catastro Minero): ground already
    held raises friction ("can't acquire"). Cell membership is computed once and
    reused across all rasters."""
    p = parcels.copy()
    members = cell_membership(p, posterior.shape)

    # 2. cheapness: effective €/ha = asking if listed else cadastral
    eur_ha = p["asking_eur_ha"].where(p["listed"], p["cadastral_eur_ha"]).astype(float)
    p["eur_ha_effective"] = eur_ha
    p["cheapness"] = 1.0 - eur_ha.rank(pct=True)

    # 3. friction: protected-area overlap + existing mining-rights overlap
    p["protected_frac"] = _overlap_frac(p, protected)
    p["claimed_frac"] = _overlap_frac(p, claimed)
    p["friction"] = (p["protected_frac"] + p["claimed_frac"]).clip(0.0, 1.0)

    w = SCORE_WEIGHTS

    def composite(prospectivity_rank):
        return (
            w["prospectivity"] * prospectivity_rank.fillna(0)
            + w["price"] * p["cheapness"].fillna(0)
            + w["friction"] * (1.0 - p["friction"])
        ).round(4)

    # 1. prospectivity — raw posterior mean, then percentile-rank normalized
    # (WofE posteriors are tiny with sparse priors; ranking makes the
    # component commensurate with cheapness/friction in the composite)
    for tag, grid in {None: posterior, **(extra_posteriors or {})}.items():
        raw = zonal_mean(grid, p, members)
        rank = pd.Series(raw, index=p.index).rank(pct=True)
        sfx = "" if tag is None else f"_{tag}"
        p[f"prospectivity_raw{sfx}"] = raw
        p[f"prospectivity{sfx}"] = rank
        p[f"score{sfx}"] = composite(rank)

    return p.sort_values("score", ascending=False)
