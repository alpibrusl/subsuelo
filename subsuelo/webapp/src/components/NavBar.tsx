import { useState } from "react";

const REPO = "https://github.com/alpibrusl/subsuelo";

export default function NavBar({ onAbout, onGuide }: { onAbout: () => void; onGuide: () => void }) {
  const [copied, setCopied] = useState(false);
  const share = () => {
    navigator.clipboard?.writeText(location.href).then(() => {
      setCopied(true); setTimeout(() => setCopied(false), 1500);
    });
  };
  return (
    <nav id="navbar">
      <div className="nb-brand">
        <span className="nb-mark" aria-hidden="true" />
        <span className="nb-name">Subsuelo</span>
        <span className="nb-tag">mineral prospectivity · land screening</span>
      </div>
      <div className="nb-links">
        <button onClick={onGuide}>Guide</button>
        <button onClick={onAbout}>About</button>
        <button onClick={share}>{copied ? "✓ copied" : "Share"}</button>
        <a href={REPO} target="_blank" rel="noopener noreferrer" className="nb-gh">GitHub ↗</a>
      </div>
    </nav>
  );
}
