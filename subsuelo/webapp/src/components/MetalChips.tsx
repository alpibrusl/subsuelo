import { cinfo } from "../data.ts";
import type { Metal } from "../types";

interface Props {
  options: (Metal | null)[];
  value: Metal | null;
  onChange: (m: Metal | null) => void;
  noneLabel?: string;
}

/** a single scrollable row of metal chips — replaces a wrapping wall of pill
 * buttons (17 commodities don't fit on one line otherwise) with one row that
 * scrolls sideways, so the picker stays a fixed, small height regardless of
 * how many commodities a region offers. */
export default function MetalChips({ options, value, onChange, noneLabel = "All" }: Props) {
  return (
    <div className="chip-strip">
      {options.map((m) => (
        <button key={m ?? "none"} className={"chip" + (value === m ? " on" : "")} onClick={() => onChange(m)}>
          {m && <span className="dot" style={{ background: cinfo(m).color }} />}
          {m ?? noneLabel}
        </button>
      ))}
    </div>
  );
}
