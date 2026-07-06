"""Synthetic demo data for the pipeline.

Generates a geologically-plausible toy version of the Extremadura Sn-W-Li
setting: granite intrusions in slate country rock, occurrences clustered on
intrusion contacts (greisen/pegmatite style), a Sn-in-soil geochemical field,
NE-SW faults, cadastral-like parcels with prices, and one protected area.

Everything here is replaced 1:1 by the live ingestors (catastro.py, igme.py)
when running with network access — grid shapes and GeoDataFrame schemas match.
"""

from __future__ import annotations

import numpy as np
import geopandas as gpd
from shapely.geometry import Point, Polygon, LineString

from ..config import BBOX, CELL_SIZE, CRS


def grid_shape() -> tuple[int, int]:
    nx = int((BBOX[2] - BBOX[0]) / CELL_SIZE)
    ny = int((BBOX[3] - BBOX[1]) / CELL_SIZE)
    return ny, nx


def cell_centers() -> tuple[np.ndarray, np.ndarray]:
    ny, nx = grid_shape()
    xs = BBOX[0] + (np.arange(nx) + 0.5) * CELL_SIZE
    ys = BBOX[3] - (np.arange(ny) + 0.5) * CELL_SIZE  # row 0 = north
    return np.meshgrid(xs, ys)


def make_geology(rng: np.random.Generator):
    """Returns (dist_to_contact grid [m], granite mask, intrusion centers)."""
    xx, yy = cell_centers()
    centers = np.column_stack(
        [
            rng.uniform(BBOX[0] + 15_000, BBOX[2] - 15_000, 4),
            rng.uniform(BBOX[1] + 15_000, BBOX[3] - 15_000, 4),
        ]
    )
    radii = rng.uniform(5_000, 11_000, 4)
    dist_contact = np.full(xx.shape, np.inf)
    granite = np.zeros(xx.shape, dtype=bool)
    for (cx, cy), r in zip(centers, radii):
        d = np.hypot(xx - cx, yy - cy)
        granite |= d <= r
        dist_contact = np.minimum(dist_contact, np.abs(d - r))
    return dist_contact, granite, centers, radii


def make_faults(rng: np.random.Generator, n: int = 6):
    """NE-SW trending fault traces; returns distance-to-fault grid and geoms."""
    xx, yy = cell_centers()
    dist = np.full(xx.shape, np.inf)
    lines = []
    for _ in range(n):
        x0 = rng.uniform(BBOX[0], BBOX[2])
        y0 = rng.uniform(BBOX[1], BBOX[3])
        length = rng.uniform(30_000, 80_000)
        ang = np.deg2rad(rng.normal(45, 8))  # NE-SW
        dx, dy = np.cos(ang) * length / 2, np.sin(ang) * length / 2
        lines.append(LineString([(x0 - dx, y0 - dy), (x0 + dx, y0 + dy)]))
        # point-to-segment distance on the grid
        px, py = x0 - dx, y0 - dy
        qx, qy = x0 + dx, y0 + dy
        vx, vy = qx - px, qy - py
        t = np.clip(((xx - px) * vx + (yy - py) * vy) / (vx**2 + vy**2), 0, 1)
        dist = np.minimum(dist, np.hypot(xx - (px + t * vx), yy - (py + t * vy)))
    return dist, gpd.GeoDataFrame(geometry=lines, crs=CRS)


def make_occurrences(rng, dist_contact, granite, n: int = 45) -> gpd.GeoDataFrame:
    """Training occurrences: preferentially on/near granite contacts."""
    ny, nx = dist_contact.shape
    w = np.exp(-dist_contact / 1_500.0)
    w[granite] *= 0.35  # contacts and aureole, not intrusion cores
    w = (w / w.sum()).ravel()
    idx = rng.choice(w.size, size=n, replace=False, p=w)
    rows, cols = np.unravel_index(idx, (ny, nx))
    xs = BBOX[0] + (cols + 0.5) * CELL_SIZE + rng.normal(0, 100, n)
    ys = BBOX[3] - (rows + 0.5) * CELL_SIZE + rng.normal(0, 100, n)
    return gpd.GeoDataFrame(
        {"commodity": rng.choice(["Sn", "W", "Li"], n, p=[0.4, 0.35, 0.25])},
        geometry=[Point(x, y) for x, y in zip(xs, ys)],
        crs=CRS,
    )


def make_geochem(rng, dist_contact, occurrences: gpd.GeoDataFrame) -> np.ndarray:
    """Sn-in-soil style anomaly field: background + halos around occurrences."""
    xx, yy = cell_centers()
    field = rng.lognormal(mean=1.0, sigma=0.5, size=xx.shape)  # background ppm
    for pt in occurrences.geometry:
        d = np.hypot(xx - pt.x, yy - pt.y)
        field += 40.0 * np.exp(-((d / 2_500.0) ** 2))
    field += 8.0 * np.exp(-dist_contact / 3_000.0)  # broad contact enrichment
    return field


def make_parcels(rng, n_side: int = 24) -> gpd.GeoDataFrame:
    """Jittered-grid rustic parcels with cadastral value and some listings."""
    dx = (BBOX[2] - BBOX[0]) / n_side
    dy = (BBOX[3] - BBOX[1]) / n_side
    geoms, rows = [], []
    pid = 0
    for i in range(n_side):
        for j in range(n_side):
            x0 = BBOX[0] + i * dx + rng.uniform(-0.1, 0.1) * dx
            y0 = BBOX[1] + j * dy + rng.uniform(-0.1, 0.1) * dy
            poly = Polygon(
                [(x0, y0), (x0 + dx * 0.92, y0), (x0 + dx * 0.92, y0 + dy * 0.92), (x0, y0 + dy * 0.92)]
            ).intersection(Polygon.from_bounds(*BBOX))
            if poly.is_empty:
                continue
            area_ha = poly.area / 10_000.0
            cadastral_eur_ha = float(rng.lognormal(np.log(1_800), 0.45))
            listed = rng.random() < 0.18
            asking_eur_ha = float(cadastral_eur_ha * rng.uniform(1.6, 3.2)) if listed else np.nan
            rows.append(
                dict(
                    parcel_id=f"DEMO-{pid:04d}",
                    area_ha=round(area_ha, 2),
                    cadastral_eur_ha=round(cadastral_eur_ha, 0),
                    listed=listed,
                    asking_eur_ha=round(asking_eur_ha, 0) if listed else np.nan,
                    listing_url=f"https://example.invalid/listing/{pid}" if listed else None,
                )
            )
            geoms.append(poly)
            pid += 1
    return gpd.GeoDataFrame(rows, geometry=geoms, crs=CRS)


def make_protected(rng) -> gpd.GeoDataFrame:
    """One Natura-2000-like polygon covering part of the window."""
    cx = rng.uniform(BBOX[0] + 25_000, BBOX[2] - 25_000)
    cy = rng.uniform(BBOX[1] + 25_000, BBOX[3] - 25_000)
    ang = np.linspace(0, 2 * np.pi, 24, endpoint=False)
    r = rng.uniform(12_000, 20_000) * (1 + 0.25 * np.sin(3 * ang + rng.uniform(0, 6)))
    poly = Polygon(np.column_stack([cx + r * np.cos(ang), cy + r * np.sin(ang)]))
    return gpd.GeoDataFrame({"site": ["ES-DEMO-ZEPA"]}, geometry=[poly], crs=CRS)
