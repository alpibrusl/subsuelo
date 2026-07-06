import { useMemo, useState } from "react";
import { COMMODITY, cinfo, scoreColor, searchParcels } from "../data.ts";
import type { IndexParcel, Metal, RegionInfo, SearchCriteria } from "../types";

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
  const set = (patch: Partial<SearchCriteria>) => setC((p) => ({ ...p, ...patch }));

  // only offer metals that actually have drillable ground in the pool
  const metalOpts = useMemo<(Metal | null)[]>(() => {
    const present = new Set<string>();
    for (const p of pool)
      for (const k of Object.keys(p))
        if (k.startsWith("prosp_") && ((p[k as keyof IndexParcel] as number) ?? 0) > 0) present.add(k.slice(6));
    return [null, ...(Object.keys(COMMODITY).filter((k) => k !== "other" && present.has(k)) as Metal[])];
  }, [pool]);

  const res = useMemo(() => searchParcels(pool, c), [pool, c]);
  const shown = res.items.slice(0, 40);

  return (
    <section className="step search">
      <p className="explain" style={{ marginTop: 0 }}>
        State what you want and a budget — get a ranked list of land you could actually acquire,
        best ground first. <b>Click a parcel</b> to open it on the map.
      </p>

      {/* intent: metal */}
      <div className="t-label">Target metal</div>
      <div className="t-btns" style={{ flexWrap: "wrap", gap: 6 }}>
        {metalOpts.map((m) => (
          <button key={m ?? "any"} className={c.metal === m ? "on" : ""}
            onClick={() => set({ metal: m })} style={{ flex: "0 0 auto", padding: "6px 12px" }}>
            {m ? <><span className="dot" style={{ background: cinfo(m).color }} />{m}</> : "Any"}
          </button>
        ))}
      </div>
      {c.metal && PROXY.has(c.metal) && (
        <div className="note" style={{ marginTop: 6 }}>⚠ {c.metal} ranking is indicative — the granite model is only a proxy for it.</div>
      )}

      {/* region */}
      {regions.length > 1 && (
        <>
          <div className="t-label" style={{ marginTop: 12 }}>Area</div>
          <div className="t-btns" style={{ flexWrap: "wrap", gap: 6 }}>
            <button className={c.region === null ? "on" : ""} onClick={() => set({ region: null })}
              style={{ flex: "0 0 auto", padding: "6px 12px" }}>All</button>
            {regions.map((r) => (
              <button key={r.key} className={c.region === r.key ? "on" : ""}
                onClick={() => set({ region: r.key })} style={{ flex: "0 0 auto", padding: "6px 12px" }}>
                {r.label?.split("—")[0]?.trim() || r.key}
              </button>
            ))}
          </div>
        </>
      )}

      {/* budget */}
      <div className="t-label" style={{ marginTop: 14 }}>
        Budget <span style={{ color: "var(--accent)", float: "right" }}>{eur(c.budgetTotal || 0)}</span>
      </div>
      <input type="range" min={50_000} max={5_000_000} step={50_000} value={c.budgetTotal || 0}
        onChange={(e) => set({ budgetTotal: Number(e.target.value) })}
        style={{ width: "100%", accentColor: "var(--accent)" }} />

      {/* size + toggles */}
      <div className="t-label" style={{ marginTop: 10 }}>
        Min parcel size <span style={{ color: "var(--muted)", float: "right" }}>{c.minAreaHa} ha</span>
      </div>
      <input type="range" min={0} max={50} step={1} value={c.minAreaHa}
        onChange={(e) => set({ minAreaHa: Number(e.target.value) })}
        style={{ width: "100%", accentColor: "var(--accent)" }} />

      <div style={{ display: "flex", gap: 14, marginTop: 10 }}>
        <label className="tgl" style={{ margin: 0 }}>
          <input type="checkbox" checked={c.excludeClaimed}
            onChange={(e) => set({ excludeClaimed: e.target.checked })} /> exclude claimed
        </label>
        <label className="tgl" style={{ margin: 0 }}>
          <input type="checkbox" checked={c.pricedOnly}
            onChange={(e) => set({ pricedOnly: e.target.checked })} /> priced only
        </label>
      </div>

      {/* summary */}
      <div className="search-stats">
        <div><div className="n">{res.matched.toLocaleString()}</div><div className="l">Parcels match</div></div>
        <div><div className="n">{res.medianEurHa != null ? eurK(res.medianEurHa) : "—"}</div><div className="l">Median €/ha</div></div>
        <div><div className="n">~{Math.round(res.affordableHa).toLocaleString()}<span className="u"> ha</span></div>
          <div className="l">Budget buys ({res.affordableCount})</div></div>
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
                  ? <> · {eur(p.eur_ha)}/ha{p.price_kind === "est" && <span style={{ color: "var(--muted)" }}> est.</span>}{p.cost != null && <> · <b>{eurK(p.cost)}</b></>}</>
                  : <> · <span style={{ color: "var(--muted)" }}>no price</span></>}
              </div>
            </div>
            <div className="fit">
              <span className="dot" style={{ background: scoreColor(p.rankScore) }} />
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
