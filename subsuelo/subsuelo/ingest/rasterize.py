"""Turn live vector geology into the numpy grids the WofE model consumes.

Grid convention matches ingest/synthetic.grid_shape(): row 0 = north,
CELL_SIZE metres, aligned to config.BBOX in config.CRS.
"""

from __future__ import annotations

import numpy as np
import geopandas as gpd
from rasterio.features import rasterize
from rasterio.transform import from_origin
from scipy.ndimage import distance_transform_edt

# Reference config dynamically (not `from config import BBOX`) so a runner can
# override the region — BBOX/CELL_SIZE/CRS — at startup for e.g. a national grid.
from .. import config


def _shape():
    nx = int((config.BBOX[2] - config.BBOX[0]) / config.CELL_SIZE)
    ny = int((config.BBOX[3] - config.BBOX[1]) / config.CELL_SIZE)
    return ny, nx


def _transform():
    return from_origin(config.BBOX[0], config.BBOX[3], config.CELL_SIZE, config.CELL_SIZE)


def burn_mask(geoms: gpd.GeoSeries) -> np.ndarray:
    """Boolean grid: True where any geometry touches the cell."""
    ny, nx = _shape()
    if geoms is None or len(geoms) == 0:
        return np.zeros((ny, nx), dtype=bool)
    shapes = [(g, 1) for g in geoms.geometry if g is not None and not g.is_empty]
    if not shapes:
        return np.zeros((ny, nx), dtype=bool)
    arr = rasterize(shapes, out_shape=(ny, nx), transform=_transform(),
                    fill=0, all_touched=True, dtype="uint8")
    return arr.astype(bool)


def distance_grid(geoms: gpd.GeoSeries) -> np.ndarray:
    """Euclidean distance (metres) from each cell centre to the nearest
    geometry. Empty input → all-inf grid (binarizes to 'far' everywhere)."""
    ny, nx = _shape()
    mask = burn_mask(geoms)
    if not mask.any():
        return np.full((ny, nx), np.inf, dtype="float64")
    # EDT of the *background*: distance to nearest True cell, in cell units.
    dist_cells = distance_transform_edt(~mask)
    return dist_cells * config.CELL_SIZE


def deposits_grid(points: gpd.GeoDataFrame) -> np.ndarray:
    """Boolean training grid: True in cells containing an occurrence point."""
    return burn_mask(points.geometry) if len(points) else np.zeros(_shape(), bool)
