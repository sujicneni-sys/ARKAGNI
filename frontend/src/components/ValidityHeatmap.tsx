import type { ValidityMap } from "../lib/types";
import { fmtInt, fmtPct, humanRegion } from "../lib/format";

const BIN_LABELS: Record<string, string> = {
  "(-3, 0]": "≤ 0",
  "(0, 0.5]": "0–0.5",
  "(0.5, 1]": "0.5–1",
  "(1, 1.5]": "1–1.5",
  "(1.5, 2]": "1.5–2",
  "(2, 3.5]": "2–3.5",
};

function tone(bin: { n: number; coverage: number | null; applicable: number }): string {
  if (bin.n === 0 || bin.coverage === null) return "empty";
  if (bin.applicable === 0) return "refused";
  if (bin.coverage >= 0.8) return "good";
  if (bin.coverage >= 0.7) return "warn";
  return "bad";
}

interface Props {
  validity: ValidityMap;
  binOrder: string[];
  className?: string;
}

/**
 * 4 x 6 region-by-delay validity heatmap. Colour is the out-of-fold conformal
 * coverage of the served gate; a refused cell is hatched and never rendered as
 * a correction. Counts stay in the tooltip so the grid remains compact.
 */
export function ValidityHeatmap({ validity, binOrder, className = "" }: Props) {
  const regions = Object.keys(validity);
  const southernAfrica = validity.Southern_Africa;
  const midBin = southernAfrica?.bins["(1.5, 2]"];
  const lateBin = southernAfrica?.bins["(2, 3.5]"];

  return (
    <div className={`heatmap ${className}`.trim()}>
      <div className="heatmap-grid" role="table" aria-label="Region by delay validity">
        <div className="heatmap-corner" aria-hidden />
        {binOrder.map((label) => (
          <div key={label} className="heatmap-col" title={`Delay bin ${label} h`}>
            {BIN_LABELS[label] ?? label}
          </div>
        ))}

        {regions.map((region) => (
          <div key={region} className="contents" role="row">
            <div className="heatmap-row" title={`${humanRegion(region)} · ${fmtInt(validity[region].n_pairs)} pairs`}>
              {humanRegion(region)}
            </div>
            {binOrder.map((label) => {
              const bin = validity[region].bins[label];
              if (!bin) {
                return <div key={label} className="heatmap-cell empty" aria-label="no row" />;
              }
              const cellTone = tone(bin);
              const detail =
                bin.n === 0
                  ? "no pairs"
                  : `${fmtInt(bin.n)} pairs · ${fmtInt(bin.applicable)} applicable · coverage ${
                      bin.coverage === null ? "not measured" : fmtPct(bin.coverage)
                    }${bin.gate_reason ? ` · ${bin.gate_reason}` : ""}`;
              return (
                <div
                  key={label}
                  className={`heatmap-cell ${cellTone}`}
                  title={`${humanRegion(region)} · ${label} h — ${detail}`}
                  aria-label={`${humanRegion(region)}, ${label} hours, ${detail}`}
                >
                  <span className="heatmap-value">
                    {bin.n === 0 || bin.coverage === null ? "—" : fmtPct(bin.coverage)}
                  </span>
                  {bin.n > 0 && <span className="heatmap-n">{fmtInt(bin.n)}</span>}
                </div>
              );
            })}
          </div>
        ))}
      </div>

      <div className="heatmap-legend" aria-hidden>
        <span className="heatmap-key good">≥ 80%</span>
        <span className="heatmap-key warn">70–80%</span>
        <span className="heatmap-key bad">&lt; 70%</span>
        <span className="heatmap-key refused">refused</span>
        <span className="heatmap-key empty">no pairs</span>
      </div>

      {midBin && lateBin && (
        <p className="table-note">
          <b className="text-ink">Single-window leverage:</b> the Southern Africa 1.5–2.0 h cell (
          {fmtInt(midBin.n)} pairs) is concentrated in one 5-day sampling window, so its{" "}
          {midBin.coverage === null ? "measured" : fmtPct(midBin.coverage)} coverage is not
          independent evidence. The refused 2–3.5 h late bin sits in a single date-region block (
          {fmtInt(lateBin.n)} pairs) and returns no correction.
        </p>
      )}
    </div>
  );
}
