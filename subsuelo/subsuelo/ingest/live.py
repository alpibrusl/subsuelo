"""Live ingestors for Spanish public geodata. NETWORK REQUIRED.

Validated 2026-07 against the live services:
  - IGME BDMIN (mineral occurrences) + MAGNA/GEODE geology via ArcGIS REST
  - Catastro INSPIRE cadastral parcels via the ATOM feed (per-municipio GML)

All functions return GeoDataFrames in config.CRS with schemas matching
ingest/synthetic.py, so `run_live.py` can drop them straight into the model.

idealista prices need approved OAuth credentials (not generally available);
`idealista_listings` is kept for when a token exists, but the live pipeline
runs without it and marks cheapness as unavailable.
"""

from __future__ import annotations

import io
import json
import os
import re
import unicodedata
import zipfile

import numpy as np
import geopandas as gpd
import pandas as pd
import requests

# config.CRS is referenced dynamically (as config.CRS, not a bare import) so a
# national runner can override the region CRS at startup and these ingestors
# follow it.
from .. import config
from ..config import ENDPOINTS, TARGET_COMMODITIES, GRANITE_LITHOLOGIES
from . import net

# every live fetch goes through net.http_get (disk-cached + provenance-logged),
# so a build is reproducible from its cache snapshot — see net.py for the modes.
_UA = net._UA
_TIMEOUT = net._TIMEOUT


# --------------------------------------------------------------------------- #
# IGME — ArcGIS REST (MapServer/<layer>/query)                                 #
# --------------------------------------------------------------------------- #

def _arcgis_query(service_path: str, layer: int, bbox_4326: tuple,
                  out_fields: str = "*", page: int = 1000,
                  where: str = "1=1") -> gpd.GeoDataFrame:
    """Paged ArcGIS REST GetFeatures as GeoJSON, clipped to a lon/lat bbox and
    an optional attribute `where` filter (server-side — cuts national volumes).

    Returns a GeoDataFrame in EPSG:4326 (empty if nothing matches). Pages with
    resultOffset until the server stops returning a full page.
    """
    url = f"{ENDPOINTS.igme_services_root}/{service_path}/MapServer/{layer}/query"
    frames, offset = [], 0
    while True:
        params = {
            "where": where,
            "geometry": ",".join(map(str, bbox_4326)),
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326", "outSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": out_fields,
            "returnGeometry": "true",
            "resultOffset": offset,
            "resultRecordCount": page,
            "f": "geojson",
        }
        gj = json.loads(net.http_get(url, params=params, tag=f"igme:{service_path}:{layer}"))
        feats = gj.get("features", [])
        if feats:
            frames.append(gpd.GeoDataFrame.from_features(feats, crs="EPSG:4326"))
        if len(feats) < page:
            break
        offset += page
    if not frames:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    return pd.concat(frames, ignore_index=True)


def igme_occurrences(bbox_4326: tuple) -> gpd.GeoDataFrame:
    """BDMIN mineral occurrences in the window, all substances.

    Schema: geometry (points, config.CRS) + columns
      commodity   normalized tag ('Sn'/'W'/'Li'/'other')
      sustancia   raw IGME 'Sustancia' string
      name        mine/showing name
      municipio, asociacion (mineral association), morfologia
    """
    gdf = _arcgis_query(ENDPOINTS.igme_bdmin_indicios, layer=1, bbox_4326=bbox_4326)
    if gdf.empty:
        return gpd.GeoDataFrame(
            columns=["commodity", "sustancia", "name", "municipio", "provincia",
                     "asociacion", "morfologia", "geometry"],
            geometry="geometry", crs=config.CRS)

    def classify(s) -> str:
        s = "" if (s is None or (isinstance(s, float) and np.isnan(s))) else str(s).lower()
        for tag, kws in TARGET_COMMODITIES.items():
            if any(k in s for k in kws):
                return tag
        return "other"

    out = gpd.GeoDataFrame(
        {
            "commodity": gdf["Sustancia"].map(classify),
            "sustancia": gdf["Sustancia"].str.strip(),
            "name": gdf.get("Nombre_mina", pd.Series([""] * len(gdf))).str.strip(),
            "municipio": gdf.get("Municipio", pd.Series([""] * len(gdf))).str.strip(),
            "provincia": gdf.get("Provincia", pd.Series([""] * len(gdf))).str.strip(),
            "asociacion": gdf.get("Asociacion_mineral", pd.Series([""] * len(gdf))),
            "morfologia": gdf.get("Morfologia", pd.Series([""] * len(gdf))),
        },
        geometry=gdf.geometry, crs="EPSG:4326",
    ).to_crs(config.CRS)
    return out


def igme_geology_lines(bbox_4326: tuple) -> gpd.GeoDataFrame:
    """Contact + fault line traces (TIPO tells them apart), in config.CRS."""
    gdf = _arcgis_query(ENDPOINTS.igme_geology_caceres,
                        layer=ENDPOINTS.igme_geology_lines_layer, bbox_4326=bbox_4326)
    if gdf.empty:
        return gpd.GeoDataFrame(columns=["TIPO", "geometry"], geometry="geometry", crs=config.CRS)
    return gdf.to_crs(config.CRS)


def igme_granite(bbox_4326: tuple) -> gpd.GeoDataFrame:
    """Lithology polygons whose description marks them as granite/pegmatite
    host rock (see config.GRANITE_LITHOLOGIES), in config.CRS."""
    gdf = _arcgis_query(ENDPOINTS.igme_geology_caceres,
                        layer=ENDPOINTS.igme_geology_litho_layer, bbox_4326=bbox_4326)
    if gdf.empty:
        return gpd.GeoDataFrame(columns=["DLO", "geometry"], geometry="geometry", crs=config.CRS)
    dlo = gdf["DLO"].fillna("").str.lower()
    mask = dlo.apply(lambda s: any(k in s for k in GRANITE_LITHOLOGIES))
    return gdf[mask].to_crs(config.CRS)


# --------------------------------------------------------------------------- #
# IGME national 1:1M geology (run_national.py)                                  #
# --------------------------------------------------------------------------- #

def igme_national_granite(bbox_4326: tuple) -> gpd.GeoDataFrame:
    """Granitoid/pegmatite lithology polygons over `bbox_4326` from the national
    1:1M map, filtered server-side (DLO LIKE '%GRANIT%' catches Granito(s),
    Granitoides, Granodiorita, Leucogranito…). Returns config.CRS."""
    gdf = _arcgis_query(ENDPOINTS.igme_geology_national,
                        layer=ENDPOINTS.igme_geology_national_litho_layer,
                        bbox_4326=bbox_4326, where="UPPER(DLO) LIKE '%GRANIT%'")
    if gdf.empty:
        return gpd.GeoDataFrame(columns=["DLO", "geometry"], geometry="geometry", crs=config.CRS)
    # keep only genuine granite host rock per the keyword list (drops e.g.
    # "areniscas con cemento granítico"-style false positives if any)
    dlo = gdf["DLO"].fillna("").str.lower()
    mask = dlo.apply(lambda s: any(k in s for k in GRANITE_LITHOLOGIES))
    return gdf[mask].to_crs(config.CRS)


def igme_national_faults(bbox_4326: tuple) -> gpd.GeoDataFrame:
    """Fault + thrust traces over `bbox_4326` from the national 1:1M map
    (TIPO LIKE 'Falla%' OR 'Cabalgamiento%'). Returns config.CRS."""
    gdf = _arcgis_query(ENDPOINTS.igme_geology_national,
                        layer=ENDPOINTS.igme_geology_national_lines_layer,
                        bbox_4326=bbox_4326,
                        where="TIPO LIKE 'Falla%' OR TIPO LIKE 'Cabalgamiento%'")
    if gdf.empty:
        return gpd.GeoDataFrame(columns=["TIPO", "geometry"], geometry="geometry", crs=config.CRS)
    return gdf.to_crs(config.CRS)


# --------------------------------------------------------------------------- #
# EGDI — pan-European geology + Minerals4EU/FRAME occurrences (run_europe.py)   #
# --------------------------------------------------------------------------- #

# Above this bbox extent (degrees), a single geologicunitview/faults GetFeature
# request comes back geographically thinned server-side, proportional to query
# area — confirmed empirically by probing the SAME 10°×10° box (containing the
# real, INSPIRE-mapped Cornwall granite) at shrinking tile sizes: 10° → 532
# polys/0 in Cornwall, 5° → 746/0, 3° → 964/24, 2° → 969/25. It plateaus at 3°,
# so that's the tile size used — smaller buys negligible extra completeness for
# a lot more requests. Pagination alone doesn't catch this (each page reports
# "no more results" well short of the true total), so large bboxes are tiled
# and the per-tile results concatenated; each tile is cached independently.
_EGDI_TILE_DEG = 3.0


def _egdi_wfs_tile(typename: str, bbox_4326: tuple, page: int = 5000) -> gpd.GeoDataFrame:
    """Paged EGDI WFS 1.1.0 GetFeature for a single (small-enough) bbox tile."""
    frames, start = [], 0
    while True:
        # WFS 1.1.0 + lon,lat bbox (2.0.0 + urn:EPSG::4326 forces lat,lon and
        # silently returns nothing); MapServer honours startindex for paging.
        params = {
            "service": "WFS", "version": "1.1.0", "request": "GetFeature",
            "typeName": typename, "srsName": "EPSG:4326",
            "bbox": ",".join(map(str, bbox_4326)),
            "maxFeatures": str(page), "startindex": str(start),
        }
        try:
            gdf = gpd.read_file(io.BytesIO(net.http_get(
                ENDPOINTS.egdi_wfs, params=params, timeout=180, tag=f"egdi:{typename}")))
        except Exception:
            break
        if len(gdf):
            frames.append(gdf)
        if len(gdf) < page:
            break
        start += page
    if not frames:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    out = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs="EPSG:4326")
    # WFS 1.1.0 + EPSG:4326 returns lat,lon axis order — flip to lon,lat
    from shapely.ops import transform as _shp_transform
    out["geometry"] = out.geometry.map(
        lambda g: _shp_transform(lambda x, y: (y, x), g) if g is not None else g)
    return out.set_crs("EPSG:4326", allow_override=True)


def _tile_bbox(bbox_4326: tuple, tile_deg: float) -> list:
    minx, miny, maxx, maxy = bbox_4326
    import numpy as _np
    xs = _np.arange(minx, maxx, tile_deg).tolist() or [minx]
    ys = _np.arange(miny, maxy, tile_deg).tolist() or [miny]
    return [(x, y, min(x + tile_deg, maxx), min(y + tile_deg, maxy)) for x in xs for y in ys]


def _egdi_wfs(typename: str, bbox_4326: tuple, page: int = 5000) -> gpd.GeoDataFrame:
    """EGDI WFS GetFeature clipped to a lon/lat bbox, in EPSG:4326 (empty on
    failure). Transparently tiles bboxes wider/taller than `_EGDI_TILE_DEG` to
    avoid the server-side thinning described above; each tile is independently
    cached by net.http_get, so a wide-area rebuild replays cheaply."""
    minx, miny, maxx, maxy = bbox_4326
    if (maxx - minx) <= _EGDI_TILE_DEG and (maxy - miny) <= _EGDI_TILE_DEG:
        return _egdi_wfs_tile(typename, bbox_4326, page)
    frames = [_egdi_wfs_tile(typename, tile, page) for tile in _tile_bbox(bbox_4326, _EGDI_TILE_DEG)]
    frames = [f for f in frames if len(f)]
    if not frames:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    return gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs="EPSG:4326")


# EGDI INSPIRE `commodity` value -> our tag. The CRM layer omits tin; the full
# INSPIRE inventory has it, so we filter that server-side by exact commodity.
# Split by mineral system: granite-related metals (default fetch) vs base metals
# (VMS — fetched only for the `iberia` region, which uses volcanic-host evidence).
_EGDI_GRANITE = {"Tin": "Sn", "Tungsten": "W", "Lithium": "Li",
                 "Tantalum": "Ta", "Niobium": "Nb",
                 "Uranium": "U", "Molybdenum": "Mo", "Beryllium": "Be",
                 "Bismuth": "Bi", "Baryte": "Ba", "Arsenic": "As", "Antimony": "Sb"}
_EGDI_VMS = {"Copper": "Cu", "Zinc": "Zn", "Lead": "Pb", "Silver": "Ag"}
_EGDI_COMMODITY = {**_EGDI_GRANITE, **_EGDI_VMS}


def egdi_occurrences(bbox_4326: tuple, egdi_names=None) -> gpd.GeoDataFrame:
    """Pan-European mineral occurrences from the EGDI full INSPIRE inventory,
    filtered server-side to a set of exact `commodity` values (default = the
    granite-related metals; the CRM subset layer has almost no tin, so we query
    the full inventory). Schema like igme_occurrences; geometry from the point's
    longitude/latitude columns (avoids the WFS 1.1.0 lat,lon axis ambiguity)."""
    names = egdi_names if egdi_names is not None else _EGDI_GRANITE
    cols = ["commodity", "sustancia", "name", "municipio", "provincia",
            "asociacion", "morfologia", "geometry"]
    fltr = ('<ogc:Filter xmlns:ogc="http://www.opengis.net/ogc"><ogc:Or>'
            + "".join(f"<ogc:PropertyIsEqualTo><ogc:PropertyName>commodity</ogc:PropertyName>"
                      f"<ogc:Literal>{v}</ogc:Literal></ogc:PropertyIsEqualTo>"
                      for v in names)
            + "</ogc:Or></ogc:Filter>")
    params = {"service": "WFS", "version": "1.1.0", "request": "GetFeature",
              "typeName": ENDPOINTS.egdi_occurrences_layer, "srsName": "EPSG:4326", "FILTER": fltr}
    try:
        gdf = gpd.read_file(io.BytesIO(net.http_get(
            ENDPOINTS.egdi_wfs, params=params, timeout=300, tag="egdi:occurrences")))
    except Exception:
        return gpd.GeoDataFrame(columns=cols, geometry="geometry", crs=config.CRS)
    if gdf.empty:
        return gpd.GeoDataFrame(columns=cols, geometry="geometry", crs=config.CRS)

    lon = pd.to_numeric(gdf.get("longitude"), errors="coerce")
    lat = pd.to_numeric(gdf.get("latitude"), errors="coerce")
    comm = gdf.get("commodity", pd.Series([""] * len(gdf))).fillna("").astype(str)
    country = gdf.get("country", pd.Series([""] * len(gdf))).fillna("").astype(str)
    out = gpd.GeoDataFrame(
        {
            "commodity": comm.map(_EGDI_COMMODITY).fillna("other"),
            "sustancia": comm,
            "name": gdf.get("name", pd.Series([""] * len(gdf))).astype(str).str.strip(),
            "municipio": country, "provincia": country,
            "asociacion": gdf.get("deposit_type", pd.Series([""] * len(gdf))),
            "morfologia": gdf.get("mine_status", pd.Series([""] * len(gdf))),
        },
        geometry=gpd.points_from_xy(lon, lat), crs="EPSG:4326",
    )
    minx, miny, maxx, maxy = bbox_4326
    out = out[out.geometry.notna()].cx[minx:maxx, miny:maxy]
    return out.to_crs(config.CRS)


def egdi_basemetals(bbox_4326: tuple) -> gpd.GeoDataFrame:
    """VMS base-metal occurrences (Cu/Zn/Pb/Ag) for the `iberia` region — the
    Iberian Pyrite Belt inventory, fetched server-side from the full EGDI set."""
    return egdi_occurrences(bbox_4326, egdi_names=_EGDI_VMS)


def egdi_granite(bbox_4326: tuple) -> gpd.GeoDataFrame:
    """Pan-European granite/granitoid lithology polygons (EGDI 1:1M geologic
    units, filtered on representativelithology_title), in config.CRS."""
    gdf = _egdi_wfs(ENDPOINTS.egdi_geolunits_layer, bbox_4326)
    if gdf.empty or "representativelithology_title" not in gdf:
        return gpd.GeoDataFrame(columns=["DLO", "geometry"], geometry="geometry", crs=config.CRS)
    lith = gdf["representativelithology_title"].fillna("").str.lower()
    kws = ["granit", "granodior", "leucogran", "monzogran", "aplit", "pegmat", "granitoid"]
    m = lith.apply(lambda s: any(k in s for k in kws))
    out = gdf[m].copy()
    out["DLO"] = out["representativelithology_title"]
    return out[["DLO", "geometry"]].set_geometry("geometry").set_crs("EPSG:4326").to_crs(config.CRS)


def egdi_felsic_volcanics(bbox_4326: tuple) -> gpd.GeoDataFrame:
    """Felsic/fine-grained volcanic + pyroclastic lithology polygons (EGDI 1:1M
    geologic units) — the host evidence for VMS base-metal deposits (the Iberian
    Pyrite Belt's Volcano-Sedimentary Complex). At 1:1M the belt is mapped as
    finegrainedigneousrock + pyroclasticrock + rhyolitoid; this is the same shape
    as egdi_granite so it drops straight into the pipeline as the 'granite' slot.
    Caveat: finegrainedigneousrock lumps felsic and mafic volcanics — proximity to
    the volcanic pile is a first-order VMS control, not a lithology-exact filter."""
    gdf = _egdi_wfs(ENDPOINTS.egdi_geolunits_layer, bbox_4326)
    if gdf.empty or "representativelithology_title" not in gdf:
        return gpd.GeoDataFrame(columns=["DLO", "geometry"], geometry="geometry", crs=config.CRS)
    lith = gdf["representativelithology_title"].fillna("").str.lower()
    kws = ["finegrainedigneous", "pyroclast", "rhyol", "riol", "dacit",
           "volcan", "ignimbr", "tuff", "felsic", "acidigneous"]
    m = lith.apply(lambda s: any(k in s for k in kws))
    out = gdf[m].copy()
    out["DLO"] = out["representativelithology_title"]
    return out[["DLO", "geometry"]].set_geometry("geometry").set_crs("EPSG:4326").to_crs(config.CRS)


def egdi_faults(bbox_4326: tuple) -> gpd.GeoDataFrame:
    """Pan-European fault traces (EGDI HIKE database), in config.CRS."""
    gdf = _egdi_wfs(ENDPOINTS.egdi_faults_layer, bbox_4326)
    if gdf.empty:
        return gpd.GeoDataFrame(columns=["TIPO", "geometry"], geometry="geometry", crs=config.CRS)
    return gdf[gdf.geometry.notna()].to_crs(config.CRS)


# --------------------------------------------------------------------------- #
# BDMIN Explotaciones — existing mine workings (friction + context)            #
# --------------------------------------------------------------------------- #

def mining_workings(bbox_4326: tuple) -> gpd.GeoDataFrame:
    """Existing mine workings/exploitations (points) over `bbox_4326` from IGME
    BDMIN Explotaciones — the available signal for "existing mining activity".
    Schema in config.CRS: geometry (points) + columns
      sustancia  worked substance
      estado     Estado_Explotacion (e.g. 'Activa' / 'Abandonada' / 'Inactiva')
      active     True where estado starts with 'Activ'
      municipio, forma (Forma_Explotacion)
    NOTE: the legal mining-rights registry (Catastro Minero, MITECO/regional) is
    not exposed as open REST features; these worked-deposit points are the proxy.
    """
    gdf = _arcgis_query(ENDPOINTS.igme_bdmin_explotaciones_svc,
                        layer=ENDPOINTS.igme_bdmin_explotaciones_layer, bbox_4326=bbox_4326)
    cols = ["sustancia", "estado", "active", "municipio", "forma", "geometry"]
    if gdf.empty:
        return gpd.GeoDataFrame(columns=cols, geometry="geometry", crs=config.CRS)
    estado = gdf.get("Estado_Explotacion", pd.Series([""] * len(gdf))).fillna("").astype(str).str.strip()
    out = gpd.GeoDataFrame(
        {
            "sustancia": gdf.get("Sustancia", pd.Series([""] * len(gdf))).astype(str).str.strip(),
            "estado": estado,
            "active": estado.str.lower().str.startswith("activ"),
            "municipio": gdf.get("Municipio", pd.Series([""] * len(gdf))).astype(str).str.strip(),
            "forma": gdf.get("Forma_Explotacion", pd.Series([""] * len(gdf))).astype(str).str.strip(),
        },
        geometry=gdf.geometry, crs="EPSG:4326",
    ).to_crs(config.CRS)
    return out


def mining_concessions(bbox_4326: tuple) -> gpd.GeoDataFrame:
    """Legal mining-rights concession polygons over `bbox_4326` from the MITECO
    national Catastro Minero WFS (derechosMineros). Schema in config.CRS:
    geometry (polygons) + columns
      name    concession name (nombre)
      tipo    right/status code (leyenda, e.g. 'CO', 'CCD', 'PT')
      status  'granted' (…O) / 'pending' (…T) / 'lapsed' (…CD) / 'other'
      blocks  True if the right blocks acquisition (granted or pending)
    Fetches GML 3.1.1 (the server's GeoJSON template is broken) via WFS 1.0.0
    (lon,lat bbox order). Geometry is lon/lat regardless of the SRS label."""
    params = {
        "SERVICE": "WFS", "VERSION": "1.0.0", "REQUEST": "GetFeature",
        "TYPENAME": "derechosMineros", "SRSNAME": "EPSG:4326",
        "BBOX": ",".join(map(str, bbox_4326)),
    }
    cols = ["name", "tipo", "status", "blocks", "geometry"]
    try:
        gdf = gpd.read_file(io.BytesIO(net.http_get(
            ENDPOINTS.catastro_minero_wfs, params=params, tag="miteco:concessions"))
        ).set_crs("EPSG:4326", allow_override=True)
    except Exception:
        return gpd.GeoDataFrame(columns=cols, geometry="geometry", crs=config.CRS)
    if gdf.empty or "geometry" not in gdf:
        return gpd.GeoDataFrame(columns=cols, geometry="geometry", crs=config.CRS)

    ley = gdf.get("leyenda", pd.Series([""] * len(gdf))).fillna("").astype(str).str.upper()

    def status(code: str) -> str:
        if code.endswith("CD"):
            return "lapsed"
        if code.endswith("O"):
            return "granted"
        if code.endswith("T"):
            return "pending"
        return "other"

    st = ley.map(status)
    out = gpd.GeoDataFrame(
        {
            "name": gdf.get("nombre", pd.Series([""] * len(gdf))).astype(str).str.strip(),
            "tipo": ley,
            "status": st,
            "blocks": st.isin(["granted", "pending"]),
        },
        geometry=gdf.geometry, crs="EPSG:4326",
    )
    return out[out.geometry.notna()].to_crs(config.CRS)


def mining_concessions_cyl(bbox_4326: tuple) -> gpd.GeoDataFrame:
    """Castilla y León mining rights from the IDECyL GeoServer WFS (fresher than
    the MITECO national aggregate; clean GeoJSON with readable tipo/estado).
    Same schema as mining_concessions: name/tipo/status/blocks in config.CRS."""
    params = {
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeNames": "mineria:cami_cyl_derecho_minero",
        "outputFormat": "application/json", "srsName": "EPSG:4326",
        "bbox": ",".join(map(str, bbox_4326)) + ",EPSG:4326",
    }
    cols = ["name", "tipo", "status", "blocks", "geometry"]
    try:
        gdf = gpd.read_file(io.BytesIO(net.http_get(
            ENDPOINTS.idecyl_mineria_wfs, params=params, tag="idecyl:concessions")))
    except Exception:
        return gpd.GeoDataFrame(columns=cols, geometry="geometry", crs=config.CRS)
    if gdf.empty or "geometry" not in gdf:
        return gpd.GeoDataFrame(columns=cols, geometry="geometry", crs=config.CRS)
    estado = gdf.get("estado", pd.Series([""] * len(gdf))).fillna("").astype(str).str.strip()
    st = estado.str.lower().map(lambda e: "granted" if e.startswith("vigen")
                                else ("lapsed" if e.startswith("caduc") else "other"))
    out = gpd.GeoDataFrame(
        {
            "name": gdf.get("denominacion", pd.Series([""] * len(gdf))).astype(str).str.strip(),
            "tipo": gdf.get("tipo", pd.Series([""] * len(gdf))).astype(str).str.strip(),
            "status": st,
            "blocks": st == "granted",
        },
        geometry=gdf.geometry, crs="EPSG:4326",
    )
    return out[out.geometry.notna()].to_crs(config.CRS)


def concessions_for(provincia: str, bbox_4326: tuple) -> gpd.GeoDataFrame:
    """Fetch legal mining concessions for a region, preferring the fresher
    IDECyL WFS for Castilla y León provinces and falling back to the MITECO
    national WFS elsewhere."""
    prov = _norm(provincia)
    if prov in config.CYL_PROVINCES:
        cyl = mining_concessions_cyl(bbox_4326)
        if len(cyl):
            return cyl
    return mining_concessions(bbox_4326)


# --------------------------------------------------------------------------- #
# Catastro — INSPIRE cadastral parcels (ATOM → per-municipio GML zip)          #
# --------------------------------------------------------------------------- #

_ATOM_ROOT = "https://www.catastro.hacienda.gob.es/INSPIRE/CadastralParcels"


def _norm(s: str) -> str:
    """Uppercase, strip accents/punctuation — for matching BDMIN municipio
    names to Catastro ATOM names (e.g. 'Cañaveral' ~ 'CAÑAVERAL')."""
    s = unicodedata.normalize("NFD", str(s))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def _decode_atom(b: bytes) -> str:
    """Catastro ATOM feeds mix encodings — the national office index is latin-1
    (lone 0xf1 = ñ), the per-province feeds are utf-8 (0xc3 0xb1). Try utf-8
    strict, fall back to latin-1 (which can't raise); either way ñ/í survive."""
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("latin-1")


def catastro_province_index() -> dict:
    """{normalized province name -> 2-digit code} from the national ATOM."""
    text = _decode_atom(net.http_get(ENDPOINTS.catastro_atom, tag="catastro:atom_root"))
    # entries look like: <title>Territorial office 10 Cáceres</title>
    idx = {}
    for m in re.finditer(r"office\s+(\d{2})\s+([^<]+)</title>", text):
        idx[_norm(m.group(2))] = m.group(1)
    return idx


def catastro_municipio_index(prov_code: str) -> list:
    """[(muni_code, atom_name)] for a province, from its ATOM feed."""
    url = f"{_ATOM_ROOT}/{prov_code}/ES.SDGC.CP.atom_{prov_code}.xml"
    text = _decode_atom(net.http_get(url, tag=f"catastro:atom_{prov_code}"))
    out = []
    for m in re.finditer(r"CadastralParcels/\d{2}/(\d{5})-([^/]+)/A\.ES\.SDGC\.CP\.\d{5}\.zip", text):
        out.append((m.group(1), m.group(2)))
    return out


def resolve_municipios(prov_code: str, names) -> list:
    """Match BDMIN municipio `names` to Catastro (code, atom_name) entries in a
    province. Normalized exact match first, then substring. Returns unique hits."""
    index = catastro_municipio_index(prov_code)
    norm_index = [(c, n, _norm(n)) for c, n in index]
    hits, seen = [], set()
    for name in names:
        q = _norm(name)
        if not q:
            continue
        match = next((e for e in norm_index if e[2] == q), None) \
            or next((e for e in norm_index if q in e[2] or e[2] in q), None)
        if match and match[0] not in seen:
            seen.add(match[0])
            hits.append((match[0], match[1]))
    return hits


def _municipio_zip_url(prov_code: str, muni_code: str, muni_name: str) -> str:
    return f"{_ATOM_ROOT}/{prov_code}/{muni_code}-{muni_name}/A.ES.SDGC.CP.{muni_code}.zip"


def catastro_parcels(muni_code: str, muni_name: str,
                     prov_code: str | None = None,
                     min_area_ha: float = 0.0) -> gpd.GeoDataFrame:
    """Download one municipio's cadastral parcels from the INSPIRE ATOM store.

    muni_code is the 5-digit INE code (province in the first two digits).
    Returns parcels in config.CRS with the pipeline schema; cadastral value is
    not published in INSPIRE CP, so `cadastral_eur_ha` is NaN.
    """
    prov_code = prov_code or muni_code[:2]
    url = _municipio_zip_url(prov_code, muni_code, muni_name)
    with zipfile.ZipFile(io.BytesIO(net.http_get(url, tag=f"catastro:cp:{muni_code}"))) as zf:
        gml = [n for n in zf.namelist()
               if n.lower().endswith(".gml") and "cadastralparcel" in n.lower()]
        gml = gml or [n for n in zf.namelist() if n.lower().endswith(".gml")]
        if not gml:
            raise ValueError(f"no CadastralParcel GML inside {url}")
        with zf.open(gml[0]) as f:
            gdf = gpd.read_file(f)

    gdf = gdf.to_crs(config.CRS)
    ref = None
    for cand in ("localId", "nationalCadastralReference", "inspireId", "gml_id"):
        if cand in gdf.columns:
            ref = gdf[cand].astype(str)
            break
    if ref is None:
        ref = pd.Series([f"{muni_code}-{i}" for i in range(len(gdf))])
    # strip INSPIRE id prefixes like "ES.SDGC.CP.10118..." to the cadastral ref
    ref = ref.map(lambda s: re.sub(r"^.*CP\.", "", s))

    out = gpd.GeoDataFrame(
        {
            "parcel_id": ref.values,
            "municipio": muni_name,
            "area_ha": (gdf.geometry.area / 10_000.0).round(2),
            "cadastral_eur_ha": np.nan,   # not in INSPIRE CP
            "listed": False,
            "asking_eur_ha": np.nan,
            "listing_url": None,
        },
        geometry=gdf.geometry, crs=config.CRS,
    )
    out = out[out.geometry.notna() & (out["area_ha"] >= min_area_ha)]
    return out.reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Per-country cadastres for the Europe-region hotspot drill (bbox-based)        #
# --------------------------------------------------------------------------- #

_PARCEL_COLS = ["parcel_id", "municipio", "area_ha", "cadastral_eur_ha",
                "listed", "asking_eur_ha", "listing_url"]


def _empty_parcels() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(columns=_PARCEL_COLS + ["geometry"], geometry="geometry", crs=config.CRS)


_dvf_cache: dict = {}   # department code -> {code_commune: median €/ha}


def dvf_commune_eur_ha(dep_codes) -> dict:
    """Median land €/ha per commune (INSEE code) from the open French DVF
    transaction data (geo-dvf), for the given 2-digit department codes. Filters
    to unbuilt land sales; cached per department. Empty dict on failure."""
    import gzip
    out: dict = {}
    for dep in {str(d).zfill(2) for d in dep_codes if d}:
        if dep in _dvf_cache:
            out.update(_dvf_cache[dep]); continue
        d: dict = {}
        for year in ("2024", "2023"):
            url = f"https://files.data.gouv.fr/geo-dvf/latest/csv/{year}/departements/{dep}.csv.gz"
            try:
                content = net.http_get(url, tag=f"dvf:{dep}:{year}")
                df = pd.read_csv(io.BytesIO(gzip.decompress(content)), low_memory=False)
                land = df[(df.nature_mutation == "Vente") & (df.type_local.isna())
                          & (df.surface_terrain > 1000) & (df.valeur_fonciere > 0)].copy()
                land["eur_ha"] = land.valeur_fonciere / (land.surface_terrain / 10_000.0)
                land = land[(land.eur_ha > 200) & (land.eur_ha < 80_000)]
                d = {str(int(k)).zfill(5): round(float(v))
                     for k, v in land.groupby("code_commune").eur_ha.median().items()}
                break
            except Exception:
                continue
        _dvf_cache[dep] = d
        out.update(d)
    return out


def cadastre_france(bbox_4326: tuple, min_area_ha: float = 0.0) -> gpd.GeoDataFrame:
    """Cadastral parcels for a lon/lat bbox from the French IGN Géoplateforme
    WFS (PARCELLAIRE EXPRESS, open). Returns the pipeline parcel schema."""
    minx, miny, maxx, maxy = bbox_4326
    params = {
        "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
        "TYPENAMES": "CADASTRALPARCELS.PARCELLAIRE_EXPRESS:parcelle",
        "SRSNAME": "urn:ogc:def:crs:EPSG::4326", "OUTPUTFORMAT": "application/json",
        "COUNT": "10000",   # WFS 2.0 + urn:EPSG::4326 bbox is lat,lon order
        "BBOX": f"{miny},{minx},{maxy},{maxx},urn:ogc:def:crs:EPSG::4326",
    }
    try:
        gdf = gpd.read_file(io.BytesIO(net.http_get(
            "https://data.geopf.fr/wfs/ows", params=params, tag="cadastre:france")))
    except Exception:
        return _empty_parcels()
    if gdf.empty:
        return _empty_parcels()
    insee = gdf.get("code_insee", pd.Series([""] * len(gdf))).astype(str)
    # real land price: median €/ha of recent DVF land sales in the parcel's commune
    prices = dvf_commune_eur_ha(insee.str[:2].unique())
    out = gpd.GeoDataFrame(
        {
            "parcel_id": gdf.get("idu", gdf.index.astype(str)).astype(str),
            "municipio": gdf.get("nom_com", pd.Series([""] * len(gdf))).astype(str).str.strip(),
            "area_ha": (pd.to_numeric(gdf.get("contenance"), errors="coerce") / 10_000.0).round(2),
            "cadastral_eur_ha": insee.map(prices).astype(float),
            "listed": False, "asking_eur_ha": np.nan, "listing_url": None,
        },
        geometry=gdf.geometry, crs="EPSG:4326",
    )
    out = out[out.geometry.notna() & (out["area_ha"].fillna(0) >= min_area_ha)]
    return out.to_crs(config.CRS)


def cadastre_czechia(bbox_4326: tuple, min_area_ha: float = 0.0) -> gpd.GeoDataFrame:
    """Cadastral parcels for a lon/lat bbox from the Czech ČÚZK INSPIRE CP WFS
    (GML; ~99% national coverage). Returns the pipeline parcel schema."""
    minx, miny, maxx, maxy = bbox_4326
    params = {
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeNames": "cp:CadastralParcel", "srsName": "urn:ogc:def:crs:EPSG::4326",
        "count": "10000",   # WFS 2.0 + urn bbox is lat,lon order
        "bbox": f"{miny},{minx},{maxy},{maxx},urn:ogc:def:crs:EPSG::4326",
    }
    try:
        gdf = gpd.read_file(io.BytesIO(net.http_get(
            "https://services.cuzk.gov.cz/wfs/inspire-cp-wfs.asp",
            params=params, tag="cadastre:czechia")))
    except Exception:
        return _empty_parcels()
    if gdf.empty or "geometry" not in gdf:
        return _empty_parcels()
    out = gpd.GeoDataFrame(
        {
            "parcel_id": gdf.get("nationalCadastralReference", gdf.get("localId")).astype(str),
            "municipio": gdf.get("label", pd.Series([""] * len(gdf))).astype(str),
            "area_ha": (pd.to_numeric(gdf.get("areaValue"), errors="coerce") / 10_000.0).round(2),
            "cadastral_eur_ha": np.nan, "listed": False, "asking_eur_ha": np.nan, "listing_url": None,
        },
        geometry=gdf.geometry, crs="EPSG:4326",
    )
    out = out[out.geometry.notna() & (out["area_ha"].fillna(0) >= min_area_ha)]
    return out.to_crs(config.CRS)


def cadastre_saxony(bbox_4326: tuple, min_area_ha: float = 0.0) -> gpd.GeoDataFrame:
    """Cadastral parcels for a lon/lat bbox from Saxony's GeoSN ALKIS-WFS
    (AdV simplified schema, `ave:Flurstueck`, weekly-updated, native EPSG:25833).
    Covers the German side of the Erzgebirge Sn-W-Li belt (Zinnwald/Altenberg).
    Germany's cadastre is per-Bundesland; this is Saxony only, so a bbox outside
    Saxony just comes back empty."""
    from pyproj import Transformer
    t = Transformer.from_crs("EPSG:4326", "EPSG:25833", always_xy=True)
    minx, miny, maxx, maxy = bbox_4326
    xs, ys = zip(*(t.transform(x, y) for x in (minx, maxx) for y in (miny, maxy)))
    params = {
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeNames": "ave:Flurstueck", "count": "10000",
        # projected-CRS urn → easting,northing (normal x,y) order
        "srsName": "urn:ogc:def:crs:EPSG::25833",
        "bbox": f"{min(xs)},{min(ys)},{max(xs)},{max(ys)},urn:ogc:def:crs:EPSG::25833",
    }
    try:
        gdf = gpd.read_file(io.BytesIO(net.http_get(
            "https://geodienste.sachsen.de/aaa/public_alkis/vereinf/wfs",
            params=params, tag="cadastre:saxony")))
    except Exception:
        return _empty_parcels()
    if gdf.empty or "geometry" not in gdf:
        return _empty_parcels()
    out = gpd.GeoDataFrame(
        {
            "parcel_id": gdf.get("flstkennz", gdf.get("gml_id")).astype(str),
            "municipio": gdf.get("gemeinde", pd.Series([""] * len(gdf))).astype(str).str.strip(),
            "area_ha": (pd.to_numeric(gdf.get("flaeche"), errors="coerce") / 10_000.0).round(2),
            "cadastral_eur_ha": np.nan, "listed": False, "asking_eur_ha": np.nan, "listing_url": None,
        },
        geometry=gdf.geometry, crs="EPSG:25833",
    )
    out = out[out.geometry.notna() & (out["area_ha"].fillna(0) >= min_area_ha)]
    return out.to_crs(config.CRS)


def cadastre_spain(bbox_4326: tuple, min_area_ha: float = 0.0) -> gpd.GeoDataFrame:
    """Cadastral parcels for a lon/lat bbox from the Spanish Catastro INSPIRE CP
    WFS (`cp:CadastralParcel`, GML, national). This is the bbox path (the spain
    region's municipio ATOM path is `catastro_parcels_for`); it lets the Iberian
    Pyrite Belt (`iberia`) and Spain-in-EU-view hotspots drill. INSPIRE CP has no
    cadastral value or municipio name, so those stay NaN/blank. The service is
    slow (~1 min per box) but the response is cached by net.http_get."""
    minx, miny, maxx, maxy = bbox_4326
    params = {
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeNames": "cp:CadastralParcel", "srsName": "urn:ogc:def:crs:EPSG::4326",
        # WFS 2.0 + urn:EPSG::4326 bbox is lat,lon order (GDAL flips geometry back)
        "bbox": f"{miny},{minx},{maxy},{maxx},urn:ogc:def:crs:EPSG::4326",
    }
    try:
        gdf = gpd.read_file(io.BytesIO(net.http_get(
            "http://ovc.catastro.meh.es/INSPIRE/wfsCP.aspx",
            params=params, timeout=300, tag="cadastre:spain")))
    except Exception:
        return _empty_parcels()
    if gdf.empty or "geometry" not in gdf:
        return _empty_parcels()
    ref = gdf.get("nationalCadastralReference", gdf.get("localId"))
    out = gpd.GeoDataFrame(
        {
            "parcel_id": ref.astype(str),
            "municipio": "",   # INSPIRE CP carries no municipality name
            "area_ha": (pd.to_numeric(gdf.get("areaValue"), errors="coerce") / 10_000.0).round(2),
            "cadastral_eur_ha": np.nan, "listed": False, "asking_eur_ha": np.nan, "listing_url": None,
        },
        geometry=gdf.geometry, crs="EPSG:4326",
    )
    out = out[out.geometry.notna() & (out["area_ha"].fillna(0) >= min_area_ha)]
    return out.to_crs(config.CRS)


def cadastre_portugal(bbox_4326: tuple, min_area_ha: float = 0.0) -> gpd.GeoDataFrame:
    """Cadastral parcels for a lon/lat bbox from Portugal's SNIC/DGT INSPIRE CP
    WFS (national, CC BY 4.0). Coverage is geographically lopsided — dense in
    the south (Alentejo/Iberian Pyrite Belt, where `iberia`'s hotspots are) but
    sparse-to-empty in the north (Porto, the Covas do Barroso lithium mine, the
    Panasqueira Sn-W belt), so this is wired only into the VMS `iberia` region,
    not `europe`'s Portugal hotspots. Two gotchas found by live-testing (not
    documented anywhere): (1) omitting `srsName=EPSG:4326` on GetFeature makes
    the geometry silently come back in an unlabelled Portuguese projected CRS
    with no error; (2) the bbox param is lon,lat order with a plain `EPSG:4326`
    suffix — NOT lat,lon like Spain/Czechia's WFS 2.0 endpoints. INSPIRE CP has
    no cadastral value or municipality name (only a numeric administrative-unit
    code, would need a separate CAOP lookup — same gap as Spain)."""
    minx, miny, maxx, maxy = bbox_4326
    params = {
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeNames": "inspire:cadastralparcel", "srsName": "EPSG:4326",
        "bbox": f"{minx},{miny},{maxx},{maxy},EPSG:4326", "count": "10000",
    }
    try:
        gdf = gpd.read_file(io.BytesIO(net.http_get(
            "https://snicws.dgterritorio.gov.pt/geoserver/inspire/wfs",
            params=params, timeout=180, tag="cadastre:portugal")))
    except Exception:
        return _empty_parcels()
    if gdf.empty or "geometry" not in gdf:
        return _empty_parcels()
    out = gpd.GeoDataFrame(
        {
            "parcel_id": gdf.get("nationalcadastralreference", gdf.get("gml_id")).astype(str),
            "municipio": "",   # INSPIRE CP carries no municipality name
            "area_ha": (pd.to_numeric(gdf.get("areavalue"), errors="coerce") / 10_000.0).round(2),
            "cadastral_eur_ha": np.nan, "listed": False, "asking_eur_ha": np.nan, "listing_url": None,
        },
        geometry=gdf.geometry, crs="EPSG:4326",
    )
    out = out[out.geometry.notna() & (out["area_ha"].fillna(0) >= min_area_ha)]
    return out.to_crs(config.CRS)


# country name (normalized) -> bbox parcel provider. Germany = Saxony only
# (ALKIS is per-Bundesland; Saxony covers the Erzgebirge belt). Spain via the
# national Catastro CP WFS (bbox path, distinct from the spain region's
# municipio ATOM). Portugal via SNIC/DGT (see cadastre_portugal for coverage
# caveats — south only, which is exactly where iberia's hotspots are).
_COUNTRY_CADASTRE = {"FRANCE": cadastre_france, "CZECHIA": cadastre_czechia,
                     "GERMANY": cadastre_saxony, "SPAIN": cadastre_spain,
                     "PORTUGAL": cadastre_portugal}


def parcels_for_country(country: str, bbox_4326: tuple, min_area_ha: float = 0.0) -> gpd.GeoDataFrame:
    """Dispatch to a country's open cadastre for parcels in a lon/lat bbox.
    Empty frame for countries without a supported open cadastre."""
    fn = _COUNTRY_CADASTRE.get(_norm(country))
    return fn(bbox_4326, min_area_ha) if fn else _empty_parcels()


def _bbox_countries(bbox_4326: tuple) -> list:
    """Normalized names of the countries whose land the lon/lat bbox overlaps
    (only those with a supported cadastre). Falls back to [] if NE is missing."""
    minx, miny, maxx, maxy = bbox_4326
    countries = natural_earth_countries()
    if not len(countries):
        return []
    from shapely.geometry import box
    hit = countries[countries.intersects(box(minx, miny, maxx, maxy))]
    seen = []
    for nm in hit["name"]:
        n = _norm(nm)
        if n in _COUNTRY_CADASTRE and n not in seen:
            seen.append(n)
    return seen


def parcels_for_bbox(country: str, bbox_4326: tuple, min_area_ha: float = 0.0) -> gpd.GeoDataFrame:
    """Border-aware drill: fetch parcels from EVERY country whose land the
    hotspot bbox overlaps, not just the majority-occurrence one — the Sn-W-Li
    belts straddle borders (the Erzgebirge is DE/CZ), so a single-country
    dispatch misses half the ground. Concatenates each country's cadastre;
    `country` is kept as a fallback if the NE country lookup is unavailable."""
    names = _bbox_countries(bbox_4326)
    if not names:
        fb = _norm(country)
        names = [fb] if fb in _COUNTRY_CADASTRE else []
    frames = []
    for n in names:
        try:
            p = _COUNTRY_CADASTRE[n](bbox_4326, min_area_ha)
            if len(p):
                p = p.copy(); p["country"] = n.title()
                frames.append(p)
        except Exception:
            pass
    if not frames:
        return _empty_parcels()
    return gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=frames[0].crs)


def catastro_parcels_for(provincia: str, municipio_names, n_munis: int = 3,
                         min_area_ha: float = 0.0) -> gpd.GeoDataFrame:
    """Resolve a province + BDMIN municipio names to Catastro codes and fetch
    their parcels — the Spain `parcels_provider` used by the hotspot drill.
    Returns an empty frame if the province can't be resolved."""
    pidx = catastro_province_index()
    q = _norm(provincia)
    prov_code = pidx.get(q) or next((c for k, c in pidx.items() if q in k or k in q), None)
    if not prov_code:
        return gpd.GeoDataFrame(geometry=[], crs=config.CRS)
    frames = []
    for code, name in resolve_municipios(prov_code, municipio_names)[:n_munis]:
        try:
            frames.append(catastro_parcels(code, name, min_area_ha=min_area_ha))
        except Exception:
            pass
    if not frames:
        return gpd.GeoDataFrame(geometry=[], crs=config.CRS)
    return gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=config.CRS)


# --------------------------------------------------------------------------- #
# MITECO — Natura 2000 protected areas (optional; graceful empty on failure)   #
# --------------------------------------------------------------------------- #

def natura2000(bbox_4326: tuple) -> gpd.GeoDataFrame:
    """Natura 2000 protected polygons intersecting the window, in config.CRS.
    Returns an empty frame (not an error) if the WFS is unreachable."""
    params = {
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeNames": "LIC",  # Sites of Community Importance; ZEC/ZEPA also exist
        "bbox": ",".join(map(str, bbox_4326)) + ",EPSG:4326",
        "srsName": "EPSG:4326", "outputFormat": "application/json",
    }
    try:
        gdf = gpd.read_file(io.BytesIO(net.http_get(
            ENDPOINTS.natura2000_wfs, params=params, tag="natura2000")))
        if gdf.empty:
            raise ValueError("empty")
        return gdf.set_crs("EPSG:4326", allow_override=True).to_crs(config.CRS)
    except Exception:
        return gpd.GeoDataFrame({"site": []}, geometry=[], crs=config.CRS)


# --------------------------------------------------------------------------- #
# idealista — needs approved OAuth token (kept for when one is available)      #
# --------------------------------------------------------------------------- #

def natural_earth_land() -> gpd.GeoDataFrame:
    """Natural Earth 1:50m land polygons (EPSG:4326), cached locally — used to
    mask sea cells out of the displayed heatmap. Empty frame if unreachable."""
    cache = os.path.join(os.path.dirname(__file__), "_ne_land_50m.geojson")
    if not os.path.exists(cache):
        url = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
               "master/geojson/ne_50m_land.geojson")
        try:
            r = requests.get(url, headers=_UA, timeout=_TIMEOUT)
            r.raise_for_status()
            with open(cache, "wb") as f:
                f.write(r.content)
        except Exception:
            return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    try:
        return gpd.read_file(cache).set_crs("EPSG:4326", allow_override=True)
    except Exception:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")


def natural_earth_countries() -> gpd.GeoDataFrame:
    """Natural Earth 1:50m country polygons (EPSG:4326) with a `name` column,
    cached locally — used to find which countries a hotspot bbox straddles so the
    drill can pull each one's cadastre. Empty frame if unreachable."""
    cache = os.path.join(os.path.dirname(__file__), "_ne_countries_50m.geojson")
    if not os.path.exists(cache):
        url = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
               "master/geojson/ne_50m_admin_0_countries.geojson")
        try:
            r = requests.get(url, headers=_UA, timeout=_TIMEOUT)
            r.raise_for_status()
            with open(cache, "wb") as f:
                f.write(r.content)
        except Exception:
            return gpd.GeoDataFrame(columns=["name", "geometry"], geometry="geometry", crs="EPSG:4326")
    try:
        g = gpd.read_file(cache).set_crs("EPSG:4326", allow_override=True)
        name_col = next((c for c in ("ADMIN", "NAME_EN", "NAME", "SOVEREIGNT") if c in g.columns), None)
        g["name"] = g[name_col].astype(str) if name_col else ""
        return g[["name", "geometry"]]
    except Exception:
        return gpd.GeoDataFrame(columns=["name", "geometry"], geometry="geometry", crs="EPSG:4326")


_EUROSTAT_LPRC = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/apri_lprc"
_NUTS_GEOJSON = ("https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/"
                 "NUTS_RG_20M_2021_4326_LEVL_2.geojson")


def eurostat_land_price() -> dict:
    """{NUTS code -> arable-land price €/ha} from Eurostat apri_lprc (latest year
    available per region, all NUTS levels). Used as an *estimated* price prior
    where no real transaction price exists (Spain/Germany/Czechia); France keeps
    its real DVF prices. Empty dict if unreachable."""
    try:
        d = json.loads(net.http_get(_EUROSTAT_LPRC, tag="eurostat:lprc", params={
            "format": "JSON", "lang": "EN", "agriprod": "ARA", "unit": "EUR_HA"}))
    except Exception:
        return {}
    dims, ids = d.get("dimension", {}), d.get("id", [])
    if "geo" not in dims or "time" not in dims:
        return {}
    sizes = [len(dims[k]["category"]["index"]) for k in ids]
    gi = dims["geo"]["category"]["index"]
    tm = dims["time"]["category"]["index"]
    years = sorted(tm)
    vals = d.get("value", {})

    def flat(gidx, tidx):
        idx = {"geo": gidx, "time": tidx}
        f = 0
        for k, sz in zip(ids, sizes):
            f = f * sz + idx.get(k, 0)
        return f

    out = {}
    for code, gidx in gi.items():
        for yr in reversed(years):
            v = vals.get(str(flat(gidx, tm[yr])))
            if v is not None:
                out[code] = round(float(v))
                break
    return out


def nuts_price_polygons() -> gpd.GeoDataFrame:
    """NUTS2 polygons (Eurostat GISCO, cached) tagged with an estimated arable-land
    `eur_ha` (NUTS2 → NUTS1 → NUTS0 fallback from Eurostat apri_lprc). EPSG:4326.
    Used to attach an estimated price to parcels that have no real one."""
    cache = os.path.join(os.path.dirname(__file__), "_nuts2_20m.geojson")
    if not os.path.exists(cache):
        try:
            with open(cache, "wb") as f:
                f.write(net.http_get(_NUTS_GEOJSON, tag="gisco:nuts2"))
        except Exception:
            return gpd.GeoDataFrame(columns=["eur_ha", "geometry"], geometry="geometry", crs="EPSG:4326")
    try:
        g = gpd.read_file(cache).set_crs("EPSG:4326", allow_override=True)
    except Exception:
        return gpd.GeoDataFrame(columns=["eur_ha", "geometry"], geometry="geometry", crs="EPSG:4326")
    # Eurostat lacks German land prices → fill from Destatis per-Bundesland (NUTS1)
    prices = {**config.DE_LAND_PRICE_EUR_HA, **eurostat_land_price()}
    idc = next((c for c in ("NUTS_ID", "id", "nuts_id") if c in g.columns), None)
    if not idc or not prices:
        return gpd.GeoDataFrame(columns=["eur_ha", "geometry"], geometry="geometry", crs="EPSG:4326")

    def look(code):
        for k in (str(code), str(code)[:3], str(code)[:2]):
            if k in prices:
                return prices[k]
        return None

    g["eur_ha"] = g[idc].map(look)
    g = g[g["eur_ha"].notna()].copy()
    g["eur_ha"] = g["eur_ha"].clip(500, 80_000)
    return g[["eur_ha", "geometry"]]


def idealista_listings(api_token: str, center_lat: float, center_lon: float,
                       distance_m: int = 50_000) -> pd.DataFrame:
    """Idealista official Search API. propertyType=lands, operation=sale.
    Returns a DataFrame of listings to be spatially matched to parcels."""
    r = requests.post(
        "https://api.idealista.com/3.5/es/search",
        headers={"Authorization": f"Bearer {api_token}"},
        data={"operation": "sale", "propertyType": "lands",
              "center": f"{center_lat},{center_lon}", "distance": distance_m,
              "maxItems": 50},
        timeout=60,
    )
    r.raise_for_status()
    items = r.json().get("elementList", [])
    return pd.DataFrame([
        {"lat": it.get("latitude"), "lon": it.get("longitude"),
         "price_eur": it.get("price"), "size_m2": it.get("size"),
         "listing_url": it.get("url")}
        for it in items
    ])
