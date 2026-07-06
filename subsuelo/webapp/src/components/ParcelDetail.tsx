import { pct } from "../data.ts";
import type { ParcelProps } from "../types";

export default function ParcelDetail({ p, onClose }: { p: ParcelProps; onClose: () => void }) {
  const eur = p.eur_ha_effective;
  const rows: [string, string | null, boolean?][] = [
    ["Prospectivity", pct(p.prospectivity)],
    ["In concession", p.claimed_frac ? pct(p.claimed_frac) : null, true],
    ["€/ha", eur != null ? "€" + Math.round(eur).toLocaleString() + (p.price_kind === "est" ? " est." : "") : null],
    ["Municipio", p.municipio || "—"],
    ["Area", p.area_ha != null ? Math.round(p.area_ha).toLocaleString() + " ha" : "—"],
  ];
  return (
    <div className="parcel-detail">
      <div className="pd-head"><b>{p.parcel_id}</b>
        <button onClick={onClose} title="Close">×</button></div>
      <div className="pd-score">{(p.score ?? 0).toFixed(3)} <small>composite score</small></div>
      {rows.filter(([, v]) => v != null).map(([k, v, warn]) => (
        <div className="pd-row" key={k}><span>{k}</span>
          <span className={warn ? "claimed" : ""}>{v}</span></div>
      ))}
    </div>
  );
}
