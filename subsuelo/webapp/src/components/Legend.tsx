import { useState, type ReactNode } from "react";
import { cinfo } from "../data.ts";
import type { ActiveLayers } from "../types";

export default function Legend({ active, metals = ["Sn", "W", "Li"] }:
  { active: ActiveLayers; metals?: string[] }) {
  const [open, setOpen] = useState(true);
  const label = metals.join("·");
  const rows: [string, ReactNode, ReactNode][] = [];
  rows.push(["Prospectivity", `favourability of the ground for ${label} — brighter = better`,
    <span className="sw" style={{ background: "linear-gradient(90deg,#0f1419,#bc3754,#fcffa4)" }} />]);
  if (active.occ) rows.push(["Mineral occurrence",
    <>a real known showing — {metals.map((m, i) => (
      <span key={m}>{i > 0 && " · "}<b style={{ color: cinfo(m).color }}>{m}</b></span>))}</>,
    <span className="sw dot" style={{ background: cinfo(metals[0] || "W").color }} />]);
  if (active.hotspots) rows.push(["Hotspot", "a top-ranked prospective area (numbered by rank)",
    <span className="sw" style={{ background: "transparent", border: "2px solid var(--gold)" }} />]);
  if (active.parcels || active.hparcels) rows.push(["Parcel score", "land ranked for acquisition — purple low, yellow high",
    <span className="sw" style={{ background: "linear-gradient(90deg,#440154,#21918c,#fde725)" }} />]);
  if (active.conc) rows.push(["Mining concession", "ground already legally claimed (red = granted)",
    <span className="sw" style={{ background: "rgba(255,90,90,.35)", border: "1.5px solid #ff5a5a" }} />]);

  return (
    <div className="map-legend">
      <div className="ml-head" onClick={() => setOpen((o) => !o)}>
        <span>Legend — what am I looking at?</span><span>{open ? "▾" : "▸"}</span>
      </div>
      {open && rows.map(([title, desc, sw], i) => (
        <div className="lg-row" key={i}>{sw}<span><b>{title}</b><small>{desc}</small></span></div>
      ))}
    </div>
  );
}
