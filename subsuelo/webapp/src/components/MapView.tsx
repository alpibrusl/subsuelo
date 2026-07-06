import { useEffect, useRef, useState } from "react";
import { MapContainer, TileLayer, useMap } from "react-leaflet";
import L from "leaflet";
import type { Feature, FeatureCollection } from "geojson";
import { cinfo, scoreColor, pct, rasterUrl } from "../data.ts";
import type { ActiveLayers, Drill, ParcelProps, RegionData, Target, Toggles } from "../types";
import Legend from "./Legend.tsx";

const TARGET_METALS = ["Sn", "W", "Li"];
const popup = (html: string) => `<div class="pop">${html}</div>`;
type Props = {
  region: string;
  data: RegionData | null;
  target: Target;
  drill: Drill | null;
  toggles: Toggles;
  parcelFocus: { id: string } | null;
  selectHotspot: (rank: number) => void;
  selectParcel: (p: ParcelProps) => void;
};

function fit(map: L.Map, bounds: L.LatLngBounds | undefined, maxZoom = 12) {
  if (!bounds || !bounds.isValid()) return;
  if (map.getContainer().clientHeight < 50) { setTimeout(() => fit(map, bounds, maxZoom), 200); return; }
  map.invalidateSize();
  const z = Math.min(map.getBoundsZoom(bounds, false, L.point(20, 20)), maxZoom);
  map.setView(bounds.getCenter(), z, { animate: false });
}

// --- layer builders (plain Leaflet) ---
function occLayer(gj: FeatureCollection): L.GeoJSON {
  return L.geoJSON(gj, {
    pointToLayer: (f, ll) => {
      const c = (f.properties as any).commodity, big = TARGET_METALS.includes(c);
      return L.circleMarker(ll, { radius: big ? 6 : 4, color: "#0f1419", weight: 1,
        fillColor: cinfo(c).color, fillOpacity: big ? 0.95 : 0.5 });
    },
    onEachFeature: (f, layer) => {
      const p = f.properties as any;
      layer.bindPopup(popup(`<h3>${p.name || "(unnamed showing)"}</h3><table>
        <tr><td class="k">Substance</td><td><b>${p.sustancia || "—"}</b></td></tr>
        <tr><td class="k">Region</td><td>${p.municipio || "—"}</td></tr></table>`));
    },
  });
}

function hotspotLayer(gj: FeatureCollection, onClick: (rank: number) => void): [L.LayerGroup, Record<number, L.Layer>] {
  const grp = L.layerGroup(); const byId: Record<number, L.Layer> = {};
  const polys = L.geoJSON(gj, {
    style: { color: "#f6c454", weight: 1.6, fillColor: "#f6c454", fillOpacity: 0.08 },
    onEachFeature: (f, layer) => {
      const p = f.properties as any; byId[p.rank] = layer;
      layer.on("click", () => onClick(p.rank));
      layer.bindPopup(popup(`<h3>Hotspot #${p.rank} — ${(p.provincia || "").toLowerCase()}</h3><table>
        <tr><td class="k">Showings</td><td><b>${p.n_occ}</b></td></tr>
        <tr><td class="k">Area</td><td>${Math.round(p.area_km2).toLocaleString()} km²</td></tr>
        <tr><td class="k">Lead metal</td><td>${p.top_commodity || "—"}</td></tr></table>`));
    },
  });
  polys.addTo(grp);
  polys.eachLayer((layer) => {
    const p = (layer as any).feature.properties;
    L.marker((layer as L.GeoJSON & { getBounds(): L.LatLngBounds }).getBounds().getCenter(), {
      icon: L.divIcon({ className: "hs-rank",
        html: `<span style="background:#f6c454;color:#1a222c;font-weight:700;font-size:11px;border-radius:50%;width:18px;height:18px;display:flex;align-items:center;justify-content:center;box-shadow:0 0 4px #0f1419">${p.rank}</span>`,
        iconSize: [18, 18], iconAnchor: [9, 9] }) }).addTo(grp).on("click", () => onClick(p.rank));
  });
  return [grp, byId];
}

function parcelLayer(gj: FeatureCollection, onSelect?: (p: ParcelProps) => void): [L.GeoJSON, Record<string, L.Layer>] {
  const vals = gj.features.map((f) => Number(f.properties?.score) || 0);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const byId: Record<string, L.Layer> = {};
  const layer = L.geoJSON(gj, {
    style: (f) => ({ color: "#0f1419", weight: 0.4, fillOpacity: 0.72,
      fillColor: scoreColor(hi > lo ? ((f!.properties as any).score - lo) / (hi - lo) : 0.5) }),
    onEachFeature: (f, l) => {
      const p = f.properties as any; byId[p.parcel_id] = l;
      if (onSelect) l.on("click", () => onSelect(p as ParcelProps));
      l.bindPopup(popup(`<h3>${p.parcel_id}</h3><table>
        <tr><td class="k">Score</td><td><b>${(p.score ?? 0).toFixed(3)}</b></td></tr>
        <tr><td class="k">Prospectivity</td><td>${pct(p.prospectivity)}</td></tr>
        ${p.claimed_frac ? `<tr><td class="k">In concession</td><td>${pct(p.claimed_frac)}</td></tr>` : ""}
        <tr><td class="k">Municipio</td><td>${p.municipio || "—"}</td></tr></table>`));
    },
  });
  return [layer, byId];
}

function concLayer(gj: FeatureCollection): L.GeoJSON {
  const st = (s: string) => s === "granted" ? { color: "#ff5a5a", fo: 0.22, dash: undefined }
    : s === "pending" ? { color: "#f6954c", fo: 0.14, dash: "5 4" }
    : { color: "#7a8791", fo: 0.06, dash: "3 4" };
  return L.geoJSON(gj, {
    style: (f) => { const s = st((f!.properties as any).status);
      return { color: s.color, weight: 1.2, fillColor: s.color, fillOpacity: s.fo, dashArray: s.dash }; },
    onEachFeature: (f, l) => { const p = f.properties as any;
      l.bindPopup(popup(`<h3>${p.name || "(unnamed)"}</h3><table>
        <tr><td class="k">Status</td><td><b>${p.status}</b></td></tr>
        <tr><td class="k">Blocks</td><td>${p.blocks ? "yes" : "no"}</td></tr></table>`)); },
  });
}

function workLayer(gj: FeatureCollection): L.GeoJSON {
  return L.geoJSON(gj, {
    pointToLayer: (f, ll) => L.marker(ll, { icon: L.divIcon({ className: "work-marker",
      html: `<span style="color:${(f.properties as any).active ? "#ff5a5a" : "#9aa7b3"};font-size:${(f.properties as any).active ? 15 : 12}px;font-weight:700;text-shadow:0 0 3px #0f1419">✕</span>`,
      iconSize: [14, 14], iconAnchor: [7, 7] }) }),
    onEachFeature: (f, l) => { const p = f.properties as any;
      l.bindPopup(popup(`<h3>${(p.sustancia || "Working").trim()}</h3><table>
        <tr><td class="k">Status</td><td><b>${p.estado || "—"}</b></td></tr></table>`)); },
  });
}

type LayerStore = {
  raster?: L.ImageOverlay; occ?: L.GeoJSON; hotspots?: L.LayerGroup;
  workings?: L.GeoJSON; parcels?: L.GeoJSON; hParcels?: L.GeoJSON; conc?: L.GeoJSON;
  hsById?: Record<number, L.Layer>; parcelById?: Record<string, L.Layer>; hParcelById?: Record<string, L.Layer>;
};

function Layers({ region, data, target, drill, toggles, parcelFocus, selectHotspot, selectParcel, setActive }:
  Props & { setActive: (a: ActiveLayers) => void }) {
  const map = useMap();
  const R = useRef<LayerStore>({});

  // (re)build base layers when the region's data loads
  useEffect(() => {
    if (!data?.meta) return;
    Object.values(R.current).forEach((l: any) => l && l.remove && l.remove());
    R.current = {};
    const nr = R.current;
    nr.raster = L.imageOverlay(rasterUrl(region, null), data.meta.raster_bounds, { opacity: 0.75 });
    if (toggles.raster) nr.raster.addTo(map);
    if (data.occ) { nr.occ = occLayer(data.occ); if (toggles.occ) nr.occ.addTo(map); }
    if (data.hotspots) { const [g, byId] = hotspotLayer(data.hotspots, selectHotspot); nr.hotspots = g; nr.hsById = byId; if (toggles.hotspots) g.addTo(map); }
    if (data.workings) { nr.workings = workLayer(data.workings); if (toggles.workings) nr.workings.addTo(map); }
    if (data.meta.n_parcels > 0 && data.parcels) { const [g, byId] = parcelLayer(data.parcels, selectParcel); nr.parcels = g; nr.parcelById = byId; g.addTo(map); }
    setActive({ raster: true, occ: !!data.occ, hotspots: !!data.hotspots, workings: !!data.workings, parcels: data.meta.n_parcels > 0 });
    const b = nr.parcels ? nr.parcels.getBounds()
      : data.hotspots ? L.geoJSON(data.hotspots).getBounds()
      : L.latLngBounds(data.meta.raster_bounds);
    fit(map, b, data.meta.n_parcels > 0 ? 12 : 8);
  }, [data]); // eslint-disable-line

  // swap raster + filter occurrences when the target metal changes
  useEffect(() => {
    const r = R.current;
    if (r.raster) r.raster.setUrl(rasterUrl(region, target));
    if (r.occ) r.occ.eachLayer((l) => {
      const c = ((l as any).feature.properties).commodity, show = !target || c === target, big = TARGET_METALS.includes(c);
      (l as L.CircleMarker).setStyle({ opacity: show ? 1 : 0, fillOpacity: show ? (big ? 0.95 : 0.5) : 0 });
    });
  }, [target]); // eslint-disable-line

  // drill: render the hotspot's parcels + concessions, zoom in
  useEffect(() => {
    const r = R.current;
    if (r.hParcels) { r.hParcels.remove(); r.hParcels = undefined; r.hParcelById = undefined; }
    if (r.conc) { r.conc.remove(); r.conc = undefined; }
    if (!drill) return;
    if (drill.parcels?.features?.length) {
      const [g, byId] = parcelLayer(drill.parcels, selectParcel); r.hParcels = g; r.hParcelById = byId;
      if (toggles.hparcels) g.addTo(map);
      fit(map, g.getBounds(), 14);
    } else if (r.hsById?.[drill.rank]) {
      fit(map, (r.hsById[drill.rank] as any).getBounds(), 11);
    }
    if (drill.concessions?.features?.length) { r.conc = concLayer(drill.concessions); if (toggles.conc) r.conc.addTo(map); }
    setActive({ ...currentActive(R.current), hparcels: !!drill.parcels, conc: !!drill.concessions });
  }, [drill]); // eslint-disable-line

  // toggles: show/hide
  useEffect(() => {
    const r = R.current;
    const set = (layer: L.Layer | undefined, on: boolean) => { if (!layer) return; on ? layer.addTo(map) : layer.remove(); };
    set(r.raster, toggles.raster); set(r.occ, toggles.occ); set(r.hotspots, toggles.hotspots);
    set(r.workings, toggles.workings); set(r.hParcels, toggles.hparcels); set(r.conc, toggles.conc);
  }, [toggles]); // eslint-disable-line

  // focus a parcel from the sidebar list
  useEffect(() => {
    if (!parcelFocus) return;
    const l = R.current.hParcelById?.[parcelFocus.id] || R.current.parcelById?.[parcelFocus.id];
    if (l) { fit(map, (l as any).getBounds(), 15); (l as any).openPopup(); }
  }, [parcelFocus]); // eslint-disable-line

  return null;
}

function currentActive(r: LayerStore): ActiveLayers {
  return { raster: !!r.raster, occ: !!r.occ, hotspots: !!r.hotspots, workings: !!r.workings, parcels: !!r.parcels };
}

export default function MapView(props: Props) {
  const [active, setActive] = useState<ActiveLayers>({});
  return (
    <div id="map">
      <MapContainer center={[40, -3.7]} zoom={5} zoomControl={true} style={{ height: "100%" }}>
        <TileLayer url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          attribution="&copy; OpenStreetMap &copy; CARTO" maxZoom={19} />
        <Layers {...props} setActive={setActive} />
      </MapContainer>
      <Legend active={active}
        metals={(props.data?.meta?.commodity_models || []).slice(0, 3).map((m) => m.key)} />
    </div>
  );
}
