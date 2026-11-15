import { ArrowUpRight, CircleAlert } from "lucide-react";
import { useAppData } from "../context/AppData";
import { ErrorPage, LoadingPage } from "../components/States";
import { RegionMap } from "../components/RegionMap";
import { ValidityHeatmap } from "../components/ValidityHeatmap";
import { SimpleBars, SupportBars } from "../components/charts";
import { Badge, Callout, Limitations, Metric, MetricStrip, PageHeader, Panel } from "../components/ui";
import { fmtInt, fmtNum, fmtPct, humanRegion } from "../lib/format";
import type { Results } from "../lib/types";

function findings(results: Results) {
  const late = results.gate.bins["(2, 3.5]"];
  const amazon = results.models.loyo.Amazon;
  const raw = results.models.grouped_cv.B0.rmse;
  const served = results.models.grouped_cv.H.rmse;
  const pairing = results.audit.pairing_sensitivity;
  const terra = results.audit.terra_extrapolation;

  return [
    {
      tone: "ok" as const,
      label: "measured",
      title: `Overall conformal coverage is ${fmtPct(results.uncertainty.overall_coverage)}`,
      body: `Measured against an 80% nominal level with the honest nested estimate. The interval is the primary product; the point estimate is secondary.`,
    },
    {
      tone: "bad" as const,
      label: "refused",
      title: "The late-delay bin is refused",
      body: `The (2, 3.5] h bin holds ${fmtInt(late.calibration_n)} calibration pairs and ${fmtPct(late.coverage)} coverage, below the ${results.gate.coverage_floor.toFixed(2)} floor. The API returns an explicit refusal instead of extrapolating.`,
    },
    {
      tone: "ok" as const,
      label: "measured",
      title: `H lowers grouped-CV RMSE from ${fmtNum(raw, 4)} to ${fmtNum(served, 4)} ln`,
      body: `Fold = whole 5-day sampling window. Lower error is evidence of better agreement with SNPP, not proof of accuracy against an independent reference.`,
    },
    {
      tone: "warn" as const,
      label: "caution",
      title: "Amazon transfer is worse than raw",
      body: `Leave-one-region-out RMSE is H ${fmtNum(amazon.H.rmse, 3)} vs raw ${fmtNum(amazon.B0.rmse, 3)} ln on ${fmtInt(amazon.n)} pairs. The correction is not an improvement there.`,
    },
    {
      tone: "warn" as const,
      label: "caution",
      title: "The pairing definition flips the sign",
      body: `Cell-day-sum slope ${pairing.cell_day_sum.slope_per_hour.toFixed(3)} h⁻¹ (CI includes zero) vs near-coincident +${pairing.near_coincident.slope_per_hour.toFixed(3)} h⁻¹ (CI excludes zero). The pairing choice must accompany every delay claim.`,
    },
    {
      tone: "bad" as const,
      label: "refused",
      title: "Terra is out of regime",
      body: `Delay mean ${fmtNum(terra.delay_mean_h, 2)} h. H RMSE ${fmtNum(terra.h_rmse, 3)} vs raw ${fmtNum(terra.raw_rmse, 3)} ln on ${fmtInt(terra.n)} pairs. The model is not validated for Terra.`,
    },
  ];
}

export function Overview() {
  const { results, loading, error } = useAppData();
  if (loading && !results) return <LoadingPage />;
  if (error || !results) return <ErrorPage message={error} />;

  const composition = Object.entries(results.dataset.rows_by_satellite)
    .map(([satellite, value]) => ({
      label:
        satellite === "N" ? "Suomi-NPP" : satellite === "N20" ? "NOAA-20" : satellite,
      value,
      display: fmtInt(value),
      color:
        satellite === "Aqua"
          ? "#B66F4D"
          : satellite === "Terra"
            ? "#C77B43"
            : satellite === "N"
              ? "#526B5B"
              : "#788B91",
    }))
    .sort((a, b) => b.value - a.value);

  const findingRows = findings(results);

  return (
    <div>
      <PageHeader
        kicker="The product in one view"
        title="Satellite fire data harmonization"
        lede={
          <>
            Arkagni estimates and corrects timing-related differences in matched satellite
            Fire Radiative Power observations, with calibrated uncertainty and an applicability
            verdict for every 1° cell-day. Saturation, plume scattering and canopy occlusion are
            never assumed away.
          </>
        }
        side={
          <>
            <Badge tone="ok">verified artifacts</Badge>
            <span className="mono tiny muted">
              generated {results.generated_at_utc.slice(0, 19).replace("T", " ")} UTC
            </span>
          </>
        }
      />

      <MetricStrip columns={4}>
        <Metric
          label="Raw observations"
          value={fmtInt(results.dataset.rows)}
          hint={`L1 canonical rows · ${results.dataset.date_min} → ${results.dataset.date_max}`}
        />
        <Metric
          label="Matched cell-days"
          value={fmtInt(results.pairs.count)}
          hint={`Aqua ↔ Suomi-NPP · ${fmtInt(results.pairs.aqua_cell_days)} Aqua cell-days`}
        />
        <Metric
          label="Study regions"
          value={results.dataset.regions}
          hint={`${results.dataset.windows} five-day windows · ${fmtInt(results.dataset.validated_rows)} validated rows`}
        />
        <Metric
          label="Conformal coverage"
          value={fmtPct(results.uncertainty.overall_coverage)}
          hint="80% nominal · honest nested estimate"
        />
      </MetricStrip>

      <div className="grid side mt">
        <Panel
          title="Geographic study area"
          meta="region envelopes · schematic bowtie, not fire footprints"
        >
          <RegionMap
            regionBounds={results.dataset.region_bounds}
            shareByRegion={results.pairs.share_by_region}
            regionSummary={results.pairs.region_summary}
          />
        </Panel>

        <div className="stack">
          <Panel title="Region × delay validity" meta="gate verdict · out-of-fold coverage">
            <ValidityHeatmap
              validity={results.validity_map}
              binOrder={results.uncertainty.bin_order}
            />
          </Panel>

          <Panel title="Key findings" meta="measured, not assumed">
            <div className="stack" style={{ gap: 12 }}>
              {findingRows.map((finding) => (
                <div key={finding.title} className="finding">
                  <Badge tone={finding.tone} className="finding-badge">
                    {finding.label}
                  </Badge>
                  <div>
                    <div className="finding-title">{finding.title}</div>
                    <div className="finding-body">{finding.body}</div>
                  </div>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Research workflow" meta="one pure core, three callers">
            <ol className="text-[11.5px] muted" style={{ paddingLeft: 16 }}>
              <li>
                <b className="text-ink">Freeze and hash</b> the three FIRMS cleaned inputs; preserve
                the source archive.
              </li>
              <li>
                <b className="text-ink">Flag, never delete</b>: type ≠ 0, FRP ≤ 0 and night become a
                uint8 bitmask.
              </li>
              <li>
                <b className="text-ink">Aggregate</b> to 1° cell-days and inner-join Aqua to SNPP.
              </li>
              <li>
                <b className="text-ink">Model</b> the log FRP ratio with a diurnal physics shape and
                regional offsets.
              </li>
              <li>
                <b className="text-ink">Calibrate</b> 80% split-conformal intervals per delay bin.
              </li>
              <li>
                <b className="text-ink">Gate</b>: refuse thin or poorly covered bins with an explicit
                code.
              </li>
            </ol>
            <div className="callout neutral mt-sm">
              <span className="callout-title">Same core everywhere</span>
              Training, batch inference and POST /harmonize call the same pure L5 functions. The
              dashboard never recomputes science.
            </div>
          </Panel>
        </div>
      </div>

      <div className="grid two mt">
        <Panel title="Data composition" meta="actual L1 row counts">
          <SimpleBars data={composition} height={225} integer leftWidth={96} />
          <p className="table-note">
            NOAA-20 contributes the largest raw count but is <b>not</b> the harmonization target.
            The served pair is Aqua → Suomi-NPP; NOAA-20 and Terra are audit comparators.
          </p>
        </Panel>
        <Panel title="Delay support" meta="Aqua minus 13.6 h · calibration pairs per bin">
          <SupportBars bins={results.gate.bins} order={results.uncertainty.bin_order} />
          <p className="table-note">
            Late-delay bins are narrow. The orange bar is the refused <span className="mono">(2, 3.5]</span>{" "}
            bin: {fmtInt(results.gate.bins["(2, 3.5]"].calibration_n)} pairs and{" "}
            {fmtPct(results.gate.bins["(2, 3.5]"].coverage)} coverage. The API refuses rather than
            extrapolates.
          </p>
        </Panel>
      </div>

      <div className="grid two mt">
        <Callout tone="warn" title="What “harmonized” means here">
          The output maps an Aqua cell-day sum to what SNPP would report at the 13.6 h reference,
          including the sensor-pair scale offset. It is <b>not</b> a pure time shift and it is{" "}
          <b>not</b> a per-pixel correction.
        </Callout>
        <Callout tone="neutral" title="What the interval is — and is not">
          The 80% conformal band describes cell-day noise from out-of-fold residuals. It is not an
          individual-pixel accuracy claim, and it does not become narrower by repeating the request.{" "}
          <span className="inline-flex items-center gap-1 text-sage font-semibold">
            Read the range first <ArrowUpRight size={12} />
          </span>
        </Callout>
      </div>

      <div className="mt">
        <Callout tone="neutral" title="Regions at a glance">
          <div className="grid four mt-sm" style={{ gap: 8 }}>
            {results.gate.domain.regions.map((region) => {
              const summary = results.pairs.region_summary[region];
              return (
                <div key={region} className="panel tight" style={{ background: "#FAF8F2" }}>
                  <div className="flex items-center justify-between gap-1">
                    <b className="text-[11.5px]">{humanRegion(region)}</b>
                    <span className="mono tiny muted">{fmtPct(summary.share)}</span>
                  </div>
                  <div className="mono text-[10.5px] mt-1">
                    {fmtInt(summary.n)} pairs · delay {fmtNum(summary.delay_median_h, 3)} h
                  </div>
                  <div className="tiny muted">
                    raw RMSE {fmtNum(summary.raw_rmse, 3)} ln · bias {fmtNum(summary.raw_bias, 3)}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="tiny muted mt-sm flex items-center gap-1">
            <CircleAlert size={11} /> Region shares sum to 100% of the 6,313 Aqua–SNPP pairs.
          </div>
        </Callout>
      </div>

      <Limitations items={results.limitations} />
    </div>
  );
}
