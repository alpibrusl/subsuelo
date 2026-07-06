"""Region registry — each mineral-screening area as a plug-in.

A `Region` declares its grid (CRS, cell size, lon/lat window), its data-source
callables (granite / faults / occurrences, each `bbox_4326 -> GeoDataFrame in
region CRS`), model thresholds, and — where a cadastre exists — the providers
that let hotspots drill down to parcels. The shared engine in `pipeline.py`
runs any Region identically, so adding a new country is a single entry here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from . import config
from .ingest import live

CONTACT = "near_granite"   # evidence-layer names (kept stable for the UI/legend)


@dataclass(frozen=True)
class Region:
    key: str                       # short id, also written to meta.region
    label: str                     # UI subtitle
    menu: str                      # short name for the Area dropdown
    crs: str
    cell_size: float               # metres
    lonlat: tuple                  # (lon_min, lat_min, lon_max, lat_max)

    granite: Callable              # bbox_4326 -> granite/granitoid polygons
    faults: Callable               # bbox_4326 -> fault lines
    occurrences: Callable          # bbox_4326 -> Sn/W/Li-classified occurrence points

    near_granite_m: float          # WofE binarization thresholds
    near_fault_m: float
    dens_sigma: float = 4.0        # hotspot occurrence-density smoothing (cells)
    target_pctl: float = 88.0      # hotspot threshold percentile
    top_k: int = 12                # hotspots to keep
    min_cells: int = 6             # drop hotspot specks

    # which commodities this region models — defaults to the granite-related set;
    # the VMS region overrides with base metals (different mineral system).
    commodities: tuple = config.COMMODITIES
    hotspot_commodities: tuple = config.HOTSPOT_COMMODITIES
    proxy_commodities: frozenset = config.PROXY_COMMODITIES

    # drill-down to parcels (optional; only where an open cadastre exists)
    drill: bool = False
    drill_hotspots: int = 8
    drill_munis: int = 3
    parcel_min_area_ha: float = 2.0
    # Spain: municipio-based (resolve province + municipios via Catastro ATOM)
    parcels_provider: Optional[Callable] = None      # (provincia, muni_names) -> parcels
    concessions_provider: Optional[Callable] = None  # (provincia, bbox_4326) -> concessions
    # Europe: bbox-based per-country cadastre around each hotspot
    parcels_bbox_provider: Optional[Callable] = None  # (country, bbox_4326, min_area_ha) -> parcels
    drill_radius_km: float = 5.0                       # bbox half-size around a hotspot


REGIONS: dict[str, Region] = {
    # Peninsular Spain — IGME 1:1M geology + national BDMIN, with Catastro drill.
    "spain": Region(
        key="spain", menu="Peninsular Spain",
        label="Sn·W·Li prospectivity — peninsular Spain (IGME 1:1M)",
        crs="EPSG:3035", cell_size=1000.0, lonlat=(-9.5, 35.9, 3.5, 43.9),
        granite=live.igme_national_granite,
        faults=live.igme_national_faults,
        occurrences=live.igme_occurrences,
        near_granite_m=5_000.0, near_fault_m=10_000.0,
        dens_sigma=4.0, target_pctl=88.0, top_k=12,
        drill=True, drill_hotspots=8, drill_munis=3,
        parcels_provider=live.catastro_parcels_for,
        concessions_provider=live.concessions_for,
    ),
    # Variscan W/Central Europe — EGDI pan-European geology + Minerals4EU/FRAME.
    "europe": Region(
        key="europe", menu="Variscan Europe",
        label="Sn·W·Li prospectivity — Variscan Europe (EGDI 1:1M)",
        crs="EPSG:3035", cell_size=5000.0, lonlat=(-10.0, 36.0, 16.0, 55.0),
        granite=live.egdi_granite,
        faults=live.egdi_faults,
        occurrences=live.egdi_occurrences,
        near_granite_m=15_000.0, near_fault_m=20_000.0,
        # ~2.9k Sn/W/Li showings across Europe → a high percentile keeps hotspots
        # tight (a lower one merges the whole Variscan belt into one blob).
        dens_sigma=3.0, target_pctl=96.0, top_k=15, min_cells=3,
        # drill hotspots to parcels where an open national cadastre exists
        # (France, Czechia, Germany/Saxony); others (Portugal, Spain-in-EU-view)
        # stay raster-only. Border-aware: a hotspot straddling DE/CZ (Erzgebirge)
        # pulls both countries' parcels.
        drill=True, drill_hotspots=15, parcel_min_area_ha=1.0, drill_radius_km=5.0,
        parcels_bbox_provider=live.parcels_for_bbox,
    ),
    # Iberian Pyrite Belt — base metals (Cu/Zn/Pb/Ag) as VMS, hosted by felsic
    # volcanics (NOT granite). Same engine, different evidence + commodity set.
    "iberia": Region(
        key="iberia", menu="Iberian Pyrite Belt",
        label="Cu·Zn·Pb·Ag prospectivity — Iberian Pyrite Belt (VMS, EGDI)",
        crs="EPSG:3035", cell_size=2000.0, lonlat=(-9.5, 36.8, -5.0, 39.0),
        granite=live.egdi_felsic_volcanics,   # 'granite' slot = the VMS host rock
        faults=live.egdi_faults,
        occurrences=live.egdi_basemetals,
        near_granite_m=8_000.0, near_fault_m=15_000.0,
        dens_sigma=3.0, target_pctl=92.0, top_k=12, min_cells=3,
        commodities=config.VMS_COMMODITIES,
        hotspot_commodities=config.VMS_COMMODITIES,
        proxy_commodities=frozenset(),
        # Catastro CP WFS is slow (~1 min/box), so keep the drill boxes modest;
        # IPB base-metal land is rural so a 2 ha floor trims dense urban plots
        drill=True, drill_hotspots=8, parcel_min_area_ha=2.0, drill_radius_km=4.0,
        parcels_bbox_provider=live.parcels_for_bbox,
    ),
}


def get(key: str) -> Region:
    if key not in REGIONS:
        raise KeyError(f"unknown region '{key}'; known: {sorted(REGIONS)}")
    return REGIONS[key]
