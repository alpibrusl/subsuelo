import type { Feature } from "geojson";
import { pct } from "../data.ts";
import type {
  Drill, IndexParcel, Meta, ParcelProps, RegionData, RegionInfo, Target, Toggles,
} from "../types";
import ParcelDetail from "./ParcelDetail.tsx";
import SearchPanel from "./SearchPanel.tsx";
import MetalChips from "./MetalChips.tsx";

interface SidebarProps {
  regions: RegionInfo[];
  region: string;
  setRegion: (k: string) => void;
  data: RegionData | null;
  target: Target;
  setTarget: (t: Target) => void;
  activeHotspot: number | null;
  selectHotspot: (rank: number) => void;
  drill: Drill | null;
  toggles: Toggles;
  toggle: (name: keyof Toggles, val?: boolean) => void;
  selectParcel: (p: ParcelProps) => void;
  selectedParcel: ParcelProps | null;
  clearParcel: () => void;
  mode: "search" | "explore";
  setMode: (m: "search" | "explore") => void;
  pool: IndexParcel[];
  poolLoading: boolean;
  onPickParcel: (p: IndexParcel) => void;
}

// the descriptive subtitle is authored once, per region, in subsuelo/regions.py
// (Region.label) and travels through meta.json — no per-region copy to keep in
// sync here (a prior hardcoded version went stale when Europe's scope grew).
function subtitleFor(meta: Meta | null | undefined): string {
  if (!meta) return "loading…";
  return meta.region_description || meta.region_label || "mineral prospectivity";
}

export default function Sidebar(props: SidebarProps) {
  const { regions, region, setRegion, data, target, setTarget, activeHotspot, selectHotspot,
          drill, toggles, toggle, selectParcel, selectedParcel, clearParcel,
          mode, setMode, pool, poolLoading, onPickParcel } = props;
  const meta = data?.meta;
  const hasParcels = (meta?.n_parcels ?? 0) > 0;
  const hotspots = meta?.hotspots || [];
  const models = meta?.commodity_models || [];
  const primaryMetals = (models.length ? models.slice(0, 3).map((m) => m.key) : ["Sn", "W", "Li"]).join("·");
  const model = target ? models.find((m) => m.key === target) : null;
  const activeH = hotspots.find((h) => h.rank === activeHotspot);
  const drillParcels: Feature[] = drill?.parcels?.features || [];

  const stats: [string | number, string, boolean?][] = hasParcels
    ? [[meta!.n_parcels, "Parcels"],
       [meta!.n_occurrences || meta!.n_listed || 0, meta!.n_occurrences ? "Showings" : "Listed"],
       [meta!.score_max?.toFixed(3) ?? "—", "Top score"]]
    : [[meta?.n_occurrences || 0, "Showings"],
       [hotspots.length, "Hotspots"],
       [hotspots[0]?.provincia?.toLowerCase() || "—", "Top target", true]];

  let hsNote = "";
  if (activeH) hsNote = activeH.n_parcels
    ? `Hotspot #${activeH.rank} (${activeH.provincia.toLowerCase()}): ${activeH.n_parcels} parcels, ${activeH.n_claimed || 0} in a concession`
    : `Hotspot #${activeH.rank} — parcels not pre-computed`;

  return (
    <aside id="sidebar">
      <div className="sb-fixed">
        <header>
          <div className="sub">{subtitleFor(meta)}</div>
          {regions.length > 1 && (
            <label className="region-pick">Area
              <select value={region} onChange={(e) => setRegion(e.target.value)}>
                {regions.map((r) => <option key={r.key} value={r.key}>{r.label || r.key}</option>)}
              </select>
            </label>
          )}
        </header>

        <div className="mode-tabs">
          <button className={mode === "search" ? "on" : ""} onClick={() => setMode("search")}>Find land by budget</button>
          <button className={mode === "explore" ? "on" : ""} onClick={() => setMode("explore")}>Explore the map</button>
        </div>
      </div>

      <div className="sb-scroll">
        {mode === "search" && (
          <SearchPanel pool={pool} poolLoading={poolLoading} regions={regions} onPick={onPickParcel} />
        )}

        {mode === "explore" && (<>
        <div className="stat-bar">
          {stats.map(([n, l, cap], i) => (
            <div className="stat-item" key={i}><b className={cap ? "cap" : ""}>{n ?? "—"}</b><span>{l}</span></div>
          ))}
        </div>

        {!meta && <div className="loading"><span className="spinner" /> Loading map data…</div>}

        {/* STEP 1 — prospectivity */}
        <section className="step">
          <div className="step-h"><span className="num">1</span> Prospectivity</div>
          <p className="explain">The <b>heatmap</b> shades every point by how favourable its geology is for
            finding {primaryMetals} — a model trained on known deposits. <b>Brighter = more favourable.</b> Pick a
            metal to see its own model.</p>
          {models.length > 0 && <>
            <div className="t-label">Show the model for</div>
            <MetalChips
              options={[null, ...models.map((m) => m.key)]}
              value={target}
              onChange={setTarget}
            />
            <div className="note">{!target ? `Combined ${primaryMetals} model`
              : model?.reliable ? `Trained on ${model.n_train} ${target} showings`
              : model?.proxy ? `⚠ ${target}: granite model is only a proxy (different host) — indicative`
              : `⚠ only ${model?.n_train} ${target} showings — indicative, not reliable`}</div>
          </>}
          <label className="tgl"><input type="checkbox" checked={toggles.raster}
            onChange={(e) => toggle("raster", e.target.checked)} /> Prospectivity heatmap</label>
          <div className="scale"><span>low</span><div className="scalebar" /><span>high</span></div>
        </section>

        {/* STEP 2 — hotspots */}
        {hotspots.length > 0 && (
          <section className="step">
            <div className="step-h"><span className="num">2</span> Prospective areas</div>
            <p className="explain">The model's top-ranked targets. <b>Click one</b> to zoom in — where a
              cadastre exists it loads the land parcels there.</p>
            {drill?.loading
              ? <div className="note"><span className="spinner" /> Loading parcels…</div>
              : hsNote && <div className="note">{hsNote}</div>}
            <ul className="rows">
              {hotspots.map((h) => (
                <li key={h.rank} className={"hs-row" + (h.rank === activeHotspot ? " active" : "")}
                  onClick={() => selectHotspot(h.rank)}>
                  <span className="rk">{h.rank}</span>
                  <span><span className="hn">{(h.provincia || "—").toLowerCase()}</span>
                    <span className="hm"><span>{h.n_occ} showings</span>
                      <span>{Math.round(h.area_km2).toLocaleString()} km²</span>
                      <span>{h.n_parcels ? `${h.n_parcels} parcels` : h.top_commodity}</span></span></span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* STEP 3 — parcels */}
        {drillParcels.length > 0 && (
          <section className="step">
            <div className="step-h"><span className="num">3</span> Land parcels</div>
            <p className="explain">Cadastral parcels scored for acquisition — prospectivity, price, and how
              much is <b>already legally claimed</b>. <span className="muted">· hotspot #{drill!.rank}</span></p>
            {selectedParcel && <ParcelDetail p={selectedParcel} onClose={clearParcel} />}
            <ul className="rows">
              {[...drillParcels].sort((a, b) => (Number(b.properties?.score) || 0) - (Number(a.properties?.score) || 0)).slice(0, 25).map((f) => {
                const p = (f.properties || {}) as ParcelProps;
                return (
                  <li key={p.parcel_id} className={"pc-row" + (selectedParcel?.parcel_id === p.parcel_id ? " active" : "")}
                    onClick={() => selectParcel(p)}>
                    <div className="top"><span className="pid">{p.parcel_id}</span>
                      <span className="sc">{(p.score ?? 0).toFixed(3)}</span></div>
                    <div className="meta"><span>prosp {pct(p.prospectivity)}</span>
                      <span>{p.municipio}</span>{p.claimed_frac ? <span className="claimed">claimed</span> : null}</div>
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        {/* reference layers */}
        {(data?.occ || data?.workings) && (
          <details className="step">
            <summary>Reference layers</summary>
            {data?.occ && <label className="tgl"><input type="checkbox" checked={toggles.occ}
              onChange={(e) => toggle("occ", e.target.checked)} /> Mineral occurrences (real showings)</label>}
            {data?.workings && <label className="tgl"><input type="checkbox" checked={toggles.workings}
              onChange={(e) => toggle("workings", e.target.checked)} /> Mine workings</label>}
            {(drill?.concessions || data?.concessions) && <label className="tgl"><input type="checkbox" checked={toggles.conc}
              onChange={(e) => toggle("conc", e.target.checked)} /> Mining concessions (already claimed)</label>}
          </details>
        )}
        </>)}
      </div>
    </aside>
  );
}
