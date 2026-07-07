import { useMemo, useState } from "react";
import { scoreColor, searchParcels } from "../data.ts";
import type { IndexParcel, Metal, RegionInfo, SearchCriteria } from "../types";
import MetalChips from "./MetalChips.tsx";

// host-mismatched metals: the granite model is only a proxy (mirrors config.PROXY_COMMODITIES)
const PROXY = new Set<Metal>(["Ba", "As", "Sb"]);
const eur = (n: number) => "€" + Math.round(n).toLocaleString();
const eurK = (n: number) => n >= 1_000_000
  ? "€" + (n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1) + "M"
  : "€" + Math.round(n / 1000) + "k";

interface Props {
  pool: IndexParcel[];
  poolLoading: boolean;
  regions: RegionInfo[];
  onPick: (p: IndexParcel) => void;
}

export default function SearchPanel({ pool, poolLoading, regions, onPick }: Props) {
  const [c, setC] = useState<SearchCriteria>({
    metal: "Li", region: null, budgetTotal: 500_000, eurHaMax: null,
    minAreaHa: 2, excludeClaimed: true, pricedOnly: false,
  });
  const [moreOpen, setMoreOpen] = useState(false);
  const set = (patch: Partial<SearchCriteria>) => setC((p) => ({ ...p, ...patch }));

  // only offer metals that actually have drillable ground in the pool
  const metalOpts = useMemo<(Metal | null)[]>(() => {
    const present = new Set<string>();
    for (const p of pool)
      for (const k of Object.keys(p))
        if (k.startsWith("prosp_") && ((p[k as keyof IndexParcel] as number) ?? 0) > 0) present.add(k.slice(6));
    const COMMODITY_ORDER = ["Sn", "W", "Li", "Ta", "Nb", "U", "Mo", "Be", "Bi", "Ba", "As", "Sb", "Cu", "Zn", "Pb", "Ag"];
    return [null, ...COMMODITY_ORDER.filter((k) => present.has(k)) as Metal[]];
  }, [pool]);

  const res = useMemo(() => searchParcels(pool, c), [pool, c]);
  const shown = res.items.slice(0, 40);
  const moreFiltersActive = c.minAreaHa > 2 || !c.excludeClaimed || c.pricedOnly;

  return (
    <section className="search">
      <p className="explain">
        State what you want and a budget — get a ranked list of land you could actually acquire,
        best ground first. <b>Click a parcel</b> to open it on the map.
      </p>

      <div className="t-label">Target metal</div>
      <MetalChips options={metalOpts} value={c.metal} onChange={(m) => set({ metal: m })} noneLabel="Any" />
      {c.metal && PROXY.has(c.metal) && (
        <div className="note warn">⚠ {c.metal} ranking is indicative — the granite model is only a proxy for it.</div>
      )}

      {regions.length > 1 && (
        <>
          <div className="t-label">Area</div>
          <div className="chip-strip">
            <button className={"chip" + (c.region === null ? " on" : "")} onClick={() => set({ region: null })}>All</button>
            {regions.map((r) => (
              <button key={r.key} className={"chip" + (c.region === r.key ? " on" : "")}
                onClick={() => set({ region: r.key })}>
                {r.label?.split("—")[0]?.trim() || r.key}
              </button>
            ))}
          </div>
        </>
      )}

      <div className="filter-row">
        <span className="t-label" style={{ margin: 0 }}>Budget</span>
        <span className="filter-val">{eur(c.budgetTotal || 0)}</span>
      </div>
      <input type="range" min={50_000} max={5_000_000} step={50_000} value={c.budgetTotal || 0}
        onChange={(e) => set({ budgetTotal: Number(e.target.value) })} className="range" />

      <button className="more-toggle" onClick={() => setMoreOpen((o) => !o)}>
        <span>More filters{moreFiltersActive && !moreOpen ? " · active" : ""}</span>
        <span className={"chev" + (moreOpen ? " open" : "")}>▾</span>
      </button>
      {moreOpen && (
        <div className="more-filters">
          <div className="filter-row">
            <span className="t-label" style={{ margin: 0 }}>Min parcel size</span>
            <span className="filter-val muted">{c.minAreaHa} ha</span>
          </div>
          <input type="range" min={0} max={50} step={1} value={c.minAreaHa}
            onChange={(e) => set({ minAreaHa: Number(e.target.value) })} className="range" />
          <div className="filter-checks">
            <label className="tgl">
              <input type="checkbox" checked={c.excludeClaimed}
                onChange={(e) => set({ excludeClaimed: e.target.checked })} /> exclude claimed
            </label>
            <label className="tgl">
              <input type="checkbox" checked={c.pricedOnly}
                onChange={(e) => set({ pricedOnly: e.target.checked })} /> priced only
            </label>
          </div>
        </div>
      )}

      <div className="stat-bar">
        <div className="stat-item"><b>{res.matched.toLocaleString()}</b><span>Parcels match</span></div>
        <div className="stat-item"><b>{res.medianEurHa != null ? eurK(res.medianEurHa) : "—"}</b><span>Median €/ha</span></div>
        <div className="stat-item"><b>~{Math.round(res.affordableHa).toLocaleString()} ha</b><span>Budget buys ({res.affordableCount})</span></div>
      </div>

      {poolLoading && <div className="loading"><span className="spinner" /> Loading parcels…</div>}
      {!poolLoading && !res.matched && (
        <p className="explain">No parcels match — widen the budget or size, or clear a filter.</p>
      )}

      <div className="buy-list">
        {shown.map((p, i) => (
          <div key={p.region + p.parcel_id} className="buy-row" style={{ opacity: p.affordable ? 1 : 0.45 }}
            onClick={() => onPick(p)} title="Open on the map">
            <div className="rk">{i + 1}</div>
            <div className="body">
              <div className="top">
                <span className="pid">{p.parcel_id}</span>
                <span className={"claim " + (p.claimed ? "y" : "n")}>{p.claimed ? "claimed" : "open"}</span>
              </div>
              <div className="meta">
                {(p.municipio || "—") + (p.country ? `, ${p.country}` : "")} · {p.area_ha ?? "?"} ha
                {p.eur_ha != null
                  ? <> · {eur(p.eur_ha)}/ha{p.price_kind === "est" && <span className="muted"> est.</span>}{p.cost != null && <> · <b>{eurK(p.cost)}</b></>}</>
                  : <> · <span className="muted">no price</span></>}
              </div>
            </div>
            <div className="fit" title={`fit ${(p.rankScore * 100).toFixed(0)}%`}>
              <span style={{ background: scoreColor(p.rankScore) }} />
            </div>
          </div>
        ))}
        {res.items.length > shown.length && (
          <div className="more">+{(res.items.length - shown.length).toLocaleString()} more — narrow the search</div>
        )}
      </div>
    </section>
  );
}
