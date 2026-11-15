import { useEffect, useState } from "react";
import { AlertTriangle, ShieldCheck } from "lucide-react";
import { useAppData } from "../context/AppData";
import { ErrorPage, LoadingPage } from "../components/States";
import { BiasChart, EstimatePlot } from "../components/charts";
import {
  Badge,
  Callout,
  KeyValue,
  Limitations,
  Metric,
  MetricStrip,
  PageHeader,
  Panel,
} from "../components/ui";
import { getDigitalTwin } from "../lib/api";
import { fmtInt, fmtNum, fmtPct, fmtSigned, humanRegion } from "../lib/format";
import type { DigitalTwin } from "../lib/types";

export function Audit() {
  const { results, loading, error } = useAppData();
  const [twin, setTwin] = useState<DigitalTwin | null>(null);
  const [twinError, setTwinError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    getDigitalTwin()
      .then((payload) => {
        if (live) setTwin(payload);
      })
      .catch((reason: unknown) => {
        if (live) setTwinError(reason instanceof Error ? reason.message : "Digital twin unavailable");
      });
    return () => {
      live = false;
    };
  }, []);

  if (loading && !results) return <LoadingPage />;
  if (error || !results) return <ErrorPage message={error} />;

  const audit = results.audit;
  const pairing = audit.pairing_sensitivity;
  const terra = audit.terra_extrapolation;
  const late = results.gate.bins["(2, 3.5]"];
  const amazon = results.models.loyo.Amazon;
  const foldYears = Object.keys(results.models.selection.folds);

  const estimates = [
    {
      label: "Cell-day sum",
      slope: pairing.cell_day_sum.slope_per_hour,
      low: pairing.cell_day_sum.ci_low,
      high: pairing.cell_day_sum.ci_high,
      n: pairing.cell_day_sum.n,
      color: "#788B91",
      note: "cell-day sum · 95% CI includes zero",
    },
    {
      label: "Near-coincident",
      slope: pairing.near_coincident.slope_per_hour,
      low: pairing.near_coincident.ci_low,
      high: pairing.near_coincident.ci_high,
      n: pairing.near_coincident.n,
      color: "#B66F4D",
      note: "near-coincident · 95% CI excludes zero",
    },
  ];

  return (
    <div>
      <PageHeader
        kicker="Evidence, assumptions and weaknesses"
        title="Audit & validation"
        lede={
          <>
            The audit asks how wrong the correction could be and where. It reports the parts that
            fail, including the Amazon transfer result, the thin support above 2 h, the Terra
            out-of-regime test and the pairing definition that flips the sign of the delay
            association.
          </>
        }
        side={
          <>
            <Badge tone="warn">negative results included</Badge>
            <span className="mono tiny muted">nested audit tooling</span>
          </>
        }
      />

      <MetricStrip>
        <Metric
          label="Pairing sign change"
          value={`${fmtSigned(pairing.cell_day_sum.slope_per_hour, 2)} → ${fmtSigned(pairing.near_coincident.slope_per_hour, 2)}`}
          hint="slope per hour · cell-day vs near-coincident"
        />
        <Metric label="Terra H RMSE" value={fmtNum(terra.h_rmse, 3)} hint={`raw ${fmtNum(terra.raw_rmse, 3)} · out of regime`} />
        <Metric
          label="Amazon H vs raw"
          value={`${fmtNum(amazon.H.rmse, 2)} / ${fmtNum(amazon.B0.rmse, 2)}`}
          hint="LOGO RMSE · H worse than raw"
        />
        <Metric
          label="Late-bin coverage"
          value={fmtPct(late.coverage)}
          hint={`${fmtInt(late.calibration_n)} pairs · below 0.70 floor`}
        />
        <Metric
          label="Digital twin"
          value={twin ? (twin.passed ? "passed" : "failed") : twinError ? "unavailable" : "…"}
          small
          hint="algorithmic round trip · self-consistency only"
        />
      </MetricStrip>

      <div className="grid two mt">
        <Panel title="Bias by delay bin" meta="raw vs corrected (H) · out-of-fold">
          <BiasChart bins={audit.bias_by_bin} order={results.uncertainty.bin_order} />
          <div className="chart-legend">
            <span>
              <i className="swatch" style={{ background: "#788B91" }} />
              raw bias
            </span>
            <span>
              <i className="swatch" style={{ background: "#526B5B" }} />
              corrected bias (H)
            </span>
          </div>
          <p className="table-note">
            Correction removes most of the raw negative bias in the late bins, but the late-bin RMSE
            still rises. Bias correction is not the same as variance reduction.
          </p>
        </Panel>

        <Panel title="Pairing sensitivity" meta="OLS slope with block-bootstrap 95% CI">
          <EstimatePlot estimates={estimates} />
          <Callout tone="bad" title="The pairing definition changes the sign — this is a first-order caveat" className="mt-sm">
            Cell-day-sum slope <span className="mono">{fmtSigned(pairing.cell_day_sum.slope_per_hour, 4)} h⁻¹</span>{" "}
            with CI{" "}
            <span className="mono">
              [{fmtSigned(pairing.cell_day_sum.ci_low, 3)}, {fmtSigned(pairing.cell_day_sum.ci_high, 3)}]
            </span>{" "}
            includes zero. Near-coincident slope{" "}
            <span className="mono">{fmtSigned(pairing.near_coincident.slope_per_hour, 4)} h⁻¹</span>{" "}
            with CI{" "}
            <span className="mono">
              [{fmtSigned(pairing.near_coincident.ci_low, 3)}, {fmtSigned(pairing.near_coincident.ci_high, 3)}]
            </span>{" "}
            excludes zero. The direction of the claimed timing association depends on the pairing
            rule. This is not a robustness footnote.
          </Callout>
        </Panel>
      </div>

      <div className="grid three mt">
        <Panel title="Terra out-of-regime" meta="fit on Aqua, predict Terra">
          <KeyValue
            rows={[
              ["Terra pairs", fmtInt(terra.n)],
              ["Mean delay", `${fmtSigned(terra.delay_mean_h, 3)} h`],
              ["Raw RMSE", fmtNum(terra.raw_rmse, 4)],
              ["Physics RMSE", fmtNum(terra.physics_rmse, 4)],
              ["H RMSE", fmtNum(terra.h_rmse, 4)],
              ["Raw bias", fmtSigned(terra.raw_bias, 4)],
            ]}
          />
          <Callout tone="bad" title="H is worse than raw" className="mt-sm">
            Terra sits at a mean delay of {fmtNum(terra.delay_mean_h, 2)} h, far outside the Aqua
            calibration. The model is not validated for Terra, and the result is reported as
            extrapolation failure rather than hidden.
          </Callout>
        </Panel>

        <Panel title="Regional transfer" meta="leave-one-region-out">
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Region</th>
                  <th className="num">B0</th>
                  <th className="num">H</th>
                  <th>Reading</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(results.models.loyo).map(([region, entry]) => (
                  <tr key={region}>
                    <td>{humanRegion(region)}</td>
                    <td className="num">{fmtNum(entry.B0.rmse, 3)}</td>
                    <td className="num">{fmtNum(entry.H.rmse, 3)}</td>
                    <td>
                      {entry.H.rmse > entry.B0.rmse ? (
                        <Badge tone="warn">worse</Badge>
                      ) : (
                        <Badge tone="ok">better</Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="table-note">
            Amazon is the clearest transfer failure: H {fmtNum(amazon.H.rmse, 3)} vs raw{" "}
            {fmtNum(amazon.B0.rmse, 3)} ln. A regional score is not an individual interval.
          </p>
        </Panel>

        <Panel title="Audit status" meta="what is measured, pending, not evaluated">
          <div className="stack" style={{ gap: 8 }}>
            <div>
              <Badge tone="ok">measured</Badge>
              <p className="tiny muted mt-1">
                Grouped CV, regional transfer, conformal coverage, Terra test, pairing sensitivity,
                FRE trend, identifiability, digital-twin round trip.
              </p>
            </div>
            <div>
              <Badge tone="warn">pending validation</Badge>
              <ul className="tiny muted mt-1" style={{ paddingLeft: 14 }}>
                {audit.pending.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
            <div>
              <Badge tone="none">not evaluated</Badge>
              <ul className="tiny muted mt-1" style={{ paddingLeft: 14 }}>
                {audit.not_evaluated.map((item) => (
                  <li key={item}>{item.replaceAll("_", " ")}</li>
                ))}
              </ul>
            </div>
          </div>
        </Panel>
      </div>

      <Panel className="mt" title="Grouped cross-validation folds" meta="fold = whole 5-day sampling window">
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Fold</th>
                <th className="num">n train</th>
                <th className="num">n test</th>
                {results.models.available.map((model) => (
                  <th key={model} className="num">
                    {model}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {foldYears.map((year) => {
                const fold = results.models.selection.folds[year];
                return (
                  <tr key={year}>
                    <td className="mono strong">{year}</td>
                    <td className="num">{fmtInt(fold.n_train)}</td>
                    <td className="num">{fmtInt(fold.n_test)}</td>
                    {results.models.available.map((model) => {
                      const metric = fold[model];
                      return (
                        <td key={model} className="num">
                          {typeof metric === "object" && metric !== null ? fmtNum(metric.rmse, 4) : "—"}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
              <tr>
                <td className="strong">Mean</td>
                <td className="num">—</td>
                <td className="num">—</td>
                {results.models.available.map((model) => (
                  <td key={model} className="num strong">
                    {fmtNum(results.models.selection.mean_rmse[model], 4)}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
        <p className="table-note">
          Folds are whole sampling windows, not random rows. This keeps same-window observations out
          of both training and test. The winner is the fold-mean minimum; the served model is a
          separate governance decision.
        </p>
      </Panel>

      <Panel className="mt" title="Validity map" meta="counts and gate verdict by region and delay">
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Region</th>
                <th>Delay bin</th>
                <th className="num">Pairs</th>
                <th className="num">Applicable</th>
                <th className="num">Coverage</th>
                <th>Gate</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(results.validity_map).flatMap(([region, entry]) =>
                results.uncertainty.bin_order.map((label) => {
                  const bin = entry.bins[label];
                  if (!bin) return null;
                  return (
                    <tr key={`${region}-${label}`}>
                      <td>{humanRegion(region)}</td>
                      <td className="mono">{label}</td>
                      <td className="num">{fmtInt(bin.n)}</td>
                      <td className="num">{fmtInt(bin.applicable)}</td>
                      <td className="num">{bin.coverage === null ? "—" : fmtPct(bin.coverage)}</td>
                      <td>
                        {bin.n === 0 ? (
                          <Badge tone="plain">no pairs</Badge>
                        ) : bin.gate_reason ? (
                          <Badge tone="bad">{bin.gate_reason}</Badge>
                        ) : (
                          <Badge tone="ok">applicable</Badge>
                        )}
                      </td>
                    </tr>
                  );
                }),
              )}
            </tbody>
          </table>
        </div>
        <p className="table-note">
          Applicable counts use the pre-registered gate and the measured delay/scan domain. A refused
          cell remains visible with its reason; it is never dropped from the audit.
        </p>
      </Panel>

      <div className="grid side mt">
        <Panel title="Digital twin" meta="injected-offset round trip · algorithmic self-consistency">
          {twinError && (
            <Callout tone="warn" title="Digital twin unavailable">
              {twinError}
            </Callout>
          )}
          {!twin && !twinError && <div className="skeleton" style={{ height: 160 }} />}
          {twin && (
            <>
              <div className="flex items-center gap-2 mb-2">
                <Badge tone={twin.passed ? "ok" : "bad"}>
                  {twin.passed ? "passed" : "failed"}
                </Badge>
                <Badge tone="none">{twin.validation_status.replaceAll("_", " ")}</Badge>
                <span className="mono tiny muted ml-auto">
                  tolerance {fmtNum(twin.tolerance_log_units, 3)} ln
                </span>
              </div>
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Bin</th>
                      <th className="num">n</th>
                      <th className="num">Injected</th>
                      <th className="num">Recovered</th>
                      <th className="num">|error|</th>
                      <th>Result</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(twin.bins).map(([label, row]) => (
                      <tr key={label}>
                        <td className="mono">{label}</td>
                        <td className="num">{fmtInt(row.n)}</td>
                        <td className="num">{fmtSigned(row.injected_log_offset, 4)}</td>
                        <td className="num">{fmtSigned(row.recovered_log_offset, 4)}</td>
                        <td className="num">{fmtNum(row.absolute_error, 6)}</td>
                        <td>
                          <Badge tone={row.within_tolerance ? "ok" : "bad"}>
                            {row.within_tolerance ? "within" : "outside"}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Callout tone="warn" title="This is not independent validation" className="mt-sm">
                {twin.note}
              </Callout>
            </>
          )}
        </Panel>

        <Panel title="Status language" meta="used consistently across the dashboard">
          <div className="stack" style={{ gap: 10 }}>
            <div>
              <Badge tone="ok">Measured</Badge>
              <p className="small muted mt-1">
                Grouped CV, regional transfer, conformal coverage, Terra test, pairing sensitivity,
                FRE trend, identifiability, digital-twin self-consistency.
              </p>
            </div>
            <div>
              <Badge tone="warn">Pending validation</Badge>
              <p className="small muted mt-1">
                {audit.pending.join(" · ")}. These are named so they cannot be mistaken for finished
                work.
              </p>
            </div>
            <div>
              <Badge tone="none">Not evaluated</Badge>
              <p className="small muted mt-1">
                {audit.not_evaluated.map((item) => item.replaceAll("_", " ")).join(" · ")}. They are
                never inferred from FRP magnitude alone.
              </p>
            </div>
          </div>
          <div className="callout neutral mt-sm">
            <span className="callout-title">Why the negative results are on this page</span>
            <div className="flex items-start gap-2 mt-1">
              <AlertTriangle size={14} className="mt-[2px] flex-none text-[#8D611D]" />
              <span>
                A correction that fails in Amazon, flips sign under a different pairing rule, and
                extrapolates poorly to Terra must say so where the serving claim is made.
              </span>
            </div>
            <div className="flex items-start gap-2 mt-2">
              <ShieldCheck size={14} className="mt-[2px] flex-none text-[#526B5B]" />
              <span>
                The gate refuses unsupported cells. The audit refuses unsupported confidence.
              </span>
            </div>
          </div>
        </Panel>
      </div>

      <Limitations items={results.limitations} />
    </div>
  );
}
