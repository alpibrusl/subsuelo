export default function Intro({ onClose }: { onClose: () => void }) {
  return (
    <div className="modal-bg" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <h2>What is this?</h2>
        <p><b>Subsuelo</b> screens where to look for — and buy land for — tin, tungsten and
          lithium, by fusing open geoscience with the property cadastre.</p>
        <ol>
          <li><b>Prospectivity</b> — a geology model shades the map by how favourable the ground
            is for Sn·W·Li. Brighter = better.</li>
          <li><b>Prospective areas</b> — the model ranks the best clusters into hotspots.
            Click one to drill in.</li>
          <li><b>Land parcels</b> — for a hotspot, real cadastral parcels are scored and
            flagged where mining rights already exist.</li>
        </ol>
        <p className="note">All data is real, open, public data (IGME · EGDI · Catastro ·
          Minerals4EU). Switch the <b>Area</b> (top-left) to change scale, or the <b>metal</b>
          to see each mineral's own model.</p>
        <button onClick={onClose}>Explore the map →</button>
      </div>
    </div>
  );
}
