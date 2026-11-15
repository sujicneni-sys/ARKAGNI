import { useMemo, useRef, useState, type ReactNode } from "react";
import {
  CloudUpload,
  CircleCheck,
  Download,
  FileSpreadsheet,
  Leaf,
  Loader2,
  ShieldCheck,
  Sparkles,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import { useAppData } from "../context/AppData";
import { ErrorPage, LoadingPage } from "../components/States";
import { useToast } from "../components/Toast";
import { Badge, PageHeader, Panel } from "../components/ui";
import { ApiError, analyzeFile, harmonize } from "../lib/api";
import { fmtInt, fmtMw, fmtNum, fmtPct, humanRegion } from "../lib/format";
import {
  REFERENCE_LST_H,
  assignDelayBin,
  lstFromHours,
  parseCell,
} from "../lib/science";
import type { ActualExample, HarmonizeCell, HarmonizeResponse } from "../lib/types";

type Tone = "good" | "warn" | "neutral";

const DEFAULT_REGION = "Southern_Africa";
const DEFAULT_DELAY_H = 1.0;
const DEFAULT_FRP = 180;
const DEFAULT_DETECTIONS = 12;
const DEFAULT_SCAN = 1.3;
const SAMPLE_ROWS = 8;

function mean(values: ReadonlyArray<number>): number | null {
  if (values.length === 0) return null;
  return values.reduce((total, value) => total + value, 0) / values.length;
}

function verdictFor(cells: ReadonlyArray<HarmonizeCell>): {
  tone: Tone;
  title: string;
  body: string;
  icon: ReactNode;
} {
  const applicable = cells.filter((cell) => cell.applicable);
  const coverage = mean(
    cells
      .map((cell) => cell.coverage)
      .filter((value): value is number => typeof value === "number" && Number.isFinite(value)),
  );

  if (applicable.length === 0) {
    return {
      tone: "neutral",
      title: "No correction returned",
      body:
        cells[0]?.refusal_message ??
        "These cells sit outside the measured applicability domain. The system returned a stated refusal instead of a number.",
      icon: <ShieldCheck size={19} strokeWidth={1.9} />,
    };
  }

  if (applicable.length < cells.length) {
    return {
      tone: "warn",
      title: "Partial support",
      body: `${applicable.length} of ${cells.length} cells received a correction. The rest were refused rather than extrapolated.`,
      icon: <TriangleAlert size={19} strokeWidth={1.9} />,
    };
  }

  if (coverage !== null && coverage < 0.8) {
    return {
      tone: "warn",
      title: "Correction with caution",
      body: `All cells are applicable, but measured coverage here is ${fmtPct(
        coverage,
      )} against the 80% nominal level.`,
      icon: <TriangleAlert size={19} strokeWidth={1.9} />,
    };
  }

  return {
    tone: "good",
    title: "Verified correction",
    body:
      "Every cell sits inside the calibrated domain. The band is the measured 80% conformal interval, not a guarantee about future fire behaviour.",
    icon: <CircleCheck size={19} strokeWidth={1.9} />,
  };
}

function ResultView({ result }: { result: HarmonizeResponse }) {
  const cells = result.cells;
  const applicable = cells.filter((cell) => cell.applicable);
  const refused = cells.filter((cell) => !cell.applicable);
  const coverage = mean(
    cells
      .map((cell) => cell.coverage)
      .filter((value): value is number => typeof value === "number" && Number.isFinite(value)),
  );
  const shifts = applicable
    .map((cell) => cell.correction_percent)
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  const meanShift = mean(shifts);
  const harmonized = applicable
    .map((cell) => cell.harmonized_frp_mw)
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  const meanHarmonized = mean(harmonized);
  // Compare like with like: the "from" value must cover the same cells that
  // received a correction, never the refused ones.
  const corrected = applicable.filter(
    (cell) =>
      typeof cell.harmonized_frp_mw === "number" &&
      Number.isFinite(cell.harmonized_frp_mw) &&
      Number.isFinite(cell.original_frp_mw),
  );
  const meanOriginal = mean(corrected.map((cell) => cell.original_frp_mw));
  const verdict = verdictFor(cells);
  const single = cells.length === 1 ? cells[0] : null;
  const lower = single?.interval_lower_mw;
  const upper = single?.interval_upper_mw;

  return (
    <div className="live-result">
      <div className={`live-verdict ${verdict.tone}`}>
        <div className="live-verdict-icon">{verdict.icon}</div>
        <div>
          <div className="live-verdict-title">{verdict.title}</div>
          <p className="live-verdict-body">{verdict.body}</p>
        </div>
      </div>

      <div className="live-hero">
        <div className="live-hero-label">
          {single ? "Harmonized FRP" : "Mean harmonized FRP"}
        </div>
        <div className="live-hero-value">
          {meanHarmonized === null ? "—" : fmtMw(meanHarmonized)}
        </div>
        <div className="live-hero-sub">
          {meanOriginal !== null && meanHarmonized !== null ? (
            <>
              from {fmtMw(meanOriginal)} ·{" "}
              <span className={meanShift !== null && meanShift < 0 ? "live-down" : "live-up"}>
                {meanShift === null ? "—" : `${meanShift > 0 ? "+" : ""}${fmtNum(meanShift, 1)}%`}
              </span>
            </>
          ) : (
            "No value was fabricated for a refused cell."
          )}
        </div>
        {single && lower !== null && upper !== null && (
          <div className="live-interval">
            80% interval <b>{fmtMw(lower)} – {fmtMw(upper)}</b>
          </div>
        )}
      </div>

      <div className="live-stats">
        <div className="live-stat">
          <span className="live-stat-label">Cells scored</span>
          <b>{fmtInt(cells.length)}</b>
        </div>
        <div className="live-stat">
          <span className="live-stat-label">Corrections</span>
          <b>{fmtInt(applicable.length)}</b>
          <span>{refused.length > 0 ? `${fmtInt(refused.length)} refused` : "all applicable"}</span>
        </div>
        <div className="live-stat">
          <span className="live-stat-label">Measured coverage</span>
          <b>{fmtPct(coverage)}</b>
          <span>out-of-fold, 80% nominal</span>
        </div>
      </div>

      {single && (
        <div className="live-detail">
          <div>
            <span>Delay</span>
            <b>{single.delay_h === null ? "—" : `${fmtNum(single.delay_h, 2)} h`}</b>
          </div>
          <div>
            <span>Delay bin</span>
            <b>{single.delay_bin ?? "outside bins"}</b>
          </div>
          <div>
            <span>Cell</span>
            <b>{single.cell}</b>
          </div>
          <div>
            <span>Model</span>
            <b>{result.model}</b>
          </div>
        </div>
      )}

      {cells.length > 1 && (
        <div className="live-chips">
          {cells.slice(0, 6).map((cell, index) => (
            <div
              key={`${cell.cell}-${index}`}
              className={`live-chip ${cell.applicable ? "good" : "neutral"}`}
            >
              <span className="live-chip-region">{humanRegion(cell.region)}</span>
              <b>
                {cell.applicable && cell.harmonized_frp_mw !== null
                  ? fmtMw(cell.harmonized_frp_mw)
                  : "No correction"}
              </b>
              <span className="live-chip-meta">
                {fmtNum(cell.delay_h, 2)} h · {cell.delay_bin ?? "outside"}
              </span>
            </div>
          ))}
          {cells.length > 6 && (
            <div className="live-chip more">+{fmtInt(cells.length - 6)} more</div>
          )}
        </div>
      )}

      {refused.length > 0 && (
        <p className="live-refusal">
          <b>Refusal, not an error.</b>{" "}
          {refused[0].refusal_message ??
            "At least one cell sits outside the calibrated domain, so no correction is returned for it."}
        </p>
      )}

      <p className="live-footnote">
        Scored by the frozen {result.model} release at the{" "}
        {fmtPct(result.prediction_level, 0)} nominal level · pipeline{" "}
        {result.provenance.pipeline_version}.
      </p>
    </div>
  );
}

export function LiveAnalysis() {
  const { results, config, loading, error } = useAppData();
  const { notify } = useToast();
  const inputRef = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [region, setRegion] = useState(DEFAULT_REGION);
  const [delay, setDelay] = useState(DEFAULT_DELAY_H);
  const [frp, setFrp] = useState(DEFAULT_FRP);
  const [detections, setDetections] = useState(DEFAULT_DETECTIONS);
  const [scan, setScan] = useState(DEFAULT_SCAN);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<HarmonizeResponse | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [ranMode, setRanMode] = useState<"file" | "manual" | null>(null);
  const [ranFile, setRanFile] = useState<string | null>(null);

  const sampleRows = useMemo(() => results?.actual_examples ?? [], [results]);

  if (loading && !results) return <LoadingPage />;
  if (error || !results || !config) return <ErrorPage message={error} />;

  const regions = results.gate.domain.regions;
  const activeRegion = regions.includes(region) ? region : (regions[0] ?? DEFAULT_REGION);
  const bounds = results.dataset.region_bounds[activeRegion];
  const centerLat = bounds ? (bounds.lat_min + bounds.lat_max) / 2 : 0;
  const centerLon = bounds ? (bounds.lon_min + bounds.lon_max) / 2 : 0;
  const lstHours = REFERENCE_LST_H + delay;
  const bin = assignDelayBin(delay);
  const manualValid =
    bin !== null &&
    Number.isFinite(frp) &&
    frp > 0 &&
    Number.isInteger(detections) &&
    detections >= 1 &&
    Number.isFinite(scan) &&
    scan > 0 &&
    scan <= 100;

  const pickFile = (candidate: File) => {
    const name = candidate.name.toLowerCase();
    if (!name.endsWith(".csv") && !name.endsWith(".parquet") && !name.endsWith(".pq")) {
      notify("Choose a .csv or .parquet file.", true);
      return;
    }
    setFile(candidate);
    setResult(null);
    setRunError(null);
    setRanMode(null);
  };

  const clearFile = () => {
    setFile(null);
    setResult(null);
    setRunError(null);
    setRanMode(null);
    if (inputRef.current) inputRef.current.value = "";
  };

  const loadSample = () => {
    const examples = sampleRows.slice(0, SAMPLE_ROWS);
    if (examples.length === 0) {
      notify("No verified examples are available in this release.", true);
      return;
    }
    const header =
      "region,frp_aqua_mw,detections,scan_aqua,lst_aqua_h,latitude,longitude,date";
    const rows = examples.map((example: ActualExample) => {
      const coords = parseCell(example.cell);
      return [
        example.region,
        example.frp_aqua_mw,
        example.detections,
        example.scan_aqua,
        example.lst_aqua_h,
        coords ? (coords.lat + 0.5).toFixed(3) : "",
        coords ? (coords.lon + 0.5).toFixed(3) : "",
        example.date,
      ].join(",");
    });
    const sample = new File([`${header}\n${rows.join("\n")}`], "verified_sample.csv", {
      type: "text/csv",
    });
    setFile(sample);
    setResult(null);
    setRunError(null);
    notify(`Loaded ${rows.length} real Aqua–SNPP pairs from the verified release.`);
  };

  const downloadTemplate = () => {
    const csv = [
      "region,frp_aqua_mw,detections,scan_aqua,delay_h,latitude,longitude,date",
      "Southern_Africa,180,12,1.3,1.0,-12.5,25.5,",
    ].join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "arkagni_live_analysis_template.csv";
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const run = async () => {
    if (!file && !manualValid) {
      notify("Fix the single-cell fields or choose a file first.", true);
      return;
    }
    setRunning(true);
    setRunError(null);
    try {
      const response = file
        ? await analyzeFile(file)
        : await harmonize({
            aggregator_config_hash: config.aggregator_config_hash,
            region: [activeRegion],
            latitude: [centerLat],
            longitude: [centerLon],
            frp_aqua_mw: [frp],
            detections: [detections],
            lst_aqua_h: [lstHours],
            scan_aqua: [scan],
          });
      setResult(response);
      setRanMode(file ? "file" : "manual");
      setRanFile(file?.name ?? null);
      const refused = response.cells.filter((cell) => !cell.applicable).length;
      notify(
        refused === 0
          ? `Scored ${response.cells.length} cell${response.cells.length === 1 ? "" : "s"} through the frozen pipeline.`
          : `${refused} of ${response.cells.length} cells returned a stated refusal.`,
        false,
      );
    } catch (reason) {
      setResult(null);
      setRunError(
        reason instanceof ApiError ? reason.message : "The live analysis request failed.",
      );
    } finally {
      setRunning(false);
    }
  };

  return (
    <div>
      <PageHeader
        kicker="Public tester"
        title="Live analysis"
        lede={
          <>
            Upload a small CSV or Parquet batch, or move one cell-day by hand. Every request goes
            through the same frozen harmonization pipeline as the API, and refusals stay refusals.
          </>
        }
        side={
          <>
            <Badge tone="ok">CSV · Parquet · single cell</Badge>
            <span className="mono tiny muted">POST /live-analysis</span>
          </>
        }
      />

      <div className="grid live-grid">
        <Panel title="Your input" meta="one cell-day or a small batch">
          <div
            className={`dropzone${dragging ? " dragging" : ""}${file ? " has-file" : ""}`}
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              const dropped = event.dataTransfer.files?.[0];
              if (dropped) pickFile(dropped);
            }}
            onClick={() => {
              if (!file) inputRef.current?.click();
            }}
          >
            <input
              ref={inputRef}
              type="file"
              accept=".csv,.parquet,.pq"
              onChange={(event) => {
                const chosen = event.target.files?.[0];
                if (chosen) pickFile(chosen);
              }}
              aria-label="Upload a CSV or Parquet file"
              style={{ display: "none" }}
            />
            {file ? (
              <>
                <div className="dropzone-icon has-file">
                  <FileSpreadsheet size={20} strokeWidth={1.8} />
                </div>
                <div className="dropzone-copy">
                  <b>{file.name}</b>
                  <span>
                    {(file.size / 1024).toFixed(file.size > 102_400 ? 0 : 1)} kB · ready to score
                  </span>
                </div>
                <button
                  type="button"
                  className="btn ghost small"
                  onClick={(event) => {
                    event.stopPropagation();
                    clearFile();
                  }}
                  aria-label="Remove uploaded file"
                >
                  <Trash2 size={13} /> Remove
                </button>
              </>
            ) : (
              <>
                <div className="dropzone-icon">
                  <CloudUpload size={20} strokeWidth={1.8} />
                </div>
                <div className="dropzone-copy">
                  <b>Drop a CSV or Parquet file here</b>
                  <span>or click to browse · up to 2,000 rows</span>
                </div>
              </>
            )}
          </div>

          <div className="live-or">
            <span>{file ? "single-cell fields are ignored while a file is loaded" : "or test a single cell-day"}</span>
          </div>

          <div className="form-grid">
            <div className="field">
              <label htmlFor="live-region">Region</label>
              <select
                id="live-region"
                value={activeRegion}
                onChange={(event) => setRegion(event.target.value)}
              >
                {regions.map((item) => (
                  <option key={item} value={item}>
                    {humanRegion(item)}
                  </option>
                ))}
              </select>
              <div className="field-hint">Only the four measured study regions are accepted.</div>
            </div>

            <div className="field">
              <label htmlFor="live-delay">Delay from 13.6 h reference</label>
              <div className="range-row">
                <input
                  id="live-delay"
                  type="range"
                  min={-2.5}
                  max={3.4}
                  step={0.05}
                  value={delay}
                  onChange={(event) => setDelay(Number(event.target.value))}
                />
                <input
                  type="number"
                  step={0.05}
                  min={-2.5}
                  max={3.4}
                  value={delay}
                  onChange={(event) => setDelay(Number(event.target.value))}
                  aria-label="Delay hours"
                />
              </div>
              <div className="field-hint">
                LST {lstFromHours(lstHours)} · bin {bin ?? "outside the calibrated bins"}
              </div>
            </div>

            <div className="field">
              <label htmlFor="live-frp">Aqua FRP (MW)</label>
              <input
                id="live-frp"
                type="number"
                min={0.001}
                step={0.1}
                value={Number.isFinite(frp) ? frp : ""}
                onChange={(event) => setFrp(Number(event.target.value))}
              />
              <div className="field-hint">Cell-day FRP sum, not a single pixel.</div>
            </div>

            <div className="field">
              <label htmlFor="live-detections">Detections</label>
              <input
                id="live-detections"
                type="number"
                min={1}
                step={1}
                value={Number.isFinite(detections) ? detections : ""}
                onChange={(event) => setDetections(Math.round(Number(event.target.value)))}
              />
              <div className="field-hint">Aqua pixels contributing to the cell-day.</div>
            </div>

            <div className="field">
              <label htmlFor="live-scan">Scan (km)</label>
              <input
                id="live-scan"
                type="number"
                min={0.001}
                max={100}
                step={0.1}
                value={Number.isFinite(scan) ? scan : ""}
                onChange={(event) => setScan(Number(event.target.value))}
              />
              <div className="field-hint">Training domain: {fmtNum(results.gate.domain.scan_low, 2)}–{fmtNum(results.gate.domain.scan_high, 2)} km.</div>
            </div>

            <div className="field">
              <label>Location used for the feature row</label>
              <div className="live-coord">
                {fmtNum(centerLat, 2)}°, {fmtNum(centerLon, 2)}°
                <span>region centroid</span>
              </div>
            </div>
          </div>

          <div className="btn-row live-actions">
            <button
              type="button"
              className="btn"
              onClick={() => void run()}
              disabled={running || (!file && !manualValid)}
            >
              {running ? <Loader2 size={14} className="spinner" /> : <Sparkles size={14} />}
              {running ? "Scoring…" : file ? "Analyze file" : "Analyze cell-day"}
            </button>
            <button type="button" className="btn secondary" onClick={loadSample} disabled={running}>
              Use verified sample
            </button>
            <button type="button" className="btn ghost" onClick={downloadTemplate}>
              <Download size={13} /> Template
            </button>
          </div>

          {runError && (
            <div className="live-error">
              <TriangleAlert size={15} />
              <span>{runError}</span>
            </div>
          )}

          <p className="live-footnote">
            Required columns: <code className="mono">region</code>,{" "}
            <code className="mono">frp_aqua_mw</code>,{" "}
            <code className="mono">detections</code>,{" "}
            <code className="mono">scan_aqua</code>, and{" "}
            <code className="mono">lst_aqua_h</code>, <code className="mono">delay_h</code>, or{" "}
            <code className="mono">acquisition_time_utc</code> with{" "}
            <code className="mono">longitude</code>. Extra columns are ignored.
          </p>
        </Panel>

        <Panel
          title="Result"
          meta={
            result
              ? ranMode === "file"
                ? (ranFile ?? "uploaded batch")
                : "single cell-day"
              : "nothing scored yet"
          }
        >
          {result ? (
            <ResultView result={result} />
          ) : (
            <div className="live-empty">
              <div className="live-empty-icon">
                <Leaf size={22} strokeWidth={1.7} />
              </div>
              <h3>Calm, measured, at a glance</h3>
              <p>
                The result panel stays quiet until there is a verified answer to show. Refusals
                appear as a soft blue note, not a failure.
              </p>
              <div className="live-empty-list">
                <span>One cell-day or a small batch</span>
                <span>Same frozen model as the API</span>
                <span>Refusals stay refusals</span>
              </div>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
