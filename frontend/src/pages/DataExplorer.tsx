import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Search } from "lucide-react";
import { useAppData } from "../context/AppData";
import { ErrorPage, LoadingPage } from "../components/States";
import { FlagCell } from "../components/FlagCell";
import { LstRange } from "../components/LstRange";
import { SimpleBars } from "../components/charts";
import {
  Badge,
  Callout,
  EmptyState,
  Limitations,
  Metric,
  MetricStrip,
  PageHeader,
  Panel,
} from "../components/ui";
import { getIngestion, getObservations, getObservationsSummary } from "../lib/api";
import { fmtHash, fmtInt, fmtNum, fmtPct, humanRegion, MONTHS, monthIndex, yearOf } from "../lib/format";
import type { IngestionReport, ObservationsPage, ObservationsSummary } from "../lib/types";

const SATELLITE_LABEL: Record<string, string> = {
  Aqua: "Aqua MODIS",
  Terra: "Terra MODIS",
  N: "Suomi-NPP",
  N20: "NOAA-20",
};

const SATELLITE_COLOR: Record<string, string> = {
  Aqua: "#B66F4D",
  Terra: "#C77B43",
  N: "#526B5B",
  N20: "#788B91",
};

const STATUS_ORDER = ["validated", "flagged", "excluded"] as const;

const STATUS_META: Record<
  (typeof STATUS_ORDER)[number],
  { tone: "ok" | "warn" | "bad"; label: string; color: string }
> = {
  validated: { tone: "ok", label: "Validated", color: "#526B5B" },
  flagged: { tone: "warn", label: "Flagged", color: "#8D611D" },
  excluded: { tone: "bad", label: "Excluded", color: "#A33C37" },
};

const YEARS = [2021, 2022, 2023, 2024, 2025];

function SortHeader({
  label,
  column,
  active,
  direction,
  numeric = false,
  onClick,
}: {
  label: string;
  column: string;
  active: string;
  direction: "asc" | "desc";
  numeric?: boolean;
  onClick: (column: string) => void;
}) {
  const isActive = active === column;
  return (
    <th className={numeric ? "num" : ""}>
      <button
        type="button"
        onClick={() => onClick(column)}
        className="inline-flex items-center gap-1 uppercase tracking-[0.09em] text-[9.5px] font-bold"
        style={{ color: isActive ? "#292D2B" : undefined }}
      >
        {label}
        {isActive ? (
          direction === "asc" ? (
            <ChevronUp size={10} />
          ) : (
            <ChevronDown size={10} />
          )
        ) : null}
      </button>
    </th>
  );
}

export function DataExplorer() {
  const { results, loading, error } = useAppData();
  const [summary, setSummary] = useState<ObservationsSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [ingestion, setIngestion] = useState<IngestionReport | null>(results?.live_ingestion ?? null);
  const [ingestionError, setIngestionError] = useState<string | null>(null);
  const [data, setData] = useState<ObservationsPage | null>(null);
  const [obsLoading, setObsLoading] = useState(true);
  const [obsError, setObsError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [region, setRegion] = useState("");
  const [satellite, setSatellite] = useState("");
  const [year, setYear] = useState("");
  const [status, setStatus] = useState("");
  const [daynight, setDaynight] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState("date");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  useEffect(() => {
    let live = true;
    getIngestion()
      .then((payload) => {
        if (live) setIngestion(payload);
      })
      .catch((reason: unknown) => {
        if (live) setIngestionError(reason instanceof Error ? reason.message : "Ingestion manifest unavailable");
      });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    let live = true;
    getObservationsSummary()
      .then((payload) => {
        if (live) setSummary(payload);
      })
      .catch((reason: unknown) => {
        if (live) setSummaryError(reason instanceof Error ? reason.message : "Explorer summary unavailable");
      });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(1);
    }, 340);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => {
    let live = true;
    setObsLoading(true);
    setObsError(null);
    getObservations({
      region,
      satellite,
      year,
      status,
      daynight,
      search,
      sortBy,
      sortDir,
      page,
      pageSize,
    })
      .then((payload) => {
        if (live) setData(payload);
      })
      .catch((reason: unknown) => {
        if (live) setObsError(reason instanceof Error ? reason.message : "Observations unavailable");
      })
      .finally(() => {
        if (live) setObsLoading(false);
      });
    return () => {
      live = false;
    };
  }, [region, satellite, year, status, daynight, search, sortBy, sortDir, page, pageSize]);

  const calendar = useMemo(
    () => yearsCalendar(summary?.active_dates ?? []),
    [summary],
  );

  if (loading && !results) return <LoadingPage />;
  if (error || !results) return <ErrorPage message={error} />;

  const rowsBySatellite = results.dataset.rows_by_satellite;
  const modis = (rowsBySatellite.Aqua ?? 0) + (rowsBySatellite.Terra ?? 0);

  const satelliteData = Object.entries(rowsBySatellite)
    .map(([key, value]) => ({
      label: SATELLITE_LABEL[key] ?? key,
      value,
      display: fmtInt(value),
      color: SATELLITE_COLOR[key] ?? "#526B5B",
    }))
    .sort((a, b) => b.value - a.value);

  const regionData = Object.entries(results.dataset.rows_by_region)
    .map(([key, value]) => ({
      label: humanRegion(key),
      value,
      display: fmtInt(value),
      color: "#526B5B",
    }))
    .sort((a, b) => b.value - a.value);

  const yearData = Object.entries(results.dataset.rows_by_year)
    .sort(([a], [b]) => Number(a) - Number(b))
    .map(([key, value]) => ({
      label: key,
      value,
      display: fmtInt(value),
      color: Number(key) === 2022 ? "#C77B43" : "#8FA793",
    }));

  const onSort = (column: string) => {
    if (sortBy === column) {
      setSortDir((current) => (current === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(column);
      setSortDir("desc");
    }
    setPage(1);
  };

  const resetFilters = () => {
    setRegion("");
    setSatellite("");
    setYear("");
    setStatus("");
    setDaynight("");
    setSearchInput("");
    setPage(1);
  };

  return (
    <div>
      <PageHeader
        kicker="Composition, provenance and validation"
        title="Data explorer"
        lede={
          <>
            Every row is loaded from the frozen L1 canonical table through the read-only API. Times
            are shown in UTC and local solar time with the derivation visible. Filters update the
            table, not a mock dataset.
          </>
        }
        side={<Badge tone="info">read-only endpoint</Badge>}
      />

      <MetricStrip>
        <Metric
          label="Total observations"
          value={fmtInt(results.dataset.rows)}
          hint="L1 canonical rows · no rows deleted"
        />
        <Metric
          label="Validated rows"
          value={fmtInt(results.dataset.validated_rows)}
          hint={
            <span className="metric-query">
              <code>type = 0</code>
              <span aria-hidden>·</span>
              <code>FRP &gt; 0</code>
              <span aria-hidden>·</span>
              <code>day</code>
            </span>
          }
        />
        <Metric
          label="MODIS observations"
          value={fmtInt(modis)}
          hint={`Aqua ${fmtInt(rowsBySatellite.Aqua)} · Terra ${fmtInt(rowsBySatellite.Terra)}`}
        />
        <Metric
          label="VIIRS NOAA-20"
          value={fmtInt(rowsBySatellite.N20)}
          hint="audit comparator · not the target"
        />
        <Metric
          label="VIIRS Suomi-NPP"
          value={fmtInt(rowsBySatellite.N)}
          hint="harmonization reference sensor"
        />
      </MetricStrip>

      {ingestionError && (
        <div className="mt">
          <Callout tone="warn" title="Ingestion manifest unavailable">
            {ingestionError} The table below still uses the live observations endpoint.
          </Callout>
        </div>
      )}

      {ingestion && (
        <Panel
          className="mt"
          title="Source ingestion"
          meta="hash-verified source files"
          actions={
            <Badge tone={ingestion.verification.passed ? "ok" : "bad"}>
              {ingestion.verification.passed ? "verified" : "mismatch"}
            </Badge>
          }
        >
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Sensor</th>
                  <th>Source file</th>
                  <th className="num">Rows</th>
                  <th className="num">Size</th>
                  <th>SHA-256</th>
                </tr>
              </thead>
              <tbody>
                {ingestion.sources.map((source) => (
                  <tr key={source.sensor_key}>
                    <td className="mono">{source.sensor_key}</td>
                    <td>
                      <span className="mono">{source.filename}</span>
                      <span className="tiny muted block">{source.path}</span>
                    </td>
                    <td className="num">{fmtInt(source.rows)}</td>
                    <td className="num">{fmtNum(source.bytes / 1024 / 1024, 1)} MB</td>
                    <td className="mono tiny">{fmtHash(source.sha256)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap items-center gap-2 mt-sm">
            <Badge tone={ingestion.hash_verified ? "ok" : "bad"}>
              data hash {ingestion.hash_verified ? "matches" : "differs"}
            </Badge>
            <Badge tone="info">
              {Object.keys(ingestion.verification.checks).length} release checks passed
            </Badge>
            <span className="mono tiny muted">{ingestion.data_hash}</span>
          </div>
        </Panel>
      )}

      {summaryError && (
        <div className="mt">
          <Callout tone="warn" title="Explorer summary unavailable">
            {summaryError} The observation table below still calls the live endpoint directly.
          </Callout>
        </div>
      )}

      <div className="grid three mt">
        <Panel title="Satellite distribution" meta="L1 rows">
          <SimpleBars data={satelliteData} height={205} integer leftWidth={92} />
        </Panel>
        <Panel title="Regional distribution" meta="study envelopes">
          <SimpleBars data={regionData} height={205} integer leftWidth={78} />
        </Panel>
        <Panel title="Year distribution" meta="sampling windows only">
          <SimpleBars data={yearData} height={205} integer leftWidth={40} />
        </Panel>
      </div>

      <div className="grid side mt">
        <Panel
          title="Satellite-year local solar time"
          meta="median with p05–p95 range · rendered HH:MM"
        >
          {summary ? (
            <LstRange rows={summary.satellite_year_lst} />
          ) : (
            <div className="skeleton" style={{ height: 240 }} />
          )}
        </Panel>

        <div className="stack">
          <Panel title="Validation state" meta="flags, not deletions">
            {summary ? (
              (() => {
                const counts = summary.status_counts;
                const total = Object.values(counts).reduce((sum, count) => sum + count, 0);
                const day = summary.daynight_counts.D ?? 0;
                const night = summary.daynight_counts.N ?? 0;
                return (
                  <>
                    <div className="status-total">
                      <div className="metric-label">Total rows</div>
                      <div className="status-total-value mono">{fmtInt(total)}</div>
                    </div>
                    <div className="status-rows">
                      {STATUS_ORDER.map((key) => {
                        const value = counts[key] ?? 0;
                        const meta = STATUS_META[key];
                        const share = total ? value / total : 0;
                        return (
                          <div key={key} className="status-row">
                            <div className="status-row-head">
                              <Badge tone={meta.tone}>{meta.label}</Badge>
                              <span className="status-count mono">{fmtInt(value)}</span>
                              <span className="status-share mono">{fmtPct(share)}</span>
                            </div>
                            <div className="status-bar">
                              <div
                                className="status-bar-fill"
                                style={{ width: `${share * 100}%`, background: meta.color }}
                              />
                            </div>
                            <div className="status-def">{summary.status_definition[key] ?? ""}</div>
                          </div>
                        );
                      })}
                    </div>
                    <div className="rule" />
                    <div className="status-row-head">
                      <Badge tone="plain">Day / night</Badge>
                      <span className="status-count mono">D {fmtInt(day)}</span>
                      <span className="status-share mono">N {fmtInt(night)}</span>
                    </div>
                    <p className="table-note">
                      Night is flagged, never dropped. Saturation, plume scattering and canopy
                      occlusion occupy reserved bits 3–5 and remain <b>not evaluated</b>.
                    </p>
                  </>
                );
              })()
            ) : (
              <div className="skeleton" style={{ height: 190 }} />
            )}
          </Panel>

          <Panel title="FRP by sensor" meta="raw cell-pixel values">
            {summary ? (
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Sensor</th>
                      <th className="num">n</th>
                      <th className="num">Median</th>
                      <th className="num">p95</th>
                      <th className="num">Max</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.frp_by_satellite.map((row) => (
                      <tr key={row.satellite}>
                        <td>{SATELLITE_LABEL[row.satellite] ?? row.satellite}</td>
                        <td className="num">{fmtInt(row.n)}</td>
                        <td className="num">{fmtNum(row.median_mw, 2)}</td>
                        <td className="num">{fmtNum(row.p95_mw, 2)}</td>
                        <td className="num">{fmtNum(row.max_mw, 1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="skeleton" style={{ height: 130 }} />
            )}
          </Panel>
        </div>
      </div>

      <Panel
        className="mt"
        title="Active ingest calendar"
        meta={`${summary?.active_dates.length ?? 0} active days · ${summary?.windows.length ?? 0} windows × ${summary?.window_days ?? 5} days`}
      >
        <div className="calendar-grid">
          <div />
          {MONTHS.map((month) => (
            <div key={month} className="calendar-month">
              {month}
            </div>
          ))}
          {calendar.map((row) => (
            <div key={row.year} className="contents">
              <div className="calendar-year">{row.year}</div>
              {row.months.map((month) => (
                <div
                  key={`${row.year}-${month.label}`}
                  className="calendar-cell"
                  data-count={month.count}
                  title={
                    month.count > 0
                      ? `${month.count} active day(s) in ${month.label} ${row.year}: ${month.dates.join(", ")}`
                      : `No sampling window in ${month.label} ${row.year}`
                  }
                />
              ))}
            </div>
          ))}
        </div>
        <div className="flex items-center gap-3 mt-sm flex-wrap">
          <span className="tiny muted">No sampling window</span>
          {[1, 2, 3, 4, 5].map((count) => (
            <span key={count} className="flex items-center gap-1 tiny muted">
              <i className="swatch" data-count={count} style={{ background: calendarColor(count) }} />
              {count}
            </span>
          ))}
          <span className="tiny muted ml-auto">
            Five 5-day windows per year: January (10–14), August (01–05), September (01–05).
          </span>
        </div>

        {summary && summary.sparse_notes.length > 0 && (
          <div className="stack mt-sm" style={{ gap: 8 }}>
            {summary.sparse_notes.map((note) => (
              <Callout key={`${note.year}-${note.region}`} tone="bad" title={`Calibration interrupt · ${note.year} · ${humanRegion(note.region)}`}>
                {note.message}
              </Callout>
            ))}
          </div>
        )}
        <p className="table-note">
          Zero matched pairs is not zero raw observations. In 2022, Amazon and Southern Africa have
          no matched Aqua–SNPP pairs while raw observations still exist; the calendar marks the
          ingest window, not calibration coverage.
        </p>
      </Panel>

      <Panel
        className="mt"
        title="Observation records"
        meta={
          data
            ? `${fmtInt(data.total)} matching rows · page ${data.page} of ${data.pages}`
            : "loading actual records"
        }
      >
        <div className="grid" style={{ gridTemplateColumns: "repeat(6, minmax(0, 1fr))", gap: 10 }}>
          <div className="field">
            <label htmlFor="f-region">Region</label>
            <select
              id="f-region"
              value={region}
              onChange={(event) => {
                setRegion(event.target.value);
                setPage(1);
              }}
            >
              <option value="">All regions</option>
              {results.gate.domain.regions.map((item) => (
                <option key={item} value={item}>
                  {humanRegion(item)}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="f-satellite">Satellite</label>
            <select
              id="f-satellite"
              value={satellite}
              onChange={(event) => {
                setSatellite(event.target.value);
                setPage(1);
              }}
            >
              <option value="">All satellites</option>
              <option value="Aqua">Aqua</option>
              <option value="Terra">Terra</option>
              <option value="N">Suomi-NPP</option>
              <option value="N20">NOAA-20</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="f-year">Year</label>
            <select
              id="f-year"
              value={year}
              onChange={(event) => {
                setYear(event.target.value);
                setPage(1);
              }}
            >
              <option value="">All years</option>
              {YEARS.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="f-status">Validation</label>
            <select
              id="f-status"
              value={status}
              onChange={(event) => {
                setStatus(event.target.value);
                setPage(1);
              }}
            >
              <option value="">All states</option>
              <option value="validated">Validated</option>
              <option value="flagged">Flagged</option>
              <option value="excluded">Excluded</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="f-daynight">Day / night</label>
            <select
              id="f-daynight"
              value={daynight}
              onChange={(event) => {
                setDaynight(event.target.value);
                setPage(1);
              }}
            >
              <option value="">Both</option>
              <option value="D">Day</option>
              <option value="N">Night</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="f-search">Search</label>
            <div className="relative">
              <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-[#747873]" />
              <input
                id="f-search"
                type="search"
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder="Observation ID or cell"
                style={{ paddingLeft: 26 }}
              />
            </div>
          </div>
        </div>

        <div className="split mt-sm">
          <span className="tiny muted">
            {obsLoading ? "Loading actual records…" : data ? `${fmtInt(data.total)} rows match the current filter` : ""}
          </span>
          <div className="btn-row">
            <button type="button" className="btn secondary small" onClick={resetFilters}>
              Reset filters
            </button>
            <select
              className="select"
              style={{ width: 92, minHeight: 28, padding: "4px 6px", fontSize: 11 }}
              value={pageSize}
              onChange={(event) => {
                setPageSize(Number(event.target.value));
                setPage(1);
              }}
              aria-label="Rows per page"
            >
              {[25, 50, 100].map((size) => (
                <option key={size} value={size}>
                  {size} / page
                </option>
              ))}
            </select>
          </div>
        </div>

        {obsError && (
          <Callout tone="bad" title="Observation endpoint unavailable" className="mt-sm">
            {obsError}
          </Callout>
        )}

        <div className="table-wrap mt-sm">
          <table className="data">
            <thead>
              <tr>
                <SortHeader label="Observation ID" column="observation_id" active={sortBy} direction={sortDir} onClick={onSort} />
                <SortHeader label="Satellite" column="satellite" active={sortBy} direction={sortDir} onClick={onSort} />
                <SortHeader label="Region" column="region" active={sortBy} direction={sortDir} onClick={onSort} />
                <th>Cell</th>
                <SortHeader label="Lat" column="latitude" active={sortBy} direction={sortDir} numeric onClick={onSort} />
                <SortHeader label="Lon" column="longitude" active={sortBy} direction={sortDir} numeric onClick={onSort} />
                <SortHeader label="Date" column="date" active={sortBy} direction={sortDir} onClick={onSort} />
                <SortHeader label="UTC" column="utc" active={sortBy} direction={sortDir} onClick={onSort} />
                <SortHeader label="LST" column="lst" active={sortBy} direction={sortDir} numeric onClick={onSort} />
                <SortHeader label="FRP (MW)" column="frp" active={sortBy} direction={sortDir} numeric onClick={onSort} />
                <SortHeader label="Scan (km)" column="scan" active={sortBy} direction={sortDir} numeric onClick={onSort} />
                <SortHeader label="Flags / status" column="status" active={sortBy} direction={sortDir} onClick={onSort} />
              </tr>
            </thead>
            <tbody>
              {obsLoading && !data && (
                <tr>
                  <td colSpan={12} className="muted">
                    Loading actual records…
                  </td>
                </tr>
              )}
              {!obsLoading && data && data.rows.length === 0 && (
                <tr>
                  <td colSpan={12}>
                    <EmptyState title="No rows match this filter">
                      The API returned zero matching observations. Reset the filters to return to the
                      measured sample.
                    </EmptyState>
                  </td>
                </tr>
              )}
              {data?.rows.map((row) => (
                <tr key={row.observation_id}>
                  <td className="mono text-[10.5px]">{row.observation_id}</td>
                  <td className="whitespace-nowrap">{SATELLITE_LABEL[row.satellite] ?? row.satellite}</td>
                  <td className="whitespace-nowrap">{humanRegion(row.region)}</td>
                  <td className="mono text-[10.5px]">{row.cell}</td>
                  <td className="num">{fmtNum(row.latitude, 3)}</td>
                  <td className="num">{fmtNum(row.longitude, 3)}</td>
                  <td className="mono text-[10.5px]">{row.date}</td>
                  <td className="mono text-[10.5px]">{row.utc}</td>
                  <td className="num" title={`${row.lst_derivation}; display ${row.lst_display}`}>
                    {row.lst_display}
                  </td>
                  <td className="num">{fmtNum(row.frp_mw, 2)}</td>
                  <td className="num">{fmtNum(row.scan_km, 2)}</td>
                  <td>
                    <FlagCell flags={row.flags_uint8} status={row.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="split mt-sm">
          <span className="tiny muted">
            {data ? `Page ${data.page} of ${data.pages} · ${fmtInt(data.total)} total` : "—"}
          </span>
          <div className="btn-row">
            <button
              type="button"
              className="btn secondary small"
              disabled={!data || page <= 1}
              onClick={() => setPage((current) => Math.max(1, current - 1))}
            >
              <ChevronLeft size={12} /> Previous
            </button>
            <button
              type="button"
              className="btn secondary small"
              disabled={!data || page >= data.pages}
              onClick={() => setPage((current) => current + 1)}
            >
              Next <ChevronRight size={12} />
            </button>
          </div>
        </div>

        <p className="table-note">
          LST = (UTC hours + longitude / 15) mod 24. The backend stores zero-padded HHMM; this table
          never displays the padded integer form. Flagged means zero FRP or night; excluded means
          type ≠ 0 or negative FRP. The row remains in the table in every case.
        </p>
      </Panel>

      <Limitations items={results.limitations} />
    </div>
  );
}

function yearsCalendar(activeDates: string[]) {
  return YEARS.map((year) => ({
    year,
    months: MONTHS.map((label, index) => {
      const dates = activeDates.filter(
        (date) => yearOf(date) === year && monthIndex(date) === index,
      );
      return { label, count: dates.length, dates };
    }),
  }));
}

function calendarColor(count: number): string {
  if (count <= 0) return "#FAF8F2";
  if (count === 1) return "#dfe7db";
  if (count === 2) return "#c4d2bc";
  if (count === 3) return "#a8bba2";
  if (count === 4) return "#8aa487";
  return "#526B5B";
}
