import type { FeatureCollection } from "geojson";

export type Metal = "Sn" | "W" | "Li" | "Ta" | "Nb"
  | "U" | "Mo" | "Be" | "Bi" | "Ba" | "As" | "Sb"
  | "Cu" | "Zn" | "Pb" | "Ag";
export type Target = Metal | null;

export interface RegionInfo {
  key: string;
  label: string;
  n_occurrences: number;
  n_hotspots: number;
}

export interface CommodityModel {
  key: Metal;
  n_train: number;
  reliable: boolean;
  proxy?: boolean;
  raster: string;
  score_min?: number;
  score_max?: number;
}

export interface Hotspot {
  rank: number;
  provincia: string;
  area_km2: number;
  n_occ: number;
  mean_post: number;
  top_commodity: string;
  municipios: string;
  n_parcels: number;
  n_claimed: number;
  n_conc: number;
}

export interface Meta {
  raster_bounds: [[number, number], [number, number]];
  center: [number, number];
  region?: string;
  region_label?: string;
  region_description?: string;
  n_parcels: number;
  n_occurrences: number;
  n_listed: number;
  has_price: boolean;
  score_min?: number;
  score_max?: number;
  commodity_models: CommodityModel[];
  hotspots: Hotspot[];
  commodities?: Record<string, number>;
  n_workings?: number;
  n_concessions?: number;
}

export interface RegionData {
  meta: Meta | null;
  occ: FeatureCollection | null;
  hotspots: FeatureCollection | null;
  workings: FeatureCollection | null;
  concessions: FeatureCollection | null;
  parcels: FeatureCollection | null;
}

export interface Drill {
  rank: number;
  parcels?: FeatureCollection | null;
  concessions?: FeatureCollection | null;
  loading?: boolean;
}

export interface ParcelProps {
  parcel_id: string;
  score: number;
  prospectivity: number;
  claimed_frac?: number;
  municipio?: string;
  area_ha?: number;
  eur_ha_effective?: number | null;
  [k: string]: unknown;
}

/** one parcel in the flat cross-hotspot buy-list index (parcels_index.json) */
export interface IndexParcel {
  parcel_id: string;
  region: string;
  rank: number;
  metal: string | null;
  country: string | null;
  municipio: string;
  area_ha: number | null;
  eur_ha: number | null;
  price_kind: "real" | "est" | "na";
  prospectivity: number | null;
  score: number | null;
  claimed: boolean;
  lon: number;
  lat: number;
  prosp_Sn?: number | null;
  prosp_W?: number | null;
  prosp_Li?: number | null;
  prosp_Ta?: number | null;
  prosp_Nb?: number | null;
  prosp_U?: number | null;
  prosp_Mo?: number | null;
  prosp_Be?: number | null;
  prosp_Bi?: number | null;
  prosp_Ba?: number | null;
  prosp_As?: number | null;
  prosp_Sb?: number | null;
  prosp_Cu?: number | null;
  prosp_Zn?: number | null;
  prosp_Pb?: number | null;
  prosp_Ag?: number | null;
}

/** search inputs for the budget/intent funnel */
export interface SearchCriteria {
  metal: Metal | null;      // null = any metal (rank by composite score)
  region: string | null;    // null = all regions
  budgetTotal: number | null;   // € — total-budget affordability mode
  eurHaMax: number | null;      // €/ha ceiling filter
  minAreaHa: number;
  excludeClaimed: boolean;
  pricedOnly: boolean;      // only parcels with a real price
}

/** a ranked buy-list result: the parcel + whether the running budget affords it */
export interface BuyListItem extends IndexParcel {
  rankScore: number;        // value it was ranked by (prosp_<metal> or composite)
  cost: number | null;      // eur_ha × area, if priced
  affordable: boolean;      // within the running total budget
}

export interface Toggles {
  raster: boolean;
  occ: boolean;
  hotspots: boolean;
  workings: boolean;
  conc: boolean;
  hparcels: boolean;
  listed: boolean;
}

/** which layers are currently on the map (drives the legend) */
export type ActiveLayers = Partial<Record<
  "raster" | "occ" | "hotspots" | "parcels" | "hparcels" | "conc" | "workings", boolean>>;
