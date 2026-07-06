// data access + shared visual constants. Region assets live under public/
// (symlinked to ../out/web) at regions/<key>/…
import type { FeatureCollection } from "geojson";
import type {
  BuyListItem, Drill, IndexParcel, Metal, RegionData, RegionInfo,
  SearchCriteria, Target,
} from "./types";

export const COMMODITY: Record<string, { color: string; label: string }> = {
  Li: { color: "#e15aa8", label: "Li — lithium" },
  Sn: { color: "#4fd1c5", label: "Sn — tin" },
  W: { color: "#f6c454", label: "W — tungsten" },
  Ta: { color: "#a78bfa", label: "Ta — tantalum" },
  Nb: { color: "#fb923c", label: "Nb — niobium" },
  U: { color: "#86efac", label: "U — uranium" },
  Mo: { color: "#94a3b8", label: "Mo — molybdenum" },
  Be: { color: "#f0abfc", label: "Be — beryllium" },
  Bi: { color: "#fda4af", label: "Bi — bismuth" },
  Ba: { color: "#bef264", label: "Ba — baryte" },
  As: { color: "#d6d3d1", label: "As — arsenic" },
  Sb: { color: "#67e8f9", label: "Sb — antimony" },
  Cu: { color: "#fb923c", label: "Cu — copper" },
  Zn: { color: "#a1a1aa", label: "Zn — zinc" },
  Pb: { color: "#64748b", label: "Pb — lead" },
  Ag: { color: "#e2e8f0", label: "Ag — silver" },
  other: { color: "#8b98a5", label: "other" },
};
export const cinfo = (c: string | Metal) => COMMODITY[c] || COMMODITY.other;

const VIRIDIS = [[68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37]];
export function scoreColor(t: number): string {
  t = Math.max(0, Math.min(1, t || 0));
  const x = t * (VIRIDIS.length - 1), i = Math.floor(x), f = x - i;
  const a = VIRIDIS[i], b = VIRIDIS[Math.min(i + 1, VIRIDIS.length - 1)];
  const c = a.map((v, k) => Math.round(v + (b[k] - v) * f));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

export const pct = (n: number | null | undefined) =>
  n == null ? "—" : (n * 100).toFixed(0) + "%";

const base = (region: string) => `regions/${region}/`;

async function getJSON<T>(url: string): Promise<T | null> {
  // vite serves index.html (200) for missing files, so guard on content-type
  // and parse errors — a missing region asset must resolve to null, not throw.
  try {
    const r = await fetch(url);
    if (!r.ok) return null;
    if ((r.headers.get("content-type") || "").includes("text/html")) return null;
    return JSON.parse(await r.text()) as T;
  } catch {
    return null;
  }
}

export async function loadRegions(): Promise<RegionInfo[]> {
  return (await getJSON<RegionInfo[]>("regions.json")) || [];
}

export async function loadRegion(region: string): Promise<RegionData> {
  const b = base(region);
  const [meta, occ, hotspots, workings, concessions, parcels] = await Promise.all([
    getJSON<RegionData["meta"]>(b + "meta.json"),
    getJSON<FeatureCollection>(b + "occurrences.geojson"),
    getJSON<FeatureCollection>(b + "hotspots.geojson"),
    getJSON<FeatureCollection>(b + "mining_workings.geojson"),
    getJSON<FeatureCollection>(b + "mining_concessions.geojson"),
    getJSON<FeatureCollection>(b + "parcels.geojson"),
  ]);
  return { meta, occ, hotspots, workings, concessions, parcels };
}

export async function loadDrill(region: string, rank: number): Promise<Drill> {
  const b = base(region);
  const [parcels, concessions] = await Promise.all([
    getJSON<FeatureCollection>(b + `hotspot_parcels_${rank}.geojson`),
    getJSON<FeatureCollection>(b + `hotspot_concessions_${rank}.geojson`),
  ]);
  return { rank, parcels, concessions };
}

export const rasterUrl = (region: string, target: Target) =>
  base(region) + (target ? `prospectivity_${target}.png` : "prospectivity.png");

// --- cross-hotspot budget search -------------------------------------------

/** load + merge every region's flat parcel index into one buy-list pool */
export async function loadParcelIndex(regions: RegionInfo[]): Promise<IndexParcel[]> {
  const lists = await Promise.all(
    regions.map((r) => getJSON<IndexParcel[]>(base(r.key) + "parcels_index.json")));
  return lists.flatMap((l, i) => (l || []).map((p) => ({ ...p, region: p.region || regions[i].key })));
}

const median = (xs: number[]) => xs.length ? [...xs].sort((a, b) => a - b)[Math.floor(xs.length / 2)] : 0;
const minmax = (xs: number[]) => xs.reduce(
  (a, v) => [Math.min(a[0], v), Math.max(a[1], v)], [Infinity, -Infinity]);

/** filter + rank the parcel pool for a search, applying total-budget affordability.
 *  Metal ranking uses the per-metal posterior (`prosp_<metal>`) — a tiny absolute
 *  probability, so we rank RELATIVELY (keep above-median ground for that metal and
 *  normalize to 0–1 for display) rather than thresholding an absolute value. */
export function searchParcels(pool: IndexParcel[], c: SearchCriteria): {
  items: BuyListItem[]; matched: number; medianEurHa: number | null;
  affordableHa: number; affordableCount: number;
} {
  const key = c.metal ? (`prosp_${c.metal}` as keyof IndexParcel) : null;
  const rawOf = (p: IndexParcel) => ((key ? (p[key] as number | null) : p.score) ?? 0);

  let rows = pool.filter((p) => {
    if (c.region && p.region !== c.region) return false;
    if (c.excludeClaimed && p.claimed) return false;
    if ((p.area_ha ?? 0) < c.minAreaHa) return false;
    if (c.eurHaMax != null && (p.eur_ha == null || p.eur_ha > c.eurHaMax)) return false;
    if (c.pricedOnly && p.eur_ha == null) return false;
    return true;
  });

  // metal filter: keep the above-median ground for that metal (a real subset)
  if (key) {
    const med = median(rows.map(rawOf).filter((v) => v > 0));
    rows = rows.filter((p) => rawOf(p) >= med && rawOf(p) > 0);
  }
  rows.sort((a, b) => rawOf(b) - rawOf(a));

  const [mn, mx] = minmax(rows.map(rawOf));
  const norm = (v: number) => (mx > mn ? (v - mn) / (mx - mn) : 1);

  // total-budget mode: walk the ranked list, mark parcels affordable until spent
  let remaining = c.budgetTotal ?? Infinity;
  let affordableHa = 0, affordableCount = 0;
  const items: BuyListItem[] = rows.map((p) => {
    const cost = p.eur_ha != null && p.area_ha != null ? Math.round(p.eur_ha * p.area_ha) : null;
    let affordable = c.budgetTotal == null;
    if (c.budgetTotal != null && cost != null && cost <= remaining) {
      affordable = true; remaining -= cost; affordableHa += p.area_ha || 0; affordableCount += 1;
    }
    return { ...p, rankScore: norm(rawOf(p)), cost, affordable };
  });

  const priced = rows.map((p) => p.eur_ha).filter((v): v is number => v != null);
  const medianEurHa = priced.length ? median(priced) : null;
  return { items, matched: rows.length, medianEurHa, affordableHa, affordableCount };
}
