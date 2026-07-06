export default function Intro({ onClose }: { onClose: () => void }) {
  return (
    <div className="modal-bg" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <h2>What is this?</h2>
        <p><b>Subsuelo</b> screens Europe for critical-raw-material investment opportunities —
          16 commodities across two mineral systems — by fusing open geoscience with property
          cadastres, permitting data and land prices.</p>
        <ol>
          <li><b>Find land by budget</b> — state a target metal and a budget; get a ranked list
            of acquisition targets you could actually pursue, best ground first.</li>
          <li><b>Prospectivity</b> — a geology model shades the map by how favourable the ground
            is for each metal. Brighter = better.</li>
          <li><b>Prospective areas</b> — the model ranks the best clusters into hotspots; click
            one to drill down to real cadastral parcels, flagged where mining rights already
            exist.</li>
        </ol>
        <p className="note">All data is real, open, public data — see <b>About</b> (top-right)
          for the full source list and the methods behind the scoring. Switch the <b>Area</b>
          to change region, or the <b>metal</b> to see each commodity's own model.</p>
        <button onClick={onClose}>Explore the map →</button>
      </div>
    </div>
  );
}
