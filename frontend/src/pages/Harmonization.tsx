import { useEffect, useRef, useState } from "react";
import { Check, CircleAlert, Loader2, Play, RotateCcw, ShieldCheck, X } from "lucide-react";
import { useAppData } from "../context/AppData";
import { ErrorPage, LoadingPage } from "../components/States";
import { ConformalRange } from "../components/ConformalRange";
import { useToast } from "../components/Toast";
import {
  Badge,
  Callout,
  Equation,
  KeyValue,
  Limitations,
  PageHeader,
  Panel,
} from "../components/ui";
import { ApiError, getIngestionHarmonization, harmonize, type HarmonizePayload } from "../lib/api";
import { fmtHash, fmtInt, fmtMw, fmtNum, fmtPct, fmtSigned, humanRegion } from "../lib/format";
import {
  assignDelayBin,
  cellLabel,
  dateCovered,
  delayFromLst,
  frpFromSlider,
  localSolarTime,
  lstFromHours,
  parseCell,
  parseLstText,
  sliderFromFrp,
} from "../lib/science";
import type {
  ActualExample,
  HarmonizeCell,
  HarmonizeResponse,
  LiveHarmonization,
  RegionalContext,
} from "../lib/types";

const DEFAULT_REGION = "Southern_Africa";
const DEFAULT_LAT = -12.3456;
const DEFAULT_LON = 25.6789;
const DEFAULT_FRP = 180;
const DEFAULT_DETECTIONS = 12;
const DEFAULT_LST = "14:54";
const DEFAULT_SCAN = 1.3;

function GuardChip({ label, ok }: { label: string; ok: boolean }) {
  return (
    <Badge tone={ok ? "ok" : "bad"}>
      {label}: {ok ? "inside" : "outside"}
    </Badge>
  );
}

function ReasonLanguage({ code }: { code: string | null }) {
  const map: Record<string, string> = {
    coverage_below_floor:
      "Honest out-of-fold coverage in this delay bin is below the 0.70 floor. The data does not support a correction there.",
    insufficient_calibration_pairs:
      "Fewer than 40 out-of-fold calibration pairs exist for this delay bin.",
    delay_outside_calibrated_range:
      "The overpass delay lies outside the measured 1st–99th percentile training domain.",
    scan_out_of_range:
      "The Aqua scan value lies outside the measured 1st–99th percentile training domain.",
    region_not_in_training: "The region is not one of the four training regions.",
  };
  return <>{code ? (map[code] ?? code) : "Refused by the applicability gate."}</>;
}

export function Harmonization() {
  const { results, config, loading, error } = useAppData();
  const { notify } = useToast();
  const [region, setRegion] = useState(DEFAULT_REGION);
  const [date, setDate] = useState("");
  const [lat, setLat] = useState(DEFAULT_LAT);
  const [lon, setLon] = useState(DEFAULT_LON);
  const [frp, setFrp] = useState(DEFAULT_FRP);
  const [detections, setDetections] = useState(DEFAULT_DETECTIONS);
  const [lstText, setLstText] = useState(DEFAULT_LST);
  const [scan, setScan] = useState(DEFAULT_SCAN);
  const [result, setResult] = useState<HarmonizeResponse | null>(null);
  const [runError, setRunError] = useState<ApiError | null>(null);
  const [running, setRunning] = useState(false);
  const [live, setLive] = useState<LiveHarmonization | null>(null);
  const [liveError, setLiveError] = useState<string | null>(null);
  const initialised = useRef(false);

  useEffect(() => {
    let alive = true;
    getIngestionHarmonization()
      .then((payload) => {
        if (alive) setLive(payload);
      })
      .catch((reason: unknown) => {
        if (alive) setLiveError(reason instanceof Error ? reason.message : "Live replay unavailable");
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!results || initialised.current) return;
    initialised.current = true;
    setDate(results.dataset.window_starts[0] ?? results.dataset.date_min);
    if (!results.gate.domain.regions.includes(DEFAULT_REGION) && results.gate.domain.regions[0]) {
      setRegion(results.gate.domain.regions[0]);
    }
  }, [results]);

  if (loading && !results) return <LoadingPage />;
  if (error || !results || !config) return <ErrorPage message={error} />;

  const windowStarts = results.dataset.window_starts;
  const windowDays = results.dataset.window_days;
  const lstHours = parseLstText(lstText);
  const delay = lstHours !== null ? delayFromLst(lstHours) : null;
  const bin = delay !== null ? assignDelayBin(delay) : null;
  const snappedLat = Number.isFinite(lat) ? Math.floor(lat) : null;
  const snappedLon = Number.isFinite(lon) ? Math.floor(lon) : null;

  const checklist: Array<{ label: string; ok: boolean; hint: string }> = [
    {
      label: "Region is in the training set",
      ok: results.gate.domain.regions.includes(region),
      hint: "Only the four measured study regions are accepted.",
    },
    {
      label: "Date is inside a verified 5-day window",
      ok: dateCovered(date, windowStarts, windowDays),
      hint: `Window starts: ${windowStarts.join(", ")}.`,
    },
    {
      label: "Latitude is within −90 … 90",
      ok: Number.isFinite(lat) && lat >= -90 && lat <= 90,
      hint: "Snapped with floor() to the 1° grid.",
    },
    {
      label: "Longitude is within −180 … 180",
      ok: Number.isFinite(lon) && lon >= -180 && lon <= 180,
      hint: "Snapped with floor() to the 1° grid.",
    },
    {
      label: "Aqua FRP is finite and above zero",
      ok: Number.isFinite(frp) && frp > 0,
      hint: "Cell-day FRP sum in megawatts.",
    },
    {
      label: "Detections is an integer of at least 1",
      ok: Number.isInteger(detections) && detections >= 1,
      hint: "Aqua pixels contributing to the cell-day.",
    },
    {
      label: "Local solar time is a valid HH:MM value",
      ok: lstHours !== null,
      hint: "Never enter the padded integer form (118 is 01:18).",
    },
    {
      label: "Scan is positive and at most 100 km",
      ok: Number.isFinite(scan) && scan > 0 && scan <= 100,
      hint: "Matches the FIRMS scan field used in training.",
    },
  ];
  const formValid = checklist.every((item) => item.ok);

  const regionInDomain = results.gate.domain.regions.includes(region);
  const delayInDomain =
    delay !== null &&
    delay >= results.gate.domain.delay_low &&
    delay <= results.gate.domain.delay_high;
  const scanInDomain =
    scan >= results.gate.domain.scan_low && scan <= results.gate.domain.scan_high;
  const binEntry = bin ? results.gate.bins[bin] : undefined;

  const loadExample = (example: ActualExample) => {
    const coords = parseCell(example.cell);
    setRegion(example.region);
    setDate(example.date);
    if (coords) {
      setLat(coords.lat + 0.5);
      setLon(coords.lon + 0.5);
    }
    setFrp(example.frp_aqua_mw);
    setDetections(example.detections);
    setLstText(lstFromHours(example.lst_aqua_h));
    setScan(example.scan_aqua);
    setResult(null);
    setRunError(null);
    notify(`Loaded actual ${example.cell} · ${example.date}. Run to call the API.`);
  };

  const reset = () => {
    setRegion(
      results.gate.domain.regions.includes(DEFAULT_REGION)
        ? DEFAULT_REGION
        : results.gate.domain.regions[0],
    );
    setDate(results.dataset.window_starts[0] ?? results.dataset.date_min);
    setLat(DEFAULT_LAT);
    setLon(DEFAULT_LON);
    setFrp(DEFAULT_FRP);
    setDetections(DEFAULT_DETECTIONS);
    setLstText(DEFAULT_LST);
    setScan(DEFAULT_SCAN);
    setResult(null);
    setRunError(null);
  };

  const run = async () => {
    if (!formValid || lstHours === null) {
      notify("Fix the highlighted fields before running harmonization.", true);
      return;
    }
    const payload: HarmonizePayload = {
      aggregator_config_hash: config.aggregator_config_hash,
      region: [region],
      date: [date],
      latitude: [lat],
      longitude: [lon],
      cell_lat: [Math.floor(lat)],
      cell_lon: [Math.floor(lon)],
      frp_aqua_mw: [frp],
      detections: [detections],
      lst_aqua_h: [lstHours],
      scan_aqua: [scan],
    };
    setRunning(true);
    setRunError(null);
    setResult(null);
    try {
      const response = await harmonize(payload);
      setResult(response);
      const cell = response.cells[0];
      notify(
        cell?.applicable
          ? `API returned ${response.model}: harmonized value with a ${fmtPct(response.prediction_level, 0)} interval.`
          : `API returned a refusal: ${cell?.reason ?? "outside domain"}. No value was fabricated.`,
        !cell?.applicable,
      );
    } catch (reason) {
      if (reason instanceof ApiError) {
        setRunError(reason);
        notify(`Harmonization refused: ${reason.message}`, true);
      } else {
        notify("Harmonization failed for an unknown reason.", true);
      }
    } finally {
      setRunning(false);
    }
  };

  const cell: HarmonizeCell | undefined = result?.cells[0];
  const regional: RegionalContext | undefined = result?.regional_context[region];

  return (
    <div>
      <PageHeader
        kicker="Primary product"
        title="FRP harmonization"
        lede={
          <>
            Map one Aqua MODIS cell-day to the Suomi-NPP VIIRS 13.6 h reference. Inputs are
            validated at the boundary; the API returns either a calibrated 80% interval or a stated
            refusal. It never fills an unsupported cell with a number.
          </>
        }
        side={
          <>
            <Badge tone="ok">cell-day unit only</Badge>
            <span className="mono tiny muted">POST /harmonize</span>
          </>
        }
      />

      <div className="grid harmonize">
        <Panel title="Input workspace" meta="one 1° cell-day per request">
          <div className="form-grid">
            <div className="field">
              <label htmlFor="h-region">
                Region <span className="req">*</span>
              </label>
              <select id="h-region" value={region} onChange={(event) => setRegion(event.target.value)}>
                {results.gate.domain.regions.map((item) => (
                  <option key={item} value={item}>
                    {humanRegion(item)}
                  </option>
                ))}
              </select>
              <div className="field-hint">Supported training regions only.</div>
            </div>

            <div className="field">
              <label htmlFor="h-date">
                Acquisition date <span className="req">*</span>
              </label>
              <input
                id="h-date"
                type="date"
                min={results.dataset.date_min}
                max={results.dataset.date_max}
                value={date}
                onChange={(event) => setDate(event.target.value)}
              />
              <div className={`field-hint ${dateCovered(date, windowStarts, windowDays) ? "good" : "bad"}`}>
                {dateCovered(date, windowStarts, windowDays)
                  ? "Inside a verified 5-day sampling window."
                  : "Outside the verified windows; the API will refuse."}
              </div>
            </div>

            <div className="field">
              <label htmlFor="h-lat">
                Latitude (°) <span className="req">*</span>
              </label>
              <input
                id="h-lat"
                type="number"
                step="0.0001"
                value={Number.isFinite(lat) ? lat : ""}
                onChange={(event) => setLat(Number(event.target.value))}
              />
              <div className="field-hint">
                floor({Number.isFinite(lat) ? fmtNum(lat, 4) : "—"}) →{" "}
                <b className="text-ink">{snappedLat ?? "—"}</b>
              </div>
            </div>

            <div className="field">
              <label htmlFor="h-lon">
                Longitude (°) <span className="req">*</span>
              </label>
              <input
                id="h-lon"
                type="number"
                step="0.0001"
                value={Number.isFinite(lon) ? lon : ""}
                onChange={(event) => setLon(Number(event.target.value))}
              />
              <div className="field-hint">
                floor({Number.isFinite(lon) ? fmtNum(lon, 4) : "—"}) →{" "}
                <b className="text-ink">{snappedLon ?? "—"}</b>
              </div>
            </div>

            <div className="field wide">
              <label htmlFor="h-frp">
                Aqua FRP sum (MW) <span className="req">*</span>
              </label>
              <div className="range-row">
                <input
                  id="h-frp-range"
                  type="range"
                  min={0}
                  max={1000}
                  value={sliderFromFrp(frp)}
                  onChange={(event) => {
                    const next = frpFromSlider(Number(event.target.value));
                    setFrp(Number(next.toPrecision(5)));
                  }}
                  aria-label="Aqua FRP logarithmic slider"
                />
                <input
                  id="h-frp"
                  type="number"
                  min={0.001}
                  step={0.1}
                  value={Number.isFinite(frp) ? frp : ""}
                  onChange={(event) => setFrp(Number(event.target.value))}
                />
              </div>
              <div className="field-hint">
                Log slider spans 0.001–5,000 MW; direct entry is authoritative. Actual value{" "}
                <b className="text-ink">{fmtMw(frp, 1)}</b>.
              </div>
            </div>

            <div className="field">
              <label htmlFor="h-n">
                Detections <span className="req">*</span>
              </label>
              <input
                id="h-n"
                type="number"
                min={1}
                step={1}
                value={Number.isFinite(detections) ? detections : ""}
                onChange={(event) => setDetections(Number(event.target.value))}
              />
              <div className="field-hint">Aqua pixels in the cell-day.</div>
            </div>

            <div className="field">
              <label htmlFor="h-lst">
                Aqua local solar time <span className="req">*</span>
              </label>
              <input
                id="h-lst"
                type="time"
                step={60}
                value={lstText}
                onChange={(event) => setLstText(event.target.value)}
              />
              <div className={`field-hint ${lstHours === null ? "bad" : ""}`}>
                {lstHours === null
                  ? "Enter a valid HH:MM local solar time."
                  : `${lstFromHours(lstHours)} LST · delay ${fmtSigned(delay ?? 0, 3)} h vs 13.6 h`}
              </div>
            </div>

            <div className="field">
              <label htmlFor="h-scan">
                Aqua scan size (km) <span className="req">*</span>
              </label>
              <input
                id="h-scan"
                type="number"
                min={0.1}
                step={0.01}
                value={Number.isFinite(scan) ? scan : ""}
                onChange={(event) => setScan(Number(event.target.value))}
              />
              <div className="field-hint">FIRMS scan field, matching training.</div>
            </div>

            <div className="field">
              <label>Resolved grid</label>
              <div className="eq" style={{ margin: 0 }}>
                {snappedLat !== null && snappedLon !== null
                  ? `${cellLabel(snappedLat, snappedLon)} · [${snappedLat}, ${snappedLat + 1}) × [${snappedLon}, ${snappedLon + 1})`
                  : "—"}
              </div>
              <div className="field-hint">Snap rule: floor(latitude) × floor(longitude).</div>
            </div>

            <div className="field wide">
              <label>Instrumentation state</label>
              <div className="btn-row">
                <span className="chip">Saturation · not evaluated</span>
                <span className="chip">Plume scattering · not evaluated</span>
                <span className="chip">Canopy occlusion · not evaluated</span>
              </div>
            </div>
          </div>

          <div className="rule" />

          <div className="panel-head" style={{ marginBottom: 8 }}>
            <h3>Live validation guard</h3>
            <span className={`badge ${formValid ? "ok" : "bad"}`}>
              {formValid ? "ready" : `${checklist.filter((item) => !item.ok).length} issue(s)`}
            </span>
          </div>
          <div className="grid two" style={{ gap: 4 }}>
            {checklist.map((item) => (
              <div key={item.label} className="flex items-start gap-2 text-[10.5px] leading-snug">
                <span className={`mt-[2px] flex-none ${item.ok ? "text-[#526B5B]" : "text-[#A33C37]"}`}>
                  {item.ok ? <Check size={11} strokeWidth={3} /> : <X size={11} strokeWidth={3} />}
                </span>
                <div>
                  <div style={{ color: item.ok ? undefined : "#A33C37" }}>{item.label}</div>
                  {!item.ok && <div className="tiny muted">{item.hint}</div>}
                </div>
              </div>
            ))}
          </div>

          <div className="callout neutral mt-sm">
            <span className="callout-title">Pre-flight uses the published gate, not a prediction</span>
            <div className="flex flex-wrap gap-1 mt-1">
              <GuardChip label="delay" ok={delayInDomain} />
              <GuardChip label="scan" ok={scanInDomain} />
              <GuardChip label="region" ok={regionInDomain} />
              <Badge tone={binEntry?.applicable ? "ok" : "bad"}>
                bin {bin ?? "outside"} {binEntry?.applicable ? "supported" : "refused"}
              </Badge>
            </div>
            <div className="tiny muted mt-1">
              Delay {delay === null ? "—" : `${fmtSigned(delay, 3)} h`}; measured domain{" "}
              {fmtNum(results.gate.domain.delay_low, 3)} … {fmtNum(results.gate.domain.delay_high, 3)} h.
              Only POST /harmonize decides the served verdict.
            </div>
          </div>

          <div className="btn-row mt">
            <button type="button" className="btn" onClick={run} disabled={running || !formValid}>
              {running ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
              {running ? "Calling API…" : "Run harmonization"}
            </button>
            <button type="button" className="btn secondary" onClick={reset}>
              <RotateCcw size={13} /> Reset
            </button>
            <span className="tiny muted">
              {running ? "POST /harmonize…" : "Live call · nothing is precomputed in the browser"}
            </span>
          </div>

          <div className="rule" />
          <div className="panel-head" style={{ marginBottom: 8 }}>
            <h3>Actual observations</h3>
            <span className="panel-meta">from the verified pair table</span>
          </div>
          <div className="stack" style={{ gap: 6 }}>
            {results.actual_examples.map((example) => (
              <button
                key={`${example.cell}-${example.date}`}
                type="button"
                className="example-button"
                onClick={() => loadExample(example)}
              >
                <span className="flex items-center justify-between w-full gap-2">
                  <span className="mono strong">{example.cell}</span>
                  <span className="mono text-[10px] text-[#747873]">{example.date}</span>
                </span>
                <span className="text-[10.5px] text-[#747873]">
                  {humanRegion(example.region)} · {fmtMw(example.frp_aqua_mw, 1)} Aqua ·{" "}
                  {example.detections} det. · {fmtNum(example.lst_aqua_h, 2)} h LST
                </span>
                <span className="text-[10px] text-[#B66F4D]">
                  observed SNPP {fmtMw(example.observed_frp_snpp_mw, 1)}
                </span>
              </button>
            ))}
          </div>
          <p className="table-note">
            These are real matched cell-days. Loading one fills the form; the API result is still
            computed live. The observed SNPP value is shown for context, not used as an input.
          </p>
        </Panel>

        <div className="stack">
          <Panel
            title="Result"
            actions={
              cell ? (
                cell.applicable ? (
                  <Badge tone="ok">applicable</Badge>
                ) : (
                  <Badge tone="bad">refused</Badge>
                )
              ) : (
                <Badge tone="none">not run</Badge>
              )
            }
          >
            {!result && !runError && (
              <div className="callout neutral">
                <span className="callout-title">The interval is the primary output</span>
                Submit a cell-day to receive the 80% conformal range and the applicability verdict.
                If the cell is outside the calibrated domain, the API returns null with a reason —
                never a fabricated value.
              </div>
            )}

            {runError && (
              <div className="stack" style={{ gap: 8 }}>
                <Callout tone="bad" title={`API refused this request (HTTP ${runError.status || "—"})`}>
                  {runError.message}
                </Callout>
                {runError.detail != null &&
                  typeof runError.detail === "object" &&
                  Array.isArray((runError.detail as Record<string, unknown>).fields) && (
                    <div className="table-wrap">
                      <table className="data">
                        <thead>
                          <tr>
                            <th>Field</th>
                            <th>Message</th>
                          </tr>
                        </thead>
                        <tbody>
                          {((runError.detail as Record<string, unknown>).fields as Array<Record<string, unknown>>).map(
                            (field, index) => (
                              <tr key={index}>
                                <td className="mono">{String(field.field ?? "request")}</td>
                                <td>{String(field.message ?? "invalid value")}</td>
                              </tr>
                            ),
                          )}
                        </tbody>
                      </table>
                    </div>
                  )}
              </div>
            )}

            {cell && result && (
              <div>
                {cell.applicable &&
                cell.harmonized_frp_mw !== null &&
                cell.interval_lower_mw !== null &&
                cell.interval_upper_mw !== null ? (
                  <>
                    <div className="flex items-baseline justify-between gap-3 mb-2">
                      <div>
                        <div className="eyebrow">Harmonized FRP · {fmtPct(cell.interval_level, 0)} interval</div>
                        <div className="metric-value" style={{ fontSize: 30, marginTop: 4 }}>
                          {fmtMw(cell.harmonized_frp_mw, 1)}
                        </div>
                        <div className="tiny muted">
                          Point estimate is secondary metadata. Read the range first.
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="mono text-[11px]">
                          {fmtSigned(cell.correction_percent, 1)}% correction
                        </div>
                        <div className="tiny muted">model {result.model}</div>
                      </div>
                    </div>

                    <ConformalRange
                      original={cell.original_frp_mw}
                      lower={cell.interval_lower_mw}
                      upper={cell.interval_upper_mw}
                      point={cell.harmonized_frp_mw}
                    />

                    <div className="grid two mt-sm" style={{ gap: 12 }}>
                      <div>
                        <KeyValue
                          rows={[
                            ["Original Aqua FRP", fmtMw(cell.original_frp_mw, 1)],
                            ["Predicted log ratio ỹ", fmtSigned(cell.predicted_log_ratio, 4)],
                            ["Delay vs 13.6 h", `${fmtSigned(cell.delay_h, 3)} h`],
                            ["Delay bin", cell.delay_bin ?? "outside"],
                            ["LST (rendered)", cell.lst_display],
                            ["Resolved cell", cell.cell],
                          ]}
                        />
                      </div>
                      <div>
                        <KeyValue
                          rows={[
                            ["Interval width", fmtMw(cell.interval_width_mw, 1)],
                            ["Conformal quantile", fmtSigned(cell.quantile_log, 4)],
                            ["Calibration pairs", fmtInt(cell.calibration_n)],
                            ["Bin coverage", cell.coverage === null ? "—" : fmtPct(cell.coverage)],
                            ["Interval level", fmtPct(cell.interval_level, 0)],
                            ["Model", `${result.model} · split conformal`],
                          ]}
                        />
                      </div>
                    </div>

                    <div className="flex flex-wrap gap-1 mt-sm">
                      <GuardChip label="delay" ok={cell.delay_in_domain} />
                      <GuardChip label="scan" ok={cell.scan_in_domain} />
                      <GuardChip label="region" ok={cell.region_in_domain} />
                      <Badge tone="ok">calibrated band</Badge>
                    </div>

                    <p className="table-note">
                      The band is wide because cell-day noise is large. It narrows neither by
                      repeating the request nor by ignoring it.
                    </p>
                  </>
                ) : (
                  <>
                    <div className="flex items-start gap-3">
                      <span className="text-[#A33C37] mt-[2px]">
                        <CircleAlert size={22} />
                      </span>
                      <div>
                        <div className="eyebrow" style={{ color: "#A33C37" }}>
                          Applicability verdict
                        </div>
                        <div className="text-[22px] font-semibold leading-tight" style={{ color: "#A33C37" }}>
                          No supported correction
                        </div>
                        <div className="tiny muted">
                          The API returns <span className="mono">null</span>, not a fabricated value.
                        </div>
                      </div>
                    </div>

                    <Callout tone="bad" title={cell.reason ?? "outside domain"} className="mt">
                      <ReasonLanguage code={cell.reason} />
                      {cell.refusal_message && <div className="mt-1">{cell.refusal_message}</div>}
                    </Callout>

                    <div className="grid two mt-sm" style={{ gap: 12 }}>
                      <KeyValue
                        rows={[
                          ["Original Aqua FRP", fmtMw(cell.original_frp_mw, 1)],
                          ["Delay vs 13.6 h", `${fmtSigned(cell.delay_h, 3)} h`],
                          ["Delay bin", cell.delay_bin ?? "outside"],
                          ["LST (rendered)", cell.lst_display],
                        ]}
                      />
                      <KeyValue
                        rows={[
                          ["Calibration pairs", fmtInt(cell.calibration_n)],
                          ["Bin coverage", cell.coverage === null ? "—" : fmtPct(cell.coverage)],
                          ["Resolved cell", cell.cell],
                          ["Model", result.model],
                        ]}
                      />
                    </div>

                    <div className="flex flex-wrap gap-1 mt-sm">
                      <GuardChip label="delay" ok={cell.delay_in_domain} />
                      <GuardChip label="scan" ok={cell.scan_in_domain} />
                      <GuardChip label="region" ok={cell.region_in_domain} />
                      <Badge tone="bad">no number returned</Badge>
                    </div>
                  </>
                )}
              </div>
            )}
          </Panel>

          {regional && (
            <Panel title="Regional performance caution" meta="leave-one-region-out">
              <Callout tone={regional.caution ? "warn" : "neutral"} title={`${humanRegion(region)} · ${regional.available ? "LOGO score" : "unavailable"}`}>
                {regional.available ? (
                  <>
                    H RMSE <span className="mono">{fmtNum(regional.h_rmse, 4)}</span> vs raw baseline{" "}
                    <span className="mono">{fmtNum(regional.raw_rmse, 4)}</span>.{" "}
                    {regional.caution
                      ? "The model is worse than the raw baseline in this region. Do not treat the correction as an improvement here."
                      : "The model improves on the raw baseline in this region, but a regional RMSE is not individual prediction uncertainty."}
                  </>
                ) : (
                  regional.note
                )}
              </Callout>
            </Panel>
          )}

          <Panel
            title="Live replay over real pairs"
            meta="frozen H · every Aqua–SNPP pair from the cleaned CSVs"
            actions={<Badge tone="warn">in-sample replay</Badge>}
          >
            {live ? (
              <>
                <div className="grid two" style={{ gap: 12 }}>
                  <KeyValue
                    rows={[
                      ["Aqua–SNPP pairs", fmtInt(live.n_pairs)],
                      ["Applicable", fmtInt(live.n_applicable)],
                      ["Refused", fmtInt(live.n_refused)],
                      ["Coverage (applicable)", live.coverage === null ? "—" : fmtPct(live.coverage)],
                    ]}
                  />
                  <KeyValue
                    rows={[
                      ["Raw RMSE", fmtNum(live.raw_rmse, 4)],
                      ["Harmonized RMSE", fmtNum(live.harmonized_rmse, 4)],
                      ["Mean correction", live.mean_correction_percent === null ? "—" : `${fmtSigned(live.mean_correction_percent, 1)}%`],
                      ["Model", live.provenance.model],
                    ]}
                  />
                </div>

                <div className="flex flex-wrap gap-1 mt-sm">
                  {Object.entries(live.refusals).map(([reason, count]) => (
                    <Badge key={reason} tone="none">
                      {reason.replaceAll("_", " ")}: {fmtInt(count)}
                    </Badge>
                  ))}
                  <Badge tone="info">{fmtInt(live.coverage_n)} coverage denominator</Badge>
                </div>

                <div className="table-wrap mt-sm">
                  <table className="data">
                    <thead>
                      <tr>
                        <th>Region</th>
                        <th className="num">Pairs</th>
                        <th className="num">Applicable</th>
                        <th className="num">Coverage</th>
                        <th className="num">Raw RMSE</th>
                        <th className="num">H RMSE</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(live.by_region).map(([region, row]) => (
                        <tr key={region}>
                          <td>{humanRegion(region)}</td>
                          <td className="num">{fmtInt(row.n)}</td>
                          <td className="num">{fmtInt(row.applicable)}</td>
                          <td className="num">{row.coverage === null ? "—" : fmtPct(row.coverage)}</td>
                          <td className="num">{fmtNum(row.raw_rmse, 4)}</td>
                          <td className="num">{fmtNum(row.harmonized_rmse, 4)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <p className="table-note">
                  {live.interpretation} The values above are recomputed from the real matched
                  cell-days at service start; they are not a substitute for the grouped CV in{" "}
                  <span className="mono">/results</span>.
                </p>
              </>
            ) : liveError ? (
              <Callout tone="warn" title="Live replay unavailable">
                {liveError}
              </Callout>
            ) : (
              <div className="skeleton" style={{ height: 150 }} />
            )}
          </Panel>

          <Panel title="How this result is calculated" meta="same pure core as batch training">
            <Equation label="log ratio" latex>
              {String.raw`y = \ln\!\left(\frac{\mathrm{FRP}_{\mathrm{Aqua}}}{\mathrm{FRP}_{\mathrm{SNPP}}}\right)`}
            </Equation>
            <Equation label="correction model" latex>
              {String.raw`\hat{y} = c + g\!\left(t_{\mathrm{Aqua}}\right) - g\!\left(13.6\right) + \delta_{\mathrm{region}}`}
            </Equation>
            <Equation label="harmonized value" latex>
              {String.raw`\mathrm{FRP}_{\mathrm{harmonized}} = \mathrm{FRP}_{\mathrm{Aqua}}\,\exp\!\left(-\hat{y}\right)`}
            </Equation>
            <p className="small muted mt-sm">
              The model estimates how far the Aqua value is expected to differ from the SNPP
              reference because of overpass timing relative to 13.6 h, adds a ridge-penalised
              regional offset, and rescales Aqua FRP by the exponential of that estimate. The band
              is a split-conformal 80% interval calibrated by delay bin.
            </p>
            {result && (
              <div className="tiny muted mt-sm mono">
                results {fmtHash(result.provenance.results_sha256)} · model{" "}
                {fmtHash(result.provenance.model_artifact_sha256)} · config{" "}
                {fmtHash(result.provenance.config_hash)} · data {fmtHash(result.provenance.data_hash)}
              </div>
            )}
          </Panel>

          <Panel title="Operational safeguards">
            <ul className="small muted" style={{ paddingLeft: 16 }}>
              <li>Pixel-level or event-level payloads are rejected; the served unit is a 1° cell-day.</li>
              <li>The aggregator config hash must match the training aggregation.</li>
              <li>Scan and delay outside the measured domain are refused.</li>
              <li>Saturation, plume scattering and canopy occlusion stay not evaluated.</li>
              <li>The point estimate is not a guarantee; the conformal interval is the product.</li>
              <li>
                LST is computed as <span className="mono">(UTC + longitude / 15) mod 24</span>; the
                stored integer form is never displayed as a time.
              </li>
            </ul>
          </Panel>
        </div>
      </div>

      <Limitations items={results.limitations} />
    </div>
  );
}
