const SOURCES: [string, string][] = [
  ["Geology (lithology + faults)",
    "IGME 1:1M (Spain, ArcGIS REST) and EGDI 1:1M (Europe, WFS) — granite/granitoid and felsic-volcanic host units, plus fault traces (EGDI HIKE)."],
  ["Mineral occurrences",
    "IGME BDMIN (Spain) and the EGDI INSPIRE mineral-occurrence inventory (Europe) — the known showings each model is trained on."],
  ["Land parcels (cadastres)",
    "Spanish Catastro (INSPIRE), French IGN Géoplateforme, Czech ČÚZK, and German GeoSN ALKIS (Saxony) — real parcel boundaries."],
  ["Mining rights (permitting friction)",
    "MITECO Catastro Minero (national) and IDECyL (Castilla y León) — granted/pending legal concessions."],
  ["Land prices",
    "France DVF (real recorded transactions, per-commune median); Eurostat apri_lprc (arable-land €/ha by NUTS region) and Destatis Kaufwerte (Germany) as estimated priors."],
  ["Reference geometry",
    "Natural Earth (coastline/country masks) and Eurostat GISCO (NUTS boundaries)."],
];

export default function About({ onClose }: { onClose: () => void }) {
  return (
    <div className="modal-bg" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal about">
        <h2>About Subsuelo</h2>
        <p>Subsuelo screens where to look for — and buy land for — critical-raw-material
          metals, by fusing open geoscience, property cadastres, permitting data and land
          prices into one map. Everything below is <b>real, open, public data</b>; the tool
          computes screening indications, not exploration-grade or legal conclusions.</p>

        <h3>Where the data comes from</h3>
        <dl className="src-list">
          {SOURCES.map(([k, v]) => (
            <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
          ))}
        </dl>

        <h3>How the models work</h3>
        <p><b>Prospectivity</b> is a <b>Weights-of-Evidence</b> model (Agterberg / Bonham-Carter) —
          a Bayesian, data-driven method. Each grid cell gets a posterior probability from three
          binarized evidence layers: <i>near host rock</i>, <i>within host rock</i>, and
          <i> near a fault</i>. The weights are learned from the known occurrences of each metal,
          so the map is trained on real deposits, not hand-tuned.</p>
        <p>Two <b>mineral systems</b> are modelled with their own host evidence:
          <b> granite-related</b> (Sn·W·Li·Ta·Nb·U·Mo·Be·Bi, hosted by granites/pegmatites) and
          <b> VMS base metals</b> (Cu·Zn·Pb·Ag — the Iberian Pyrite Belt, hosted by felsic
          volcanics). Each metal gets its own posterior. Models trained on very few showings, or
          on a host the metal doesn't strictly belong to (Ba·As·Sb on the granite model), are
          flagged <b>“indicative”</b>.</p>
        <p><b>Prospective areas (hotspots)</b> combine prospectivity with occurrence density
          (Gaussian-smoothed) and are thresholded into ranked clusters. <b>Parcels</b> inside a
          hotspot are scored with a composite:</p>
        <p className="formula">score = 0.5 · prospectivity + 0.3 · cheapness + 0.2 · (1 − friction)</p>
        <p>— where <b>cheapness</b> comes from land price (real DVF transactions, or an estimated
          regional €/ha, tagged “est.”) and <b>friction</b> from overlap with an existing mining
          concession.</p>

        <h3>Caveats</h3>
        <p className="note">The geology is 1:1M (coarse — a screening scale, not a drill target).
          Estimated prices are regional averages of agricultural land, a proxy for the actual
          parcel. Occurrence inventories are incomplete. Treat results as a first filter, then
          verify against primary sources.</p>

        <p className="note">Open source (EUPL-1.2) ·{" "}
          <a href="https://github.com/alpibrusl/subsuelo" target="_blank" rel="noopener noreferrer">
            github.com/alpibrusl/subsuelo</a> — full data-source and method notes in the repo.</p>

        <button onClick={onClose}>Close</button>
      </div>
    </div>
  );
}
