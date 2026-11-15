import { useAppData } from "../context/AppData";
import { ErrorPage, LoadingPage } from "../components/States";
import { CoverageChart, WidthFactorChart, YearBars } from "../components/charts";
import {
  Badge,
  Callout,
  Equation,
  KeyValue,
  Limitations,
  Metric,
  MetricStrip,
  PageHeader,
  Panel,
} from "../components/ui";
import { fmtInt, fmtNum, fmtPct, fmtSigned } from "../lib/format";

export function Uncertainty() {
  const { results, loading, error } = useAppData();
  if (loading && !results) return <LoadingPage />;
  if (error || !results) return <ErrorPage message={error} />;

  const { uncertainty, gate } = results;
  const widthFactors = Object.values(uncertainty.calibration)
    .map((entry) => entry.width_factor)
    .filter((value) => Number.isFinite(value))
    .sort((a, b) => a - b);
  const medianWidthFactor =
    widthFactors.length > 0 ? widthFactors[Math.floor(widthFactors.length / 2)] : null;
  const trend = results.audit.fre_trend;
  const identifiability = results.audit.identifiability;

  return (
    <div>
      <PageHeader
        kicker="Reliability and limits"
        title="Uncertainty analysis"
        lede={
          <>
            Conformal coverage is measured by delay bin with the evaluated sampling block excluded
            from calibration. Where support is thin the empirical coverage falls and the gate
            refuses the cell. The interval is the product; the point estimate is supporting metadata.
          </>
        }
        side={
          <>
            <Badge tone="ok">{fmtPct(uncertainty.nominal_coverage, 0)} nominal</Badge>
            <span className="mono tiny muted">α = {uncertainty.alpha}</span>
          </>
        }
      />

      <MetricStrip>
        <Metric
          label="Overall coverage"
          value={fmtPct(uncertainty.overall_coverage)}
          hint="honest nested estimate · out-of-fold"
        />
        <Metric
          label="In-sample coverage"
          value={fmtPct(uncertainty.in_sample_coverage)}
          hint="calibration residuals · optimistic comparison"
        />
        <Metric label="Nominal level" value={fmtPct(uncertainty.nominal_coverage, 0)} hint="split conformal" />
        <Metric label="Coverage floor" value={fmtPct(gate.coverage_floor, 0)} hint="pre-registered refusal threshold" />
        <Metric
          label="Minimum calibration"
          value={fmtInt(gate.min_calibration_pairs)}
          hint="pairs per delay bin"
        />
      </MetricStrip>

      <div className="grid side mt">
        <Panel
          title="Conformal coverage by delay bin"
          meta="80% nominal · honest nested estimate · orange = refused"
        >
          <CoverageChart
            bins={gate.bins}
            order={uncertainty.bin_order}
            nominal={uncertainty.nominal_coverage}
            floor={gate.coverage_floor}
          />
          <div className="chart-legend">
            <span>
              <i className="swatch" style={{ background: "#526B5B" }} />
              applicable bin
            </span>
            <span>
              <i className="swatch" style={{ background: "#C77B43" }} />
              refused bin
            </span>
            <span>
              <i className="swatch" style={{ background: "#B66F4D" }} />
              80% nominal reference
            </span>
          </div>
          <p className="table-note">
            The evaluated sampling block is excluded from calibration. This is why the last bin is
            shown at {fmtPct(gate.bins["(2, 3.5]"].coverage)} instead of being hidden behind the
            pooled quantile.
          </p>
        </Panel>

        <Panel title="Gate table" meta="pre-registered rules">
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Delay bin</th>
                  <th className="num">n</th>
                  <th className="num">Coverage</th>
                  <th>Verdict</th>
                </tr>
              </thead>
              <tbody>
                {uncertainty.bin_order.map((label) => {
                  const row = gate.bins[label];
                  return (
                    <tr key={label}>
                      <td className="mono">{label}</td>
                      <td className="num">{fmtInt(row?.calibration_n)}</td>
                      <td className="num">{fmtPct(row?.coverage)}</td>
                      <td>
                        {row?.applicable ? (
                          <Badge tone="ok">applicable</Badge>
                        ) : (
                          <Badge tone="bad">{row?.reason ?? "refused"}</Badge>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="table-note">
            Gate: at least {gate.min_calibration_pairs} calibration pairs and out-of-fold coverage of
            at least {gate.coverage_floor.toFixed(2)}. A bin that fails is refused, not silently
            trusted. The late bin has {fmtInt(gate.bins["(2, 3.5]"].calibration_n)} pairs but{" "}
            {fmtPct(gate.bins["(2, 3.5]"].coverage)} coverage, so pair count alone is not enough.
          </p>
        </Panel>
      </div>

      <div className="grid two mt">
        <Panel title="Applicability domain" meta="measured 1st–99th percentile ranges">
          <KeyValue
            rows={[
              [
                "Delay domain",
                `${fmtNum(gate.domain.delay_low, 3)} … ${fmtNum(gate.domain.delay_high, 3)} h`,
              ],
              [
                "Scan domain",
                `${fmtNum(gate.domain.scan_low, 3)} … ${fmtNum(gate.domain.scan_high, 3)} km`,
              ],
              ["Regions in training", gate.domain.regions.join(", ").replaceAll("_", " ")],
              ["Coverage floor", fmtPct(gate.coverage_floor, 0)],
              ["Minimum calibration pairs", fmtInt(gate.min_calibration_pairs)],
              ["Alpha / nominal", `${gate.alpha} / ${fmtPct(gate.nominal_coverage, 0)}`],
            ]}
          />
          <Callout tone="neutral" title="Not evaluated — never inferred from FRP size" className="mt-sm">
            <div className="flex flex-wrap gap-1">
              {results.audit.not_evaluated.map((item) => (
                <Badge key={item} tone="none">
                  {item.replaceAll("_", " ")}
                </Badge>
              ))}
            </div>
          </Callout>
        </Panel>

        <Panel title="Interval behaviour" meta="multiplicative width factors by delay bin">
          <Equation label="interval">interval = [FRP_h · exp(−q), FRP_h · exp(+q)]</Equation>
          <p className="small muted">
            The 80% quantile <span className="mono">q</span> is the split-conformal absolute residual
            quantile for the bin. Because the correction is multiplicative, the band width scales
            with the point estimate. The median multiplicative factor is{" "}
            <b>{medianWidthFactor === null ? "—" : `${fmtNum(medianWidthFactor, 2)}×`}</b>.
          </p>
          <div className="mt-sm">
            <WidthFactorChart calibration={uncertainty.calibration} order={uncertainty.bin_order} />
          </div>
          <p className="table-note">
            Orange bars are bins with fewer than 40 calibration pairs. The late bin has both thin
            support and a 6.25× width factor; its interval is wide <b>and</b> under-covered, which is
            exactly why the gate refuses it.
          </p>
        </Panel>
      </div>

      <Panel className="mt" title="Nested versus in-sample coverage" meta="the difference is the honesty gap">
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Delay bin</th>
                <th className="num">n</th>
                <th className="num">In-sample</th>
                <th className="num">Nested (honest)</th>
                <th className="num">Gap</th>
                <th>Reading</th>
              </tr>
            </thead>
            <tbody>
              {uncertainty.bin_order.map((label) => {
                const inSample = uncertainty.in_sample[label];
                const nested = uncertainty.nested[label];
                const gap =
                  inSample && nested ? nested.coverage - inSample.coverage : null;
                return (
                  <tr key={label}>
                    <td className="mono">{label}</td>
                    <td className="num">{fmtInt(nested?.n)}</td>
                    <td className="num">{fmtPct(inSample?.coverage)}</td>
                    <td className="num">{fmtPct(nested?.coverage)}</td>
                    <td className="num">{gap === null ? "—" : `${fmtSigned(gap * 100, 1)} pp`}</td>
                    <td className="text-[11px]">
                      {label === "(2, 3.5]" ? (
                        <Badge tone="bad">honest coverage collapses</Badge>
                      ) : (nested?.coverage ?? 0) >= gate.coverage_floor ? (
                        <Badge tone="ok">within gate</Badge>
                      ) : (
                        <Badge tone="warn">below floor</Badge>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="table-note">
          In-sample coverage near 80% is expected by construction. The nested estimate removes the
          evaluated sampling block from calibration and is the only number used for the gate.
        </p>
      </Panel>

      <div className="grid two mt">
        <Panel title="FRE trend audit" meta={trend.unit}>
          <YearBars data={trend.yearly_frp} />
          <Callout tone={trend.significant ? "warn" : "neutral"} title={trend.significant ? "Significant at 95%" : "Not statistically significant"} className="mt-sm">
            Naive log-linear slope <span className="mono">{fmtSigned(trend.naive_slope_percent_per_year, 3)}%/yr</span>{" "}
            with 95% interval{" "}
            <span className="mono">
              [{fmtSigned(trend.ci_low_percent, 2)}, {fmtSigned(trend.ci_high_percent, 2)}]%/yr
            </span>
            . The interval crosses zero, so no trend claim is made. The bars are measured validated
            annual FRP totals across all sensors; the line is not drawn because the dashboard does
            not recompute the fit.
          </Callout>
        </Panel>

        <Panel title="Identifiability" meta="late-delay support">
          <KeyValue
            rows={[
              ["Independent unit", identifiability.independent_unit],
              ["Cells", fmtInt(identifiability.n_cells)],
              ["Independent blocks", fmtInt(identifiability.n_blocks)],
              ["Mean bias", fmtSigned(identifiability.mean_bias, 4)],
              ["Cell-level SE", fmtNum(identifiability.cell_level_se, 4)],
              [
                "Block-level SE",
                identifiability.block_level_se === null ? "not available" : fmtNum(identifiability.block_level_se, 4),
              ],
            ]}
          />
          <Callout tone="warn" title="The cell-level standard error is optimistic" className="mt-sm">
            All {fmtInt(identifiability.n_cells)} late-delay cells sit inside a single date-region
            sampling block. Treating cells as independent overstates the effective sample size. A
            block-level standard error is not available, so no confidence claim is made for this
            bin.
          </Callout>
          <div className="tiny muted mt-sm">
            {identifiability.n_blocks < 2
              ? "Fewer than two independent blocks: the data cannot separate cell noise from block-level bias."
              : "At least two independent blocks are available."}
          </div>
        </Panel>
      </div>

      <Limitations items={results.limitations} />
    </div>
  );
}
