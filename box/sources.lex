# sources.lex — the licence classification for every host subsuelo fetches.
#
# This is the single place a source's terms are declared. Adding an ingestor
# without adding it here means `parse_licence` returns Unknown and the
# attribution gate refuses to publish — which is the intended failure mode.
#
# Each entry mirrors what ingest/live.py fetches. The licence strings are the
# ones the providers themselves publish; where a provider's terms are not
# clearly stated, the entry is deliberately left Unknown rather than guessed,
# and shows up as work to do rather than as a silent assumption.

import "std.list" as list

import "./licence" as lic

# ---------------------------------------------------------------------------
# Geoscience
# ---------------------------------------------------------------------------
fn geoscience_sources() -> List[lic.Source] {
  [{ tag: "igme_geology", host: "mapas.igme.es", licence: lic.CCBy, attribution: "© Instituto Geológico y Minero de España (IGME-CSIC)" }, { tag: "egdi", host: "maps.europe-geology.eu", licence: lic.CCBy, attribution: "© EuroGeoSurveys / European Geological Data Infrastructure" }, { tag: "minetur_mines", host: "geoportal.minetur.gob.es", licence: lic.Unknown, attribution: "© Ministerio para la Transición Ecológica (MITECO)" }, { tag: "idecyl_mining", host: "idecyl.jcyl.es", licence: lic.CCBy, attribution: "© Junta de Castilla y León — IDECyL" }, { tag: "mapama_natura", host: "wms.mapama.gob.es", licence: lic.CCBy, attribution: "© MITECO — Banco de Datos de la Naturaleza" }]
}

# ---------------------------------------------------------------------------
# Cadastres
# ---------------------------------------------------------------------------
fn cadastre_sources() -> List[lic.Source] {
  [{ tag: "catastro_es_ovc", host: "ovc.catastro.meh.es", licence: lic.CCBy, attribution: "Dirección General del Catastro (España)" }, { tag: "catastro_es", host: "www.catastro.hacienda.gob.es", licence: lic.CCBy, attribution: "Dirección General del Catastro (España)" }, { tag: "ign_fr_parcels", host: "data.geopf.fr", licence: lic.EtalabOpen, attribution: "© IGN — Géoplateforme, Licence Ouverte / Etalab 2.0" }, { tag: "cuzk_cz", host: "services.cuzk.gov.cz", licence: lic.CCBy, attribution: "© ČÚZK — Český úřad zeměměřický a katastrální" }, { tag: "geosn_sachsen", host: "geodienste.sachsen.de", licence: lic.DlDeBy20, attribution: "© GeoSN, dl-de/by-2-0" }, { tag: "geoproxy_th", host: "www.geoproxy.geoportal-th.de", licence: lic.DlDeZero, attribution: "© TLBG Thüringen, dl-de/zero-2-0" }, { tag: "wfs_nrw", host: "www.wfs.nrw.de", licence: lic.DlDeZero, attribution: "© Geobasis NRW, dl-de/zero-2-0" }, { tag: "pdok_nl", host: "service.pdok.nl", licence: lic.CC0, attribution: "© Kadaster / PDOK (CC0)" }, { tag: "dgt_pt", host: "snicws.dgterritorio.gov.pt", licence: lic.Unknown, attribution: "© Direção-Geral do Território (Portugal)" }]
}

# ---------------------------------------------------------------------------
# Prices and reference data
# ---------------------------------------------------------------------------
fn price_sources() -> List[lic.Source] {
  [{ tag: "dvf_fr", host: "files.data.gouv.fr", licence: lic.EtalabOpen, attribution: "DVF — data.gouv.fr, Licence Ouverte / Etalab 2.0" }, { tag: "eurostat", host: "ec.europa.eu", licence: lic.CCBy, attribution: "© European Union, Eurostat" }, { tag: "gisco", host: "gisco-services.ec.europa.eu", licence: lic.CCBy, attribution: "© EuroGeographics for the administrative boundaries" }, { tag: "naturalearth", host: "raw.githubusercontent.com", licence: lic.CC0, attribution: "Natural Earth (public domain)" }, { tag: "idealista", host: "api.idealista.com", licence: lic.Restricted, attribution: "idealista (commercial API — not redistributable)" }]
}

# Every declared source. The gate resolves a provenance host against this.
fn all_sources() -> List[lic.Source] {
  list.concat(geoscience_sources(), list.concat(cadastre_sources(), price_sources()))
}

# Look up a host. An unlisted host yields an Unknown-licensed placeholder,
# which blocks publication — adding an ingestor without declaring its terms
# fails the build rather than passing silently.
fn source_for_host(host :: Str) -> lic.Source {
  let hits := list.filter(all_sources(), fn (s :: lic.Source) -> Bool {
    s.host == host
  })
  match list.head(hits) {
    Some(s) => s,
    None => { tag: "undeclared", host: host, licence: lic.Unknown, attribution: "UNDECLARED SOURCE" },
  }
}

