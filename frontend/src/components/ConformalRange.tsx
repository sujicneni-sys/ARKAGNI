import { fmtMw } from "../lib/format";

export function ConformalRange({
  original,
  lower,
  upper,
  point,
}: {
  original: number;
  lower: number;
  upper: number;
  point: number;
}) {
  const domainLow = Math.max(0, Math.min(original, lower) * 0.88);
  const domainHigh = Math.max(original, upper) * 1.08;
  const span = Math.max(domainHigh - domainLow, 1e-6);
  const position = (value: number) =>
    Math.max(0, Math.min(100, ((value - domainLow) / span) * 100));

  return (
    <div className="range-bar">
      <div className="range-labels">
        <span>{fmtMw(domainLow, 0)}</span>
        <span>shared MW scale</span>
        <span>{fmtMw(domainHigh, 0)}</span>
      </div>

      <div className="tiny muted mb-1">Aqua input · before</div>
      <div className="range-track" style={{ height: 14, marginBottom: 12 }}>
        <div
          className="absolute top-[-4px] bottom-[-4px] w-[3px] rounded-sm"
          style={{ left: `${position(original)}%`, background: "#B66F4D" }}
          title={`Aqua input ${fmtMw(original)}`}
        />
        <div
          className="absolute -top-[19px] mono text-[9px] -translate-x-1/2 whitespace-nowrap"
          style={{ left: `${position(original)}%`, color: "#B66F4D" }}
        >
          {fmtMw(original, 1)}
        </div>
      </div>

      <div className="tiny muted mb-1">Harmonized · 80% conformal interval (primary output)</div>
      <div className="range-track">
        <div
          className="range-fill"
          style={{
            left: `${position(lower)}%`,
            width: `${Math.max(0.4, position(upper) - position(lower))}%`,
          }}
        />
        <div className="range-point" style={{ left: `${position(point)}%` }} />
      </div>

      <div className="range-caption">
        <span>lower {fmtMw(lower, 1)}</span>
        <span>
          point estimate <b className="text-ink">{fmtMw(point, 1)}</b>
        </span>
        <span>upper {fmtMw(upper, 1)}</span>
      </div>
      <p className="table-note" style={{ marginTop: 6 }}>
        Read the sage band first. The dark tick is the point estimate and the terracotta tick above
        is the original Aqua value; the band is the calibrated statement.
      </p>
    </div>
  );
}
