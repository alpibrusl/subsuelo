import { useEffect, useState, useCallback, useRef } from "react";
import { loadRegions, loadRegion, loadDrill, loadParcelIndex } from "./data.ts";
import type { Drill, IndexParcel, ParcelProps, RegionData, RegionInfo, Target, Toggles } from "./types";
import Sidebar from "./components/Sidebar.tsx";
import MapView from "./components/MapView.tsx";
import Intro from "./components/Intro.tsx";
import NavBar from "./components/NavBar.tsx";
import About from "./components/About.tsx";

const DEFAULT_TOGGLES: Toggles = {
  raster: true, occ: true, hotspots: true, workings: true, conc: true, hparcels: false, listed: false,
};

export default function App() {
  const [regions, setRegions] = useState<RegionInfo[]>([]);
  const [region, setRegionState] = useState<string>(
    () => new URLSearchParams(location.search).get("region") || "");
  const [data, setData] = useState<RegionData | null>(null);
  const [target, setTarget] = useState<Target>(null);
  const [activeHotspot, setActiveHotspot] = useState<number | null>(null);
  const [drill, setDrill] = useState<Drill | null>(null);
  const [toggles, setToggles] = useState<Toggles>(DEFAULT_TOGGLES);
  const [parcelFocus, setParcelFocus] = useState<{ id: string } | null>(null);
  const [selectedParcel, setSelectedParcel] = useState<ParcelProps | null>(null);
  const [mode, setMode] = useState<"search" | "explore">("search");
  // mobile only (CSS-gated — harmless no-op at desktop widths): which of the
  // overlapping sidebar/map panels is currently shown
  const [mobileView, setMobileView] = useState<"list" | "map">("list");
  const [pool, setPool] = useState<IndexParcel[]>([]);
  const [poolLoading, setPoolLoading] = useState<boolean>(true);
  const pendingNav = useRef<{ region: string; rank: number; parcelId: string;
    eurHa: number | null; priceKind: string } | null>(null);
  const [introOpen, setIntroOpen] = useState<boolean>(() => {
    try { return !localStorage.getItem("subsuelo_seen"); } catch { return true; }
  });
  const [aboutOpen, setAboutOpen] = useState<boolean>(false);
  // metal + hotspot from the shared URL, applied once after the region loads
  const initialParams = useRef({
    metal: (() => {
      const m = new URLSearchParams(location.search).get("metal");
      return (["Sn", "W", "Li"].includes(m || "") ? m : null) as Target;
    })(),
    hotspot: Number(new URLSearchParams(location.search).get("hotspot")) || null,
  });

  // load the region registry, pick a default region
  useEffect(() => {
    loadRegions().then((list) => {
      setRegions(list);
      if (!region && list.length) setRegionState(list[0].key);
    });
  }, []); // eslint-disable-line

  // load + merge every region's parcel index once (the cross-region buy-list pool)
  useEffect(() => {
    if (!regions.length) return;
    setPoolLoading(true);
    loadParcelIndex(regions).then((p) => { setPool(p); setPoolLoading(false); });
  }, [regions]);

  // (re)load a region's data whenever the region changes
  useEffect(() => {
    if (!region) return;
    setData(null); setTarget(null); setActiveHotspot(null); setDrill(null);
    setToggles(DEFAULT_TOGGLES);
    loadRegion(region).then(setData);
  }, [region]);

  // once a region's data is in, apply any metal/hotspot from the shared URL
  useEffect(() => {
    if (!data?.meta) return;
    const p = initialParams.current;
    if (p.metal) { setTarget(p.metal); p.metal = null; }
    if (p.hotspot) { selectHotspot(p.hotspot); p.hotspot = null; }
  }, [data]); // eslint-disable-line

  // keep the URL in sync so the current view is shareable
  useEffect(() => {
    if (!region) return;
    const u = new URL(location.href);
    u.searchParams.set("region", region);
    target ? u.searchParams.set("metal", target) : u.searchParams.delete("metal");
    activeHotspot ? u.searchParams.set("hotspot", String(activeHotspot)) : u.searchParams.delete("hotspot");
    history.replaceState(null, "", u);
  }, [region, target, activeHotspot]);

  const setRegion = useCallback((k: string) => setRegionState(k), []);
  const toggle = useCallback((name: keyof Toggles, val?: boolean) =>
    setToggles((t) => ({ ...t, [name]: val ?? !t[name] })), []);

  const selectHotspot = useCallback((rank: number) => {
    setActiveHotspot(rank);
    setMobileView("map");   // clicking a hotspot should show its result on the map
    const h = (data?.meta?.hotspots || []).find((x) => x.rank === rank);
    if (!h || !h.n_parcels) { setDrill({ rank, parcels: null, concessions: null }); return; }
    setDrill({ rank, loading: true });
    loadDrill(region, rank).then((d) => {
      setDrill(d);
      setToggles((t) => ({ ...t, hparcels: true }));
    });
  }, [region, data]);

  const selectParcel = useCallback((p: ParcelProps) => {
    setSelectedParcel(p);
    setParcelFocus({ id: p.parcel_id });
    setMobileView("map");   // clicking a parcel should show it on the map
  }, []);

  // clear the selected parcel whenever the region or drilled hotspot changes
  useEffect(() => { setSelectedParcel(null); }, [region, drill?.rank]);

  // pick a parcel from the cross-region buy-list → switch region + drill + focus it
  const onPickParcel = useCallback((p: IndexParcel) => {
    pendingNav.current = { region: p.region, rank: p.rank, parcelId: p.parcel_id,
      eurHa: p.eur_ha, priceKind: p.price_kind };
    setMode("explore");
    if (p.region !== region) setRegionState(p.region);
    else selectHotspot(p.rank);
  }, [region, selectHotspot]);

  // once the target region's data is loaded, drill the pending hotspot
  useEffect(() => {
    const nav = pendingNav.current;
    if (nav && data?.meta && nav.region === region && activeHotspot !== nav.rank) selectHotspot(nav.rank);
  }, [data]); // eslint-disable-line

  // once the pending hotspot's parcels arrive, select the picked parcel
  useEffect(() => {
    const nav = pendingNav.current;
    if (!nav || !drill || drill.rank !== nav.rank || !drill.parcels) return;
    const f = drill.parcels.features.find((ft) => String(ft.properties?.parcel_id) === nav.parcelId);
    if (f?.properties) {
      const props = { ...f.properties } as ParcelProps;
      // carry the buy-list's (possibly estimated) price onto the detail card,
      // which is drilled from a geojson that lacks it (Spain/Germany/Czechia)
      if (props.eur_ha_effective == null && nav.eurHa != null) {
        props.eur_ha_effective = nav.eurHa; props.price_kind = nav.priceKind;
      }
      selectParcel(props);
    }
    pendingNav.current = null;
  }, [drill]); // eslint-disable-line

  const closeIntro = () => {
    setIntroOpen(false);
    try { localStorage.setItem("subsuelo_seen", "1"); } catch { /* ignore */ }
  };

  return (
    <>
      {introOpen && <Intro onClose={closeIntro} />}
      {aboutOpen && <About onClose={() => setAboutOpen(false)} />}
      <NavBar onAbout={() => setAboutOpen(true)} onGuide={() => setIntroOpen(true)} />
      <div id="app" className={mobileView === "map" ? "show-map" : ""}>
        <Sidebar
          regions={regions} region={region} setRegion={setRegion}
          data={data} target={target} setTarget={setTarget}
          activeHotspot={activeHotspot} selectHotspot={selectHotspot}
          drill={drill} toggles={toggles} toggle={toggle}
          selectParcel={selectParcel}
          selectedParcel={selectedParcel}
          clearParcel={() => setSelectedParcel(null)}
          mode={mode} setMode={setMode}
          pool={pool} poolLoading={poolLoading} onPickParcel={onPickParcel}
        />
        <MapView
          region={region} data={data} target={target}
          drill={drill} toggles={toggles} parcelFocus={parcelFocus}
          selectHotspot={selectHotspot} selectParcel={selectParcel}
        />
      </div>
      <button className="mobile-toggle" onClick={() => setMobileView((v) => (v === "map" ? "list" : "map"))}>
        {mobileView === "map" ? "Show list" : "Show map"}
      </button>
    </>
  );
}
