"""Central configuration for the Subsuelo pipeline.

Region: western Extremadura / Sn-W-Li belt demo window around Cáceres.
CRS: EPSG:25829 (ETRS89 / UTM 29N) — the correct zone for Cáceres province
(west of -6°). The earlier config used zone 30N, which shifted the window
~400 km east onto the Mediterranean coast; 29N puts it over Extremadura.
"""

from dataclasses import dataclass

CRS = "EPSG:25829"

# 100 x 100 km window centred on Cáceres, covering the San José de
# Valdeflórez (Li) area and the surrounding Sn-W granite belt.
# (xmin, ymin, xmax, ymax) in EPSG:25829.  Corners ≈ lon -6.97..-5.77,
# lat 39.04..39.91 — all on land in Extremadura.
BBOX = (676_000.0, 4_323_000.0, 776_000.0, 4_423_000.0)

CELL_SIZE = 500.0  # metres; screening resolution


@dataclass(frozen=True)
class Endpoints:
    """Live data endpoints (Spain). Network required. Validated 2026-07
    against the live services; ministries reshuffle URLs, so re-check if a
    fetch 404s."""

    # Catastro INSPIRE ATOM feed: national → per-province → per-municipio GML zips.
    catastro_atom: str = (
        "http://www.catastro.hacienda.gob.es/INSPIRE/CadastralParcels/ES.SDGC.CP.atom.xml"
    )
    # IGME ArcGIS REST services root.
    igme_services_root: str = "https://mapas.igme.es/gis/rest/services"
    # IGME MapServer paths (pinned from the services root).
    igme_bdmin_indicios: str = "BasesDatos/IGME_BDMIN_Indicios"        # mineral occurrences (showings)
    igme_bdmin_explotaciones: str = "BasesDatos/IGME_BDMIN_Explotaciones"  # workings/mines
    igme_geology_caceres: str = "Cartografia_Geologica/IGME_GeologicoCaceres_200"  # 1:200k Cáceres sheet
    # Layer ids within the Cáceres geology MapServer:
    igme_geology_lines_layer: int = 5   # "Contactos y Fallas"  (contacts + faults)
    igme_geology_litho_layer: int = 7   # "Litologias color"    (lithology polygons)
    # National 1:1M geology (for run_national.py): same layer layout as a sheet.
    igme_geology_national: str = "Cartografia_Geologica/IGME_Geologico_1M"
    igme_geology_national_lines_layer: int = 2   # "Contactos y Fallas Geologico 1M"
    igme_geology_national_litho_layer: int = 4   # "Litologias color Geologico 1M"
    # BDMIN Explotaciones — real Spanish mine workings/exploitations (points,
    # with Estado_Explotacion = active/abandoned) — "existing mining activity".
    igme_bdmin_explotaciones_svc: str = "BasesDatos/IGME_BDMIN_Explotaciones"
    igme_bdmin_explotaciones_layer: int = 1
    # MITECO national Catastro Minero WFS — LEGAL mining rights (derechosMineros:
    # concession POLYGONS, `leyenda` = type+status). GeoJSON output is broken
    # server-side, so we fetch GML 3.1.1 and let GDAL parse it.
    catastro_minero_wfs: str = "https://geoportal.minetur.gob.es/cgi-bin/mapservcm"
    # IDECyL (Castilla y León) mining-rights WFS — fresher regional data, clean
    # GeoJSON, readable `tipo`/`estado`. Preferred over MITECO for CyL provinces.
    idecyl_mineria_wfs: str = "https://idecyl.jcyl.es/geoserver/mineria/wfs"
    # EGDI (European Geological Data Infrastructure) WFS — pan-European geology
    # + Minerals4EU/FRAME occurrences. JSON output 500s; fetch GML.
    egdi_wfs: str = "https://maps.europe-geology.eu/wfs/"
    # full INSPIRE inventory (not the CRM subset) — carries tin, which the CRM
    # layer omits; filtered server-side to Tin/Tungsten/Lithium.
    egdi_occurrences_layer: str = "ms:egdi_mineraloccurrences_inspire"
    egdi_geolunits_layer: str = "ms:geologicunitview"        # 1:1M lithology polygons
    egdi_faults_layer: str = "ms:hike_all_faults_layer"
    # MITECO Natura 2000 WFS.
    natura2000_wfs: str = "https://wms.mapama.gob.es/sig/Biodiversidad/RedNatura/wfs.aspx"


ENDPOINTS = Endpoints()

# --- Live-ingest tuning -----------------------------------------------------

# BDMIN "Sustancia" values (Spanish) that count as our target commodities.
# Matching is case-insensitive substring, so "Estaño (Sn)" etc. still hit.
# Order = priority: many showings list several metals (e.g. "Litio, Estaño,
# Tantalio"), and the first match wins — Li first so the strategic lithium
# showings aren't hidden under the far more common tin.
TARGET_COMMODITIES = {
    "Li": ["litio", "lepidolita", "espodumena", "petalita"],
    "W": ["wolframio", "volframio", "scheelita", "wolframita", "tungsteno"],
    "Sn": ["estaño", "casiterita", "estanno"],
    # Ta/Nb travel with Li in LCT pegmatites (coltán = (Ta,Nb) oxide) — the same
    # granite/pegmatite evidence layers model them, so they come near-free.
    "Ta": ["tántalo", "tantalio", "tantalo", "tantalita", "coltán", "coltan"],
    "Nb": ["niobio", "columbita", "pirocloro"],
    # Other granite-related metals sharing the same evidence (near-free, like Ta/Nb):
    # clean fits — vein/greisen/pegmatite hosted around granites.
    "U":  ["uranio", "uraninita", "pechblenda", "uranium"],
    "Mo": ["molibdeno", "molibdenita", "molybdenum"],
    "Be": ["berilio", "berilo", "beryllium"],
    "Bi": ["bismuto", "bismutina", "bismuth"],
    # Weaker fits — vein/fault hydrothermal, the granite model is only a proxy
    # (see PROXY_COMMODITIES → flagged "indicative" regardless of sample size).
    "Ba": ["barita", "baritina", "baryte", "barium"],
    "As": ["arsénico", "arsenico", "arsenopirita", "arsenic"],
    "Sb": ["antimonio", "estibina", "antimony", "stibnite"],
    # Base metals — a DIFFERENT mineral system (VMS / Iberian Pyrite Belt),
    # modelled on felsic-volcanic (not granite) evidence in the `iberia` region.
    "Cu": ["cobre", "calcopirita", "copper"],
    "Zn": ["cinc", "zinc", "esfalerita", "blenda"],
    "Pb": ["plomo", "galena", "lead"],
    "Ag": ["plata", "argentita", "silver"],
}

# Base-metal commodities used by the VMS (`iberia`) region — felsic-volcanic host.
VMS_COMMODITIES = ("Cu", "Zn", "Pb", "Ag")

# German arable-land price €/ha by NUTS1 (Bundesland). Germany doesn't report to
# Eurostat apri_lprc, so we fill the gap from Destatis "Kaufwerte für
# landwirtschaftliche Grundstücke" 2023 (official, published per state). Static —
# refresh annually. Only the Länder we drill are listed; others stay unpriced.
# Merged into the NUTS price lookup (nuts_price_polygons) as an 'est' prior.
DE_LAND_PRICE_EUR_HA = {
    "DED": 15606,   # Sachsen — the Erzgebirge, where cadastre_saxony drills
    "DEE": 23033,   # Sachsen-Anhalt
}

# All commodities that get their own per-metal heatmap + UI selector + buy-list.
COMMODITIES = ("Sn", "W", "Li", "Ta", "Nb", "U", "Mo", "Be", "Bi", "Ba", "As", "Sb")
# The belt-defining primaries whose occurrence density drives hotspot detection
# (the rest are selectable layers, but they shouldn't redraw the clusters).
HOTSPOT_COMMODITIES = ("Sn", "W", "Li")
# Host-mismatched: modelled on the granite evidence only as a proxy, so their
# per-metal model is always flagged "indicative" (not the sample-size flag).
PROXY_COMMODITIES = frozenset({"Ba", "As", "Sb"})

# Lithology DLO substrings (lower-case) treated as prospective granite/pegmatite
# host rock for Sn-W-Li (leucogranites, two-mica granites, aplite-pegmatite).
GRANITE_LITHOLOGIES = [
    "granito", "granitos", "granitoide", "granodiorita", "leucogranito",
    "monzogranito", "aplita", "pegmatita", "pórfido gran", "porfido gran",
    "pórfidos gran", "porfidos gran", "cuarzodiorita",
]

# Default municipios (Cáceres province, code 10) to pull Catastro parcels for.
# Chosen because they host real BDMIN Sn-W-Li showings (Garrovillas tin-tungsten
# district; "Mina Las Navas" Li-Sn-Ta at Cañaveral). Names must match the ATOM
# feed exactly — they go straight into the download URL. Kept to a handful: the
# demo's pure-Python zonal loop is O(parcels × cells).
CATASTRO_MUNICIPIOS = [
    ("10083", "GARROVILLAS DE ALCONETAR"),
    ("10142", "PEDROSO DE ACIM"),
    ("10148", "PIEDRAS ALBAS"),
    ("10046", "CAÑAVERAL"),
]

# Drop cadastral parcels smaller than this — removes dense urban plots and
# keeps the count (and runtime) sane; mineral land acquisition targets rústico.
PARCEL_MIN_AREA_HA = 2.0

# metres to buffer *active* mine workings into an exclusion/friction footprint
# (a parcel near an active working is contested / harder to acquire).
WORKING_BUFFER_M = 1_000.0

# Castilla y León provinces (upper-case, accent-free) — for these the fresher
# IDECyL regional concessions WFS is used instead of the MITECO national one.
CYL_PROVINCES = {
    "AVILA", "BURGOS", "LEON", "PALENCIA", "SALAMANCA",
    "SEGOVIA", "SORIA", "VALLADOLID", "ZAMORA",
}

# Composite parcel score weights. Score in [0, 1].
SCORE_WEIGHTS = {
    "prospectivity": 0.5,   # mean posterior probability over parcel
    "price": 0.3,           # cheapness vs. regional €/ha distribution (listed parcels)
    "friction": 0.2,        # 1 - permitting friction (protected overlap, slope proxy)
}
