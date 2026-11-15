/* PyroHarmonize dashboard.  Reads hashed results only; harmonization calls the live API. */
(() => {
  "use strict";

  const state = {
    results: null,
    version: null,
    config: null,
    page: "overview",
    obsPage: 1,
    obsPageSize: 25,
    obsTotal: 0,
    apiOnline: false,
    searchTimer: null,
  };

  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#39;");
  const nf = new Intl.NumberFormat("en-US");
  const fmtInt = (value) => Number.isFinite(Number(value)) ? nf.format(Math.round(Number(value))) : "—";
  const fmtNum = (value, digits = 3) => Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : "—";
  const fmtPct = (value, digits = 1) => Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(digits)}%` : "—";
  const fmtSigned = (value, digits = 3) => {
    if (!Number.isFinite(Number(value))) return "—";
    const number = Number(value);
    return `${number >= 0 ? "+" : ""}${number.toFixed(digits)}`;
  };
  const fmtMw = (value) => Number.isFinite(Number(value)) ? `${nf.format(Math.round(Number(value)))} MW` : "—";

  function badge(kind, text, symbol) {
    const symbolMap = { ok: "✓", warn: "⚠", bad: "✕", none: "○", info: "◐" };
    return `<span class="badge ${kind}"><span class="sym">${symbol || symbolMap[kind] || "○"}</span> ${esc(text)}</span>`;
  }

  function toast(message, bad = false) {
    const node = $("toast");
    node.textContent = message;
    node.className = `toast show${bad ? " bad" : ""}`;
    window.clearTimeout(toast._timer);
    toast._timer = window.setTimeout(() => { node.className = "toast"; }, 4200);
  }

  async function fetchJSON(url, fallbackUrl) {
    try {
      const response = await fetch(url, { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error(`${url} returned ${response.status}`);
      return await response.json();
    } catch (error) {
      if (fallbackUrl) {
        const response = await fetch(fallbackUrl);
        if (!response.ok) throw error;
        return await response.json();
      }
      throw error;
    }
  }

  const titles = {
    overview: ["Satellite Fire Data Harmonization", "Understanding and correcting FRP differences between Aqua MODIS and Suomi-NPP VIIRS."],
    explorer: ["Data Explorer", "Inspect the actual L1 records, provenance, composition and validation states."],
    harmonization: ["FRP Harmonization", "Map an Aqua cell-day to the SNPP 13.6 h reference, or receive a stated refusal."],
    uncertainty: ["Prediction Reliability", "Conformal coverage, interval behaviour and the applicability domain."],
    models: ["Model Performance", "Compare all seven correction approaches without declaring an unsupported winner."],
    audit: ["Scientific Audit", "Evidence, assumptions, weaknesses and pending work."],
    methodology: ["Technical Methodology", "A readable account of the complete pipeline and its limits."],
  };

  function navigate(page) {
    if (!titles[page]) return;
    state.page = page;
    document.querySelectorAll(".page").forEach((section) => {
      section.hidden = section.id !== `page-${page}`;
    });
    document.querySelectorAll(".nav button").forEach((button) => {
      button.classList.toggle("active", button.dataset.page === page);
    });
    $("page-title").textContent = titles[page][0];
    $("page-desc").textContent = titles[page][1];
    window.location.hash = page === "overview" ? "" : page;
    window.scrollTo({ top: 0, behavior: "smooth" });
    if (page === "explorer") loadObservations();
  }

  /* ---------------------------------------------------------------- charts */
  function chartSvg(width, height, body, label) {
    return `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(label)}" preserveAspectRatio="xMidYMid meet">${body}</svg>`;
  }

  function hbarChart(items, { width = 560, row = 28, labelWidth = 118, pad = 12, color = "var(--sage)", valueFmt = fmtNum } = {}) {
    const height = pad * 2 + row * items.length + 18;
    const max = Math.max(0, ...items.map((item) => Number(item.value) || 0));
    const right = width - 16;
    let body = "";
    items.forEach((item, index) => {
      const y = pad + index * row;
      const value = Number(item.value) || 0;
      const w = max > 0 ? Math.max(1, (value / max) * (right - labelWidth - 112)) : 0;
      const fill = item.color || color;
      body += `<text x="0" y="${y + 13}" class="label">${esc(item.label)}</text>`;
      body += `<rect x="${labelWidth}" y="${y + 3}" width="${w}" height="${row - 9}" rx="1" fill="${fill}"></rect>`;
      body += `<text x="${labelWidth + w + 6}" y="${y + 13}" class="value">${esc(item.display ?? valueFmt(value))}</text>`;
      if (item.note) body += `<text x="${right}" y="${y + 13}" text-anchor="end" class="label">${esc(item.note)}</text>`;
    });
    return chartSvg(width, height, body, "Horizontal bar chart");
  }

  function coverageChart(containerId, bins) {
    const labels = Object.keys(bins);
    const width = 620, height = 300, left = 42, right = 14, top = 26, bottom = 54;
    const plotW = width - left - right, plotH = height - top - bottom;
    const x = (i) => left + (plotW / labels.length) * (i + 0.5);
    const barW = Math.min(54, plotW / labels.length * 0.55);
    const y = (v) => top + plotH * (1 - v);
    let body = "";
    [0, 0.2, 0.4, 0.6, 0.8, 1].forEach((v) => {
      body += `<line class="gridline" x1="${left}" x2="${width - right}" y1="${y(v)}" y2="${y(v)}"></line>`;
      body += `<text x="${left - 7}" y="${y(v) + 3}" text-anchor="end" class="label">${Math.round(v * 100)}%</text>`;
    });
    body += `<line class="ref" x1="${left}" x2="${width - right}" y1="${y(0.8)}" y2="${y(0.8)}"></line>`;
    body += `<text class="ref-label" x="${width - right}" y="${y(0.8) - 6}" text-anchor="end">80% nominal</text>`;
    labels.forEach((label, i) => {
      const row = bins[label];
      const value = Number(row.coverage);
      const fill = Number.isFinite(value) && value >= 0.7 ? "var(--sage)" : "var(--fire)";
      if (Number.isFinite(value)) {
        body += `<rect class="bar" x="${x(i) - barW / 2}" y="${y(value)}" width="${barW}" height="${Math.max(1, top + plotH - y(value))}" fill="${fill}" rx="1"></rect>`;
        body += `<text x="${x(i)}" y="${y(value) - 5}" text-anchor="middle" class="value">${fmtPct(value)}</text>`;
      } else {
        body += `<text x="${x(i)}" y="${top + plotH / 2}" text-anchor="middle" class="label">unavailable</text>`;
      }
      body += `<text x="${x(i)}" y="${height - 24}" text-anchor="middle" class="label">${esc(label)}</text>`;
      body += `<text x="${x(i)}" y="${height - 10}" text-anchor="middle" class="label">n=${fmtInt(row.n)}</text>`;
    });
    body += `<line class="axis" x1="${left}" x2="${width - right}" y1="${top + plotH}" y2="${top + plotH}"></line>`;
    $(containerId).innerHTML = chartSvg(width, height, body, "Conformal coverage by delay bin");
  }

  function groupedBiasChart(containerId, bins) {
    const labels = Object.keys(bins);
    const width = 620, height = 300, left = 44, right = 14, top = 24, bottom = 54;
    const plotW = width - left - right, plotH = height - top - bottom;
    const values = labels.flatMap((label) => [Number(bins[label].raw_bias) || 0, Number(bins[label].corrected_bias) || 0]);
    const low = Math.min(-0.1, ...values) - 0.05;
    const high = Math.max(0.1, ...values) + 0.05;
    const y = (v) => top + plotH * ((high - v) / (high - low));
    const groupW = plotW / labels.length;
    const barW = Math.min(30, groupW * 0.32);
    let body = "";
    [0, 0.25, 0.5, 0.75, 1].forEach((fraction) => {
      const v = low + (high - low) * fraction;
      body += `<line class="gridline" x1="${left}" x2="${width - right}" y1="${y(v)}" y2="${y(v)}"></line>`;
      body += `<text x="${left - 7}" y="${y(v) + 3}" text-anchor="end" class="label">${v.toFixed(2)}</text>`;
    });
    body += `<line class="axis" x1="${left}" x2="${width - right}" y1="${y(0)}" y2="${y(0)}"></line>`;
    labels.forEach((label, i) => {
      const center = left + groupW * (i + 0.5);
      const raw = Number(bins[label].raw_bias) || 0;
      const corrected = Number(bins[label].corrected_bias) || 0;
      const zero = y(0);
      body += `<rect x="${center - barW - 1}" y="${Math.min(zero, y(raw))}" width="${barW}" height="${Math.abs(zero - y(raw))}" fill="var(--slate)" rx="1"></rect>`;
      body += `<rect x="${center + 1}" y="${Math.min(zero, y(corrected))}" width="${barW}" height="${Math.abs(zero - y(corrected))}" fill="var(--sage)" rx="1"></rect>`;
      body += `<text x="${center}" y="${height - 24}" text-anchor="middle" class="label">${esc(label)}</text>`;
      body += `<text x="${center}" y="${height - 10}" text-anchor="middle" class="label">n=${fmtInt(bins[label].n)}</text>`;
    });
    $(containerId).innerHTML = chartSvg(width, height, body, "Raw and corrected bias by delay bin");
  }

  function pairingChart(containerId, pairing) {
    const rows = [
      ["Cell-day sum", pairing.cell_day_sum],
      ["Near-coincident", pairing.near_coincident],
    ];
    const width = 580, height = 190, left = 128, right = 22, top = 34, rowH = 54;
    const all = rows.flatMap(([, row]) => [Number(row.ci_low), Number(row.ci_high), Number(row.slope_per_hour)]).filter(Number.isFinite);
    const low = Math.min(-0.35, ...all) - 0.1;
    const high = Math.max(0.6, ...all) + 0.1;
    const x = (v) => left + ((v - low) / (high - low)) * (width - left - right);
    let body = `<line class="gridline" x1="${left}" x2="${width - right}" y1="22" y2="22"></line>`;
    [-0.25, 0, 0.25, 0.5].forEach((v) => {
      if (v < low || v > high) return;
      body += `<line class="gridline" x1="${x(v)}" x2="${x(v)}" y1="22" y2="${height - 22}"></line>`;
      body += `<text x="${x(v)}" y="${height - 7}" text-anchor="middle" class="label">${v.toFixed(2)}</text>`;
    });
    body += `<line class="ref" x1="${x(0)}" x2="${x(0)}" y1="18" y2="${height - 22}"></line>`;
    body += `<text class="ref-label" x="${x(0) + 3}" y="14">zero</text>`;
    rows.forEach(([label, row], i) => {
      const y = top + i * rowH;
      const slope = Number(row.slope_per_hour);
      const ciLow = Number(row.ci_low);
      const ciHigh = Number(row.ci_high);
      body += `<text x="0" y="${y + 4}" class="label">${esc(label)}</text>`;
      if (Number.isFinite(ciLow) && Number.isFinite(ciHigh)) {
        body += `<line class="ci" x1="${x(ciLow)}" x2="${x(ciHigh)}" y1="${y}" y2="${y}"></line>`;
        body += `<line class="ci-cap" x1="${x(ciLow)}" x2="${x(ciLow)}" y1="${y - 5}" y2="${y + 5}"></line>`;
        body += `<line class="ci-cap" x1="${x(ciHigh)}" x2="${x(ciHigh)}" y1="${y - 5}" y2="${y + 5}"></line>`;
        body += `<circle class="point" cx="${x(slope)}" cy="${y}" r="3.5"></circle>`;
        body += `<text x="${x(ciHigh) + 6}" y="${y + 4}" class="value">${fmtSigned(slope, 3)}/h</text>`;
      } else {
        body += `<text x="${left}" y="${y + 4}" class="label">unavailable</text>`;
      }
    });
    body += `<text x="${width - right}" y="12" text-anchor="end" class="label">slope (ln per hour)</text>`;
    $(containerId).innerHTML = chartSvg(width, height, body, "Pairing sensitivity slopes with 95 percent intervals");
  }

  function trendChart(containerId, trend) {
    const years = Object.keys(trend.yearly_frp || {}).map(Number).sort((a, b) => a - b);
    if (years.length < 3) {
      $(containerId).innerHTML = `<div class="result-empty">Trend unavailable: fewer than three years.</div>`;
      return;
    }
    const base = Number(trend.yearly_frp[String(years[0])]);
    const values = years.map((year) => ((Number(trend.yearly_frp[String(year)]) / base) - 1) * 100);
    const slope = Number(trend.naive_slope_percent_per_year);
    const ciLow = Number(trend.ci_low_percent);
    const ciHigh = Number(trend.ci_high_percent);
    const meanYear = years.reduce((a, b) => a + b, 0) / years.length;
    const trendAt = (year) => ((Math.pow(1 + slope / 100, year - years[0])) - 1) * 100;
    const trendLow = (year) => ((Math.pow(1 + ciLow / 100, year - years[0])) - 1) * 100;
    const trendHigh = (year) => ((Math.pow(1 + ciHigh / 100, year - years[0])) - 1) * 100;
    const width = 620, height = 300, left = 48, right = 18, top = 24, bottom = 42;
    const plotW = width - left - right, plotH = height - top - bottom;
    const allY = [...values, 0, ...years.map(trendLow), ...years.map(trendHigh)];
    const low = Math.min(...allY) - 4;
    const high = Math.max(...allY) + 4;
    const x = (year) => left + ((year - years[0]) / (years[years.length - 1] - years[0] || 1)) * plotW;
    const y = (value) => top + plotH * ((high - value) / (high - low));
    let body = "";
    [low, (low + high) / 2, high].forEach((v) => {
      body += `<line class="gridline" x1="${left}" x2="${width - right}" y1="${y(v)}" y2="${y(v)}"></line>`;
      body += `<text x="${left - 7}" y="${y(v) + 3}" text-anchor="end" class="label">${v.toFixed(0)}%</text>`;
    });
    body += `<line class="axis" x1="${left}" x2="${width - right}" y1="${y(0)}" y2="${y(0)}"></line>`;
    const band = years.map((year) => `${x(year)},${y(trendHigh(year))}`).concat([...years].reverse().map((year) => `${x(year)},${y(trendLow(year))}`)).join(" ");
    body += `<polygon class="band" points="${band}"></polygon>`;
    body += `<polyline fill="none" stroke="var(--slate)" stroke-width="1.6" points="${years.map((year) => `${x(year)},${y(trendAt(year))}`).join(" ")}"></polyline>`;
    values.forEach((value, i) => {
      body += `<circle class="point" cx="${x(years[i])}" cy="${y(value)}" r="3.6"></circle>`;
      body += `<text x="${x(years[i])}" y="${y(value) - 8}" text-anchor="middle" class="value">${fmtSigned(value, 1)}%</text>`;
      body += `<text x="${x(years[i])}" y="${height - 18}" text-anchor="middle" class="label">${years[i]}</text>`;
    });
    body += `<text x="${width - right}" y="${height - 4}" text-anchor="end" class="label">change vs ${years[0]} · annual validated FRP</text>`;
    $(containerId).innerHTML = chartSvg(width, height, body, "Annual FRP change with trend confidence ribbon") +
      `<div class="chart-legend"><span><i class="swatch" style="background:var(--fire)"></i> annual total</span><span><i class="swatch" style="background:var(--sage-soft)"></i> 95% trend band</span><span><i class="swatch" style="background:var(--slate)"></i> naive trend</span></div>`;
  }

  function regionMap(bounds, counts) {
    const entries = Object.entries(bounds || {});
    if (!entries.length) return `<div class="result-empty">Region bounds unavailable.</div>`;
    const width = 680, height = 360, left = 46, right = 18, top = 22, bottom = 34;
    const lats = entries.flatMap(([, b]) => [Number(b.lat_min), Number(b.lat_max)]);
    const lons = entries.flatMap(([, b]) => [Number(b.lon_min), Number(b.lon_max)]);
    const latMin = Math.min(...lats) - 4, latMax = Math.max(...lats) + 4;
    const lonMin = Math.min(...lons) - 4, lonMax = Math.max(...lons) + 4;
    const x = (lon) => left + ((lon - lonMin) / (lonMax - lonMin)) * (width - left - right);
    const y = (lat) => top + ((latMax - lat) / (latMax - latMin)) * (height - top - bottom);
    let body = "";
    for (let lon = Math.ceil(lonMin / 20) * 20; lon <= lonMax; lon += 20) {
      body += `<line class="graticule" x1="${x(lon)}" x2="${x(lon)}" y1="${top}" y2="${height - bottom}"></line>`;
      body += `<text x="${x(lon)}" y="${height - 14}" text-anchor="middle" class="label">${lon}°</text>`;
    }
    for (let lat = Math.ceil(latMin / 20) * 20; lat <= latMax; lat += 20) {
      body += `<line class="graticule" x1="${left}" x2="${width - right}" y1="${y(lat)}" y2="${y(lat)}"></line>`;
      body += `<text x="${left - 7}" y="${y(lat) + 3}" text-anchor="end" class="label">${lat}°</text>`;
    }
    Object.entries(bounds).forEach(([region, b]) => {
      const x0 = x(Number(b.lon_min)), x1 = x(Number(b.lon_max));
      const y0 = y(Number(b.lat_max)), y1 = y(Number(b.lat_min));
      const cls = region.toLowerCase().includes("amazon") ? "amazon" : region.toLowerCase().includes("australia") ? "australia" : region.toLowerCase().includes("california") ? "california" : "";
      body += `<rect class="region ${cls}" x="${x0}" y="${y0}" width="${Math.max(3, x1 - x0)}" height="${Math.max(3, y1 - y0)}"><title>${esc(region)}: ${fmtInt(counts[region])} observations</title></rect>`;
      const labelX = Math.min(width - right - 100, Math.max(left + 4, x0 + 4));
      const labelY = Math.max(top + 12, y0 - 4);
      body += `<text x="${labelX}" y="${labelY}" class="region-label">${esc(region.replaceAll("_", " "))}</text>`;
      body += `<text x="${labelX}" y="${labelY + 11}" class="region-sub">${fmtInt(counts[region])} rows</text>`;
    });
    return chartSvg(width, height, body, "Region-level map of study areas").replace(
      'class="chart"',
      'class="chart map"',
    );
  }

  /* ------------------------------------------------------------ overview */
  function renderOverview() {
    const r = state.results;
    const dataset = r.dataset;
    const pairs = r.pairs;
    const coverage = r.uncertainty.overall_coverage;
    document.querySelectorAll("#page-overview [data-bind='rows']").forEach((n) => { n.textContent = fmtInt(dataset.rows); });
    document.querySelectorAll("#page-overview [data-bind='pairs']").forEach((n) => { n.textContent = fmtInt(pairs.count); });
    document.querySelectorAll("#page-overview [data-bind='regions']").forEach((n) => { n.textContent = fmtInt(dataset.regions); });
    document.querySelectorAll("#page-overview [data-bind='coverage']").forEach((n) => { n.textContent = fmtPct(coverage); });
    document.querySelectorAll("#page-overview [data-bind='date-range']").forEach((n) => { n.textContent = `${dataset.date_min} to ${dataset.date_max}`; });

    const late = r.gate.bins["(2, 3.5]"];
    const amazon = r.models.loyo.Amazon;
    const findings = [
      {
        tone: "ok",
        label: "measured",
        title: `Overall conformal coverage is ${fmtPct(coverage)}`,
        body: "Measured against an 80% nominal level with the honest nested estimate. The interval is the primary product; the point estimate is secondary.",
      },
      {
        tone: "bad",
        label: "refused",
        title: "The late-delay bin is refused",
        body: `The (2, 3.5] h bin holds ${fmtInt(late.calibration_n)} calibration pairs and ${fmtPct(late.coverage)} coverage, below the ${Number(r.gate.coverage_floor).toFixed(2)} floor. The API returns an explicit refusal instead of extrapolating.`,
      },
      {
        tone: "ok",
        label: "measured",
        title: `H lowers grouped-CV RMSE from ${fmtNum(r.models.grouped_cv.B0.rmse, 4)} to ${fmtNum(r.models.grouped_cv.H.rmse, 4)} ln`,
        body: "Fold = whole 5-day sampling window. Lower error is evidence of better agreement with SNPP, not proof of accuracy against an independent reference.",
      },
      {
        tone: "warn",
        label: "caution",
        title: "Amazon transfer is worse than raw",
        body: `Leave-one-region-out RMSE is H ${fmtNum(amazon.H.rmse, 3)} vs raw ${fmtNum(amazon.B0.rmse, 3)} ln on ${fmtInt(amazon.n)} pairs. The correction is not an improvement there.`,
      },
      {
        tone: "warn",
        label: "caution",
        title: "The pairing definition flips the sign",
        body: `Cell-day-sum slope ${r.audit.pairing_sensitivity.cell_day_sum.slope_per_hour.toFixed(3)} h⁻¹ (CI includes zero) vs near-coincident +${r.audit.pairing_sensitivity.near_coincident.slope_per_hour.toFixed(3)} h⁻¹ (CI excludes zero). The pairing choice must accompany every delay claim.`,
      },
      {
        tone: "bad",
        label: "refused",
        title: "Terra is out of regime",
        body: `Delay mean ${fmtNum(r.audit.terra_extrapolation.delay_mean_h, 2)} h. H RMSE ${fmtNum(r.audit.terra_extrapolation.h_rmse, 3)} vs raw ${fmtNum(r.audit.terra_extrapolation.raw_rmse, 3)} ln on ${fmtInt(r.audit.terra_extrapolation.n)} pairs. The model is not validated for Terra.`,
      },
    ];
    $("key-findings").innerHTML = findings.map((finding) => `
      <div class="finding">
        ${badge(finding.tone, finding.label)}
        <div>
          <div class="finding-title">${esc(finding.title)}</div>
          <div class="finding-body">${esc(finding.body)}</div>
        </div>
      </div>`).join("");

    const stages = [
      ["L1 frozen inputs", "verified hashes"],
      ["L2 flags + LST", "no deletes"],
      ["1° cell-days", "aggregation"],
      ["Aqua–SNPP pairing", "6,313 pairs"],
      ["Models B0–PR", "grouped CV"],
      ["Conformal + gate", "refuse unsupported"],
      ["FastAPI", "same pure core"],
      ["Dashboard", "hashed results"],
    ];
    $("workflow").innerHTML = stages.map(([name, note], i) =>
      `<div class="split" style="padding:5px 0;border-bottom:1px solid #efede6"><span><span class="mono tiny muted">${String(i + 1).padStart(2, "0")}</span> ${esc(name)}</span><span class="small muted">${esc(note)}</span></div>`
    ).join("");

    $("region-map").innerHTML = regionMap(dataset.region_bounds, dataset.rows_by_region);
    const satelliteItems = Object.entries(dataset.rows_by_satellite).map(([label, value]) => ({
      label, value, display: `${fmtInt(value)} · ${fmtPct(value / dataset.rows)}`,
    }));
    $("composition-chart").innerHTML = hbarChart(satelliteItems, { width: 540, valueFmt: fmtInt });

    const bins = r.audit.bias_by_bin;
    const delayItems = Object.entries(bins).map(([label, row]) => ({
      label, value: row.n, display: `n=${fmtInt(row.n)} · raw ${fmtSigned(row.raw_bias, 2)}`,
      color: label === "(2, 3.5]" ? "var(--fire)" : "var(--sage)",
    }));
    $("delay-support-chart").innerHTML = hbarChart(delayItems, { width: 540, labelWidth: 92, valueFmt: fmtInt });
    renderLimitations("overview-limitations");
  }

  /* ----------------------------------------------------------- explorer */
  function renderExplorer() {
    const r = state.results;
    const dataset = r.dataset;
    document.querySelectorAll("#page-explorer [data-bind='rows']").forEach((n) => { n.textContent = fmtInt(dataset.rows); });
    document.querySelectorAll("#page-explorer [data-bind='modis']").forEach((n) => { n.textContent = fmtInt((dataset.rows_by_satellite.Aqua || 0) + (dataset.rows_by_satellite.Terra || 0)); });
    document.querySelectorAll("#page-explorer [data-bind='modis-split']").forEach((n) => { n.textContent = `Aqua ${fmtInt(dataset.rows_by_satellite.Aqua)} · Terra ${fmtInt(dataset.rows_by_satellite.Terra)}`; });
    document.querySelectorAll("#page-explorer [data-bind='n20']").forEach((n) => { n.textContent = fmtInt(dataset.rows_by_satellite.N20); });
    document.querySelectorAll("#page-explorer [data-bind='snpp']").forEach((n) => { n.textContent = fmtInt(dataset.rows_by_satellite.N); });
    document.querySelectorAll("#page-explorer [data-bind='rows']").forEach((n) => { n.textContent = fmtInt(dataset.rows); });

    const satItems = Object.entries(dataset.rows_by_satellite).map(([label, value]) => ({
      label, value, display: fmtInt(value), note: fmtPct(value / dataset.rows),
    }));
    $("chart-satellite").innerHTML = hbarChart(satItems, { width: 360, row: 24, labelWidth: 50, valueFmt: fmtInt });

    const regionItems = Object.entries(dataset.rows_by_region).map(([label, value]) => ({
      label: label.replaceAll("_", " "), value, display: fmtInt(value), note: fmtPct(value / dataset.rows),
    }));
    $("chart-region").innerHTML = hbarChart(regionItems, { width: 360, row: 24, labelWidth: 104, valueFmt: fmtInt });

    const yearItems = Object.entries(dataset.rows_by_year).map(([label, value]) => ({
      label, value, display: fmtInt(value),
    }));
    $("chart-year").innerHTML = hbarChart(yearItems, { width: 360, row: 24, labelWidth: 42, valueFmt: fmtInt });

    const regionSelect = $("f-region");
    regionSelect.innerHTML = `<option value="">All regions</option>` + Object.keys(dataset.rows_by_region).map((region) => `<option value="${esc(region)}">${esc(region.replaceAll("_", " "))}</option>`).join("");
    const yearSelect = $("f-year");
    yearSelect.innerHTML = `<option value="">All years</option>` + Object.keys(dataset.rows_by_year).sort().map((year) => `<option value="${esc(year)}">${esc(year)}</option>`).join("");
    $("f-region").onchange = () => { state.obsPage = 1; loadObservations(); };
    $("f-satellite").onchange = () => { state.obsPage = 1; loadObservations(); };
    $("f-year").onchange = () => { state.obsPage = 1; loadObservations(); };
    $("f-status").onchange = () => { state.obsPage = 1; loadObservations(); };
    $("f-daynight").onchange = () => { state.obsPage = 1; loadObservations(); };
    $("f-search").oninput = () => {
      window.clearTimeout(state.searchTimer);
      state.searchTimer = window.setTimeout(() => { state.obsPage = 1; loadObservations(); }, 280);
    };
    $("obs-prev").onclick = () => { if (state.obsPage > 1) { state.obsPage -= 1; loadObservations(); } };
    $("obs-next").onclick = () => { if (state.obsPage * state.obsPageSize < state.obsTotal) { state.obsPage += 1; loadObservations(); } };
    renderLimitations("explorer-limitations");
    loadObservations();
  }

  async function loadObservations() {
    if (!state.results) return;
    const params = new URLSearchParams({
      page: String(state.obsPage),
      page_size: String(state.obsPageSize),
    });
    const values = {
      region: $("f-region").value,
      satellite: $("f-satellite").value,
      year: $("f-year").value,
      status: $("f-status").value,
      daynight: $("f-daynight").value,
      search: $("f-search").value.trim(),
    };
    Object.entries(values).forEach(([key, value]) => { if (value) params.set(key, value); });
    const body = $("obs-body");
    body.innerHTML = `<tr><td colspan="12" class="loading">Loading actual records…</td></tr>`;
    try {
      const payload = await fetchJSON(`/observations?${params.toString()}`);
      state.obsTotal = payload.total;
      $("obs-total").textContent = `${fmtInt(payload.total)} matching rows`;
      $("obs-page-info").textContent = payload.total === 0
        ? "No records match this filter combination."
        : `Page ${payload.page} · showing ${payload.rows.length} of ${fmtInt(payload.total)}`;
      $("obs-prev").disabled = payload.page <= 1;
      $("obs-next").disabled = payload.page * payload.page_size >= payload.total;
      if (!payload.rows.length) {
        body.innerHTML = `<tr><td colspan="12"><div class="result-empty" style="border:0">No records match these filters. The filter is working; the intersection is empty. Try a different region, year or status.</div></td></tr>`;
      } else {
        body.innerHTML = payload.rows.map((row) => {
          const cls = row.status === "validated" ? "ok" : row.status === "flagged" ? "warn" : "bad";
          return `<tr>
            <td class="mono tiny">${esc(row.observation_id)}</td>
            <td>${esc(row.satellite)}</td>
            <td>${esc(row.region.replaceAll("_", " "))}</td>
            <td class="mono">${esc(row.cell)}</td>
            <td class="num">${fmtNum(row.latitude, 4)}</td>
            <td class="num">${fmtNum(row.longitude, 4)}</td>
            <td class="nowrap">${esc(row.date)}</td>
            <td class="mono">${esc(row.utc)}</td>
            <td class="num">${fmtNum(row.lst, 3)}</td>
            <td class="num">${fmtNum(row.frp_mw, 2)}</td>
            <td class="num">${fmtNum(row.scan_km, 2)}</td>
            <td>${badge(cls, row.status)}</td>
          </tr>`;
        }).join("");
      }
      const year = values.year;
      const region = values.region;
      const note = $("explorer-note");
      if (year === "2022" && (region === "Amazon" || region === "Southern_Africa")) {
        note.hidden = false;
        note.innerHTML = `<b>Calibration notice.</b> 2022 contributes only one 5-day sampling window in this dataset (from 10 January). This region has zero matched Aqua–SNPP calibration pairs for 2022; raw observations may still exist below, and zero pairs is not the same as zero observations.`;
      } else {
        note.hidden = true;
      }
    } catch (error) {
      body.innerHTML = `<tr><td colspan="12"><div class="result-empty" style="border:0">API unavailable. The Data Explorer reads real records from the live service; it does not substitute a mock table.<br><span class="tiny mono">${esc(error.message)}</span></div></td></tr>`;
      $("obs-total").textContent = "API unavailable";
    }
  }

  /* ------------------------------------------------------ harmonization */
  function parseCell(cell) {
    const match = /^([NS])(\d{2})([EW])(\d{3})$/.exec(cell || "");
    if (!match) return null;
    const lat = (match[1] === "S" ? -1 : 1) * Number(match[2]) + 0.5;
    const lon = (match[3] === "W" ? -1 : 1) * Number(match[4]) + 0.5;
    return { lat, lon };
  }

  function cellLabel(lat, lon) {
    const latFloor = Math.floor(lat);
    const lonFloor = Math.floor(lon);
    const latPart = `${latFloor >= 0 ? "N" : "S"}${String(Math.abs(latFloor)).padStart(2, "0")}`;
    const lonPart = `${lonFloor >= 0 ? "E" : "W"}${String(Math.abs(lonFloor)).padStart(3, "0")}`;
    return `${latPart}${lonPart}`;
  }

  function updateSnap() {
    const lat = Number($("h-lat").value);
    const lon = Number($("h-lon").value);
    if (Number.isFinite(lat) && Number.isFinite(lon)) {
      $("h-snap").textContent = `Resolved cell ${cellLabel(lat, lon)} · output is the cell-day aggregate`;
      $("h-cell-label").textContent = `${cellLabel(lat, lon)} · 1° cell`;
    } else {
      $("h-snap").textContent = "Resolved cell —";
      $("h-cell-label").textContent = "—";
    }
  }

  function frpFromRange() {
    const t = Number($("h-frp-range").value) / 1000;
    const min = Math.log(0.1), max = Math.log(5000);
    return Math.exp(min + t * (max - min));
  }

  function rangeFromFrp() {
    const value = Math.max(0.1, Math.min(5000, Number($("h-frp").value) || 0.1));
    const min = Math.log(0.1), max = Math.log(5000);
    $("h-frp-range").value = String(Math.round(((Math.log(value) - min) / (max - min)) * 1000));
  }

  function renderHarmonization() {
    const r = state.results;
    const regionSelect = $("h-region");
    regionSelect.innerHTML = r.gate.domain.regions.map((region) => `<option value="${esc(region)}">${esc(region.replaceAll("_", " "))}</option>`).join("");
    regionSelect.value = r.gate.domain.regions.includes("Southern_Africa") ? "Southern_Africa" : r.gate.domain.regions[0];
    const dateInput = $("h-date");
    dateInput.min = r.dataset.date_min;
    dateInput.max = r.dataset.date_max;
    dateInput.value = r.dataset.window_starts?.[0] || r.dataset.date_min;
    $("h-date-hint").textContent = `Verified window starts: ${(r.dataset.window_starts || []).join(", ")}.`;

    $("h-lat").oninput = updateSnap;
    $("h-lon").oninput = updateSnap;
    $("h-frp-range").oninput = () => {
      $("h-frp").value = frpFromRange().toFixed(1);
      $("h-frp-hint").textContent = `Actual value: ${frpFromRange().toFixed(1)} MW. Display scaling only; the calculation uses MW.`;
    };
    $("h-frp").oninput = () => {
      rangeFromFrp();
      $("h-frp-hint").textContent = `Actual value: ${Number($("h-frp").value || 0).toFixed(1)} MW. Direct entry is authoritative.`;
    };
    $("h-run").onclick = runHarmonization;
    $("h-reset").onclick = resetHarmonization;
    updateSnap();
    rangeFromFrp();

    const examples = r.actual_examples || [];
    $("h-examples").innerHTML = examples.map((example, index) => {
      const coords = parseCell(example.cell) || { lat: 0, lon: 0 };
      return `<button class="btn secondary small-btn" data-example="${index}" style="text-align:left;justify-content:flex-start">
        <span class="mono">${esc(example.cell)}</span> · ${esc(example.region.replaceAll("_", " "))} · ${esc(example.date)} · ${fmtMw(example.frp_aqua_mw)} · ${example.detections} det. · ${fmtNum(example.lst_aqua_h, 2)} h
        <span class="muted tiny">(observed SNPP ${fmtMw(example.observed_frp_snpp_mw)}; Aqua cell ${fmtNum(coords.lat, 1)}, ${fmtNum(coords.lon, 1)})</span>
      </button>`;
    }).join("");
    document.querySelectorAll("[data-example]").forEach((button) => {
      button.onclick = () => {
        const example = examples[Number(button.dataset.example)];
        const coords = parseCell(example.cell) || { lat: 0, lon: 0 };
        $("h-region").value = example.region;
        $("h-date").value = example.date;
        $("h-lat").value = String(coords.lat);
        $("h-lon").value = String(coords.lon);
        $("h-frp").value = String(Number(example.frp_aqua_mw).toFixed(1));
        rangeFromFrp();
        $("h-n").value = String(example.detections);
        const hours = Math.floor(Number(example.lst_aqua_h));
        const minutes = Math.round((Number(example.lst_aqua_h) - hours) * 60);
        $("h-lst").value = `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
        $("h-scan").value = String(Number(example.scan_aqua).toFixed(2));
        updateSnap();
        $("h-status").textContent = "Actual observation loaded. Run to call the API.";
      };
    });
    renderLimitations("harm-limitations");
  }

  function resetHarmonization() {
    $("h-region").value = "Southern_Africa";
    $("h-date").value = state.results.dataset.window_starts?.[0] || state.results.dataset.date_min;
    $("h-lat").value = "-12.3456";
    $("h-lon").value = "25.6789";
    $("h-frp").value = "180";
    $("h-n").value = "12";
    $("h-lst").value = "14:54";
    $("h-scan").value = "1.3";
    rangeFromFrp();
    updateSnap();
    $("h-result").hidden = true;
    $("h-empty").hidden = false;
    $("h-applicability").className = "badge none";
    $("h-applicability").innerHTML = `<span class="sym">○</span> Not run`;
    $("h-regional-panel").hidden = true;
    $("h-status").textContent = "Ready. Calls the live POST /harmonize.";
  }

  function dateCovered(date) {
    const windows = state.results.dataset.window_starts || [];
    const days = Number(state.results.dataset.window_days || 5);
    const target = new Date(`${date}T00:00:00`);
    return windows.some((start) => {
      const begin = new Date(`${start}T00:00:00`);
      const end = new Date(begin.getTime() + days * 86400000);
      return target >= begin && target < end;
    });
  }

  function reasonText(reason) {
    const text = {
      coverage_below_floor: "The delay bin's honest coverage is below the 0.70 floor. The data does not support a correction there.",
      insufficient_calibration_pairs: "Fewer than 40 out-of-fold calibration pairs exist for this delay bin.",
      delay_outside_calibrated_range: "The delay lies outside the measured 1st–99th percentile training domain.",
      scan_out_of_range: "The Aqua scan value lies outside the measured 1st–99th percentile training domain.",
      region_not_in_training: "The region is not one of the four training regions.",
      calibrated: "The interval is calibrated per delay bin from out-of-fold residuals. The band is the primary output; the point estimate is secondary.",
    };
    return text[reason] || String(reason || "Refused by the applicability gate.");
  }

  async function runHarmonization() {
    const status = $("h-status");
    const region = $("h-region").value;
    const date = $("h-date").value;
    const lat = Number($("h-lat").value);
    const lon = Number($("h-lon").value);
    const frp = Number($("h-frp").value);
    const detections = Number($("h-n").value);
    const lstText = $("h-lst").value;
    const scan = Number($("h-scan").value);
    if (!region) return toast("Select a supported region.", true);
    if (!date || !dateCovered(date)) return toast("The acquisition date is outside the verified 5-day windows.", true);
    if (!Number.isFinite(lat) || lat < -90 || lat > 90 || !Number.isFinite(lon) || lon < -180 || lon > 180) return toast("Latitude or longitude is outside the valid range.", true);
    if (!Number.isFinite(frp) || frp <= 0) return toast("Aqua FRP must be finite and greater than zero.", true);
    if (!Number.isInteger(detections) || detections < 1) return toast("Detections must be an integer of at least 1.", true);
    if (!lstText) return toast("Enter the Aqua local solar time.", true);
    const [hours, minutes] = lstText.split(":").map(Number);
    if (!Number.isFinite(hours) || !Number.isFinite(minutes) || hours > 23 || minutes > 59) return toast("Local solar time is invalid.", true);
    if (!Number.isFinite(scan) || scan <= 0) return toast("Scan size must be finite and positive.", true);
    const lst = hours + minutes / 60;

    if (!state.config?.aggregator_config_hash) {
      return toast("API configuration is unavailable; reload the page with the service running.", true);
    }
    const payload = {
      aggregator_config_hash: state.config.aggregator_config_hash,
      region: [region],
      date: [date],
      cell_lat: [Math.floor(lat)],
      cell_lon: [Math.floor(lon)],
      latitude: [lat],
      longitude: [lon],
      frp_aqua_mw: [frp],
      detections: [detections],
      lst_aqua_h: [lst],
      scan_aqua: [scan],
      area_ratio: [Math.max(0.9, Math.min(12, scan))],
    };
    const runButton = $("h-run");
    runButton.disabled = true;
    status.textContent = "Calling POST /harmonize…";
    try {
      const response = await fetch("/harmonize", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail));
      renderResult(body.cells[0], { region, lat, lon, frp, detections, lst, scan, date });
      status.textContent = `API returned ${body.model}; ${body.count} cell(s).`;
    } catch (error) {
      status.textContent = "API call failed.";
      toast(`Harmonization failed: ${error.message}`, true);
      $("h-result").hidden = true;
      $("h-empty").hidden = false;
      $("h-applicability").className = "badge bad";
      $("h-applicability").innerHTML = `<span class="sym">✕</span> API unavailable`;
    } finally {
      runButton.disabled = false;
    }
  }

  function renderResult(cell, input) {
    const regionLoyo = state.results.models.loyo[input.region];
    $("h-empty").hidden = true;
    $("h-result").hidden = false;
    const badgeNode = $("h-applicability");
    const regional = $("h-regional-panel");
    if (!cell.applicable) {
      badgeNode.className = "badge bad";
      badgeNode.innerHTML = `<span class="sym">✕</span> REFUSED`;
      $("h-result").innerHTML = `
        <div class="result-hero">
          <div class="headline">Applicability verdict</div>
          <div class="big" style="font-size:23px;color:var(--crimson)">No supported correction</div>
          <div class="subline">The API returns <span class="mono">null</span>, not a fabricated value.</div>
        </div>
        <div class="callout bad mt"><div class="title">${esc(cell.reason)}</div>${esc(reasonText(cell.reason))}</div>
        <div class="kv">
          <span class="k">Original Aqua FRP</span><span class="v">${fmtMw(input.frp)}</span>
          <span class="k">Local solar time</span><span class="v">${fmtNum(input.lst, 3)} h</span>
          <span class="k">Delay vs 13.6 h</span><span class="v">${fmtSigned(cell.delay_h, 3)} h</span>
          <span class="k">Delay bin</span><span class="v">${esc(cell.delay_bin || "outside")}</span>
          <span class="k">Prediction level</span><span class="v">80%</span>
        </div>`;
    } else {
      badgeNode.className = "badge ok";
      badgeNode.innerHTML = `<span class="sym">✓</span> APPLICABLE`;
      const lo = Number(cell.interval_lower_mw);
      const hi = Number(cell.interval_upper_mw);
      const point = Number(cell.harmonized_frp_mw);
      const width = Number(cell.interval_width_mw);
      const pad = Math.max((hi - lo) * 0.12, Math.max(hi, 1) * 0.02);
      const trackLow = Math.max(0, lo - pad);
      const trackHigh = hi + pad;
      const trackSpan = Math.max(trackHigh - trackLow, 1e-6);
      const pct = (value) => Math.max(0, Math.min(100, ((value - trackLow) / trackSpan) * 100));
      const pos = (value) => `${pct(value)}%`;
      const correction = ((point / input.frp) - 1) * 100;
      $("h-result").innerHTML = `
        <div class="result-hero">
          <div class="headline">Harmonized FRP · 80% interval is primary</div>
          <div class="big">${fmtMw(point)}</div>
          <div class="subline">Point estimate is secondary metadata. Read the range first.</div>
        </div>
        <div class="interval-box">
          <div class="interval-labels"><span>${fmtMw(lo)}</span><span>point ${fmtMw(point)}</span><span>${fmtMw(hi)}</span></div>
          <div class="interval-track">
            <div class="interval-range" style="left:${pos(lo)};width:${pct(hi) - pct(lo)}%"></div>
            <div class="interval-point" style="left:${pos(point)}"></div>
          </div>
          <div class="interval-caption"><span>Lower bound</span><span>Interval width ${fmtMw(width)}</span><span>Upper bound</span></div>
        </div>
        <div class="kv">
          <span class="k">Original Aqua FRP</span><span class="v">${fmtMw(input.frp)}</span>
          <span class="k">Correction</span><span class="v">${fmtSigned(correction, 1)}%</span>
          <span class="k">Delay vs 13.6 h</span><span class="v">${fmtSigned(cell.delay_h, 3)} h</span>
          <span class="k">Delay bin</span><span class="v">${esc(cell.delay_bin)}</span>
          <span class="k">Predicted log ratio ŷ</span><span class="v">${fmtSigned(cell.predicted_log_ratio, 4)}</span>
          <span class="k">Model</span><span class="v">${esc(state.results.models.served)} · split conformal</span>
        </div>
        <div class="callout neutral mt-sm"><b>${esc(reasonText("calibrated"))}</b> The band is wide because cell-day noise is large. It narrows neither by repeating the request nor by ignoring it.</div>`;
    }
    if (regional) {
      if (regionLoyo) {
        const h = Number(regionLoyo.H?.rmse);
        const raw = Number(regionLoyo.B0?.rmse);
        const worse = Number.isFinite(h) && Number.isFinite(raw) && h > raw;
        regional.hidden = false;
        $("h-regional").innerHTML = `
          <div class="callout ${worse ? "warn" : "neutral"}">
            <div class="title">${esc(input.region.replaceAll("_", " "))} · leave-one-region-out</div>
            H RMSE <span class="mono">${fmtNum(h)}</span> vs raw baseline <span class="mono">${fmtNum(raw)}</span> (n=${fmtInt(regionLoyo.n)}).
            ${worse ? "The model is worse than the raw baseline in this region. Do not treat the correction as an improvement here." : "The model improves on the raw baseline in this region, but regional RMSE is not individual prediction uncertainty."}
          </div>`;
      } else {
        regional.hidden = false;
        $("h-regional").innerHTML = `<div class="callout neutral">No regional validation result exists for this region. An unavailable state is shown rather than an invented score.</div>`;
      }
    }
  }

  /* --------------------------------------------------------- uncertainty */
  function renderUncertainty() {
    const r = state.results;
    coverageChart("coverage-chart", r.uncertainty.nested);
    const gateBody = $("gate-body");
    gateBody.innerHTML = Object.entries(r.gate.bins).map(([label, row]) => `
      <tr><td class="mono">${esc(label)}</td><td class="num">${fmtInt(row.calibration_n)}</td><td class="num">${fmtPct(row.coverage)}</td>
      <td>${row.applicable ? badge("ok", "Applicable") : badge("bad", row.reason || "Refused")}</td></tr>`).join("");

    const domain = r.gate.domain;
    $("domain-panel").innerHTML = `
      <div class="kv">
        <span class="k">Delay domain (1st–99th pct)</span><span class="v">${fmtNum(domain.delay_low, 3)} to ${fmtNum(domain.delay_high, 3)} h</span>
        <span class="k">Scan domain (1st–99th pct)</span><span class="v">${fmtNum(domain.scan_low, 3)} to ${fmtNum(domain.scan_high, 3)} km</span>
        <span class="k">Regions in training</span><span class="v">${esc(domain.regions.join(", "))}</span>
        <span class="k">Coverage floor</span><span class="v">${fmtPct(r.gate.coverage_floor)}</span>
        <span class="k">Minimum calibration pairs</span><span class="v">${fmtInt(r.gate.min_calibration_pairs)}</span>
      </div>
      <p class="mt-sm muted">Saturation, plume scattering and canopy occlusion are <span class="badge none"><span class="sym">○</span> NOT EVALUATED</span>; they are not inferred from FRP size.</p>`;

    const calBins = Object.entries(r.uncertainty.calibration);
    const factors = calBins.map(([, row]) => Number(row.width_factor)).filter(Number.isFinite);
    const medianFactor = factors.length ? factors.sort((a, b) => a - b)[Math.floor(factors.length / 2)] : NaN;
    $("interval-explainer").innerHTML = `
      <p>At 80% nominal, the interval is <span class="mono">FRP_h × exp(±q)</span>. The measured width factor varies by delay bin; the median multiplicative factor is <b>${fmtNum(medianFactor, 2)}×</b>, so the upper bound can be roughly that multiple of the point estimate.</p>
      <div class="table-wrap mt-sm"><table><thead><tr><th>Bin</th><th class="num">q</th><th class="num">exp(q)</th><th class="num">n</th></tr></thead><tbody>
      ${calBins.map(([label, row]) => `<tr><td class="mono">${esc(label)}</td><td class="num">${fmtNum(row.quantile, 3)}</td><td class="num">${fmtNum(row.width_factor, 2)}×</td><td class="num">${fmtInt(row.n)}</td></tr>`).join("")}
      </tbody></table></div>
      <p class="table-note">A bin with fewer than 40 calibration pairs uses the pooled quantile and is reported as a fallback.</p>`;
    trendChart("trend-chart", r.audit.fre_trend);
    const trend = r.audit.fre_trend;
    $("trend-note").innerHTML = `<b>${trend.significant ? "Statistically significant at 95%." : "No statistically significant trend detected at 95%."}</b> Naive log-linear slope ${fmtSigned(trend.naive_slope_percent_per_year, 2)}%/yr; interval ${fmtSigned(trend.ci_low_percent, 1)}% to ${fmtSigned(trend.ci_high_percent, 1)}%. The interval crossing zero is why the annual line is not presented as a real decline. Covers 2021–2025 only; unit: ${esc(trend.unit)}.`;

    const ident = r.audit.identifiability;
    if (!ident.available) {
      $("identifiability").innerHTML = `<div class="result-empty">Identifiability unavailable: no late-delay pairs.</div>`;
    } else {
      $("identifiability").innerHTML = `
        <div class="kv">
          <span class="k">Late delay bin</span><span class="v">(2, 3.5] h</span>
          <span class="k">Cells</span><span class="v">${fmtInt(ident.n_cells)}</span>
          <span class="k">Date-region blocks</span><span class="v">${fmtInt(ident.n_blocks)}</span>
          <span class="k">Mean bias</span><span class="v">${fmtSigned(ident.mean_bias, 3)} ln</span>
          <span class="k">Cell-level SE (naive)</span><span class="v">${fmtNum(ident.cell_level_se, 3)} ln</span>
          <span class="k">Block-level SE</span><span class="v">${ident.block_level_se == null ? "unavailable (1 block)" : `${fmtNum(ident.block_level_se, 3)} ln`}</span>
        </div>
        <p class="mt-sm">The independent unit is the date-region sampling block, not the cell. With only one block above 2 h, a block-level standard error cannot be estimated. That is the reason the gate refuses this regime, not a tuning choice.</p>`;
    }
    renderLimitations("unc-limitations");
  }

  /* -------------------------------------------------------------- models */
  function modelRole(id) {
    return {
      B0: "Raw baseline", B1: "Global mean correction", B2: "Regional mean correction",
      P: "Physics-based", H: "Physics + regional offsets", M: "Gradient boosting", PR: "Physics + ML residual",
    }[id] || "—";
  }

  function renderModels() {
    const r = state.results;
    const order = ["B0", "B1", "B2", "P", "H", "M", "PR"];
    const items = order.map((id) => ({
      label: id,
      value: r.models.grouped_cv[id]?.rmse,
      display: fmtNum(r.models.grouped_cv[id]?.rmse, 3),
      color: ["M", "PR"].includes(id) ? "var(--slate)" : "var(--sage)",
      note: id === r.models.served ? "served" : "",
    }));
    $("model-rmse-chart").innerHTML = hbarChart(items, { width: 540, labelWidth: 48, valueFmt: (v) => fmtNum(v, 3) });

    const selection = r.models.selection;
    const winner = selection.winner;
    $("selection-panel").innerHTML = `
      <div class="callout ${winner === r.models.served ? "neutral" : "warn"}">
        <div class="title">Rule: ${esc(selection.rule)}</div>
        Lowest measured mean RMSE: <b>${esc(winner)}</b>. Served model: <b>${esc(r.models.served)}</b>.
        ${winner !== r.models.served ? "The selection result differs from the serving decision; the product specification still serves H and the evidence is shown rather than hidden." : "The selected model matches the served model."}
      </div>
      <div class="table-wrap mt-sm"><table><thead><tr><th>Model</th><th class="num">Mean LOYO RMSE</th></tr></thead><tbody>
      ${order.map((id) => `<tr><td>${id}${id === winner ? " · selected" : ""}</td><td class="num">${fmtNum(selection.mean_rmse[id], 4)}</td></tr>`).join("")}
      </tbody></table></div>`;

    $("model-table").innerHTML = order.map((id) => {
      const metrics = r.models.grouped_cv[id] || {};
      const research = ["M", "PR"].includes(id);
      return `<tr>
        <td><b>${id}</b></td><td>${esc(modelRole(id))}</td>
        <td class="num">${fmtNum(metrics.rmse, 4)}</td>
        <td class="num">${fmtSigned(metrics.bias, 4)}</td>
        <td class="num">${fmtNum(metrics.mae, 4)}</td>
        <td class="num">${fmtInt(metrics.n)}</td>
        <td>${id === r.models.served ? badge("ok", "Active serving") : research ? badge("info", "Research only") : badge("none", "Not served")}</td>
      </tr>`;
    }).join("");

    $("operational-models").innerHTML = ["B0", "B1", "B2", "P", "H"].map((id) => `
      <div class="split" style="padding:6px 0;border-bottom:1px solid #efede6">
        <span><b>${id}</b> · ${esc(modelRole(id))}</span>
        <span class="mono small">${fmtNum(r.models.grouped_cv[id]?.rmse, 3)}</span>
        <span>${id === "H" ? badge("ok", "Serving") : badge("none", "Not served")}</span>
      </div>`).join("") +
      `<p class="small muted mt-sm">H is the served artifact because it keeps a physics-structured correction with regional adjustments. It is not the lowest-RMSE model.</p>`;

    $("research-models").innerHTML = ["M", "PR"].map((id) => `
      <div class="split" style="padding:6px 0;border-bottom:1px solid #efede6">
        <span><b>${id}</b> · ${esc(modelRole(id))}</span>
        <span class="mono small">${fmtNum(r.models.grouped_cv[id]?.rmse, 3)}</span>
        <span>${badge("info", "Not switchable")}</span>
      </div>`).join("") +
      `<p class="small muted mt-sm">Lower RMSE is evidence of lower prediction error in this sample, not evidence of better extrapolation or causal bias removal. Operational switching is unavailable until further validation.</p>`;

    const loyo = r.models.loyo;
    $("loyo-body").innerHTML = Object.entries(loyo).map(([region, row]) => {
      const h = Number(row.H?.rmse), raw = Number(row.B0?.rmse);
      const reading = h > raw ? "Worse than raw" : "Improves on raw";
      return `<tr><td>${esc(region.replaceAll("_", " "))}</td><td class="num">${fmtInt(row.n)}</td>
        <td class="num">${fmtNum(raw)}</td><td class="num">${fmtNum(row.P?.rmse)}</td><td class="num">${fmtNum(h)}</td>
        <td>${h > raw ? badge("warn", reading) : badge("ok", reading)}</td></tr>`;
    }).join("");
    renderLimitations("model-limitations");
  }

  /* --------------------------------------------------------------- audit */
  function renderAudit() {
    const r = state.results;
    groupedBiasChart("bias-chart", r.audit.bias_by_bin);
    pairingChart("pairing-chart", r.audit.pairing_sensitivity);
    const pairing = r.audit.pairing_sensitivity;
    const includesZero = (row) => Number(row.ci_low) <= 0 && Number(row.ci_high) >= 0;
    $("pairing-note").innerHTML = `Cell-day-sum slope ${fmtSigned(pairing.cell_day_sum.slope_per_hour, 3)}/h (95% CI ${fmtSigned(pairing.cell_day_sum.ci_low, 3)} to ${fmtSigned(pairing.cell_day_sum.ci_high, 3)}; n=${fmtInt(pairing.cell_day_sum.n)}). Near-coincident slope ${fmtSigned(pairing.near_coincident.slope_per_hour, 3)}/h (CI ${fmtSigned(pairing.near_coincident.ci_low, 3)} to ${fmtSigned(pairing.near_coincident.ci_high, 3)}; n=${fmtInt(pairing.near_coincident.n)}). The sign depends on the pairing strategy; a confound test with scan control remains pending.`;

    const terra = r.audit.terra_extrapolation;
    $("terra-panel").innerHTML = terra.available ? `
      <div class="kv">
        <span class="k">Terra–SNPP pairs</span><span class="v">${fmtInt(terra.n)}</span>
        <span class="k">Mean delay</span><span class="v">${fmtSigned(terra.delay_mean_h, 2)} h</span>
        <span class="k">Raw RMSE</span><span class="v">${fmtNum(terra.raw_rmse)}</span>
        <span class="k">Physics P RMSE</span><span class="v">${fmtNum(terra.physics_rmse)}</span>
        <span class="k">H RMSE</span><span class="v">${fmtNum(terra.h_rmse)}</span>
      </div>
      <p class="small mt-sm">Out-of-regime test: fit on Aqua, predict Terra. ${terra.physics_rmse > terra.raw_rmse ? "The physics model is worse than the raw baseline." : "The physics model beats the raw baseline."} This is not validation of the Aqua correction.</p>` :
      `<div class="result-empty">No Terra–SNPP pairs; unavailable.</div>`;

    $("audit-loyo").innerHTML = Object.entries(r.models.loyo).map(([region, row]) => `
      <div class="split" style="padding:5px 0;border-bottom:1px solid #efede6"><span>${esc(region.replaceAll("_", " "))}</span><span class="mono small">${fmtNum(row.H?.rmse)} vs raw ${fmtNum(row.B0?.rmse)}</span></div>`).join("");
    $("audit-status").innerHTML = `
      <div class="small"><span class="badge ok"><span class="sym">✓</span> Measured</span><p class="mt-sm">Grouped CV, regional transfer, conformal coverage, Terra test, pairing sensitivity, FRE trend, identifiability.</p>
      <span class="badge warn"><span class="sym">⚠</span> Pending</span><p class="mt-sm">Pairing-confound test, bin-level bootstrap bias intervals, independent georeferenced reference data, feature importance.</p>
      <span class="badge none"><span class="sym">○</span> Not evaluated</span><p class="mt-sm">Saturation, plume scattering, canopy occlusion.</p></div>`;

    const validity = r.validity_map;
    const rows = [];
    Object.entries(validity).forEach(([region, payload]) => {
      Object.entries(payload.bins).forEach(([label, row]) => {
        if (!row.n) return;
        rows.push(`<tr>
          <td>${esc(region.replaceAll("_", " "))}</td><td class="mono">${esc(label)}</td>
          <td class="num">${fmtInt(row.n)}</td><td class="num">${fmtInt(row.applicable)}</td>
          <td class="num">${fmtPct(row.coverage)}</td>
          <td>${row.gate_reason ? badge("bad", row.gate_reason) : badge("ok", "Applicable")}</td>
        </tr>`);
      });
    });
    $("validity-body").innerHTML = rows.join("") || `<tr><td colspan="6" class="loading">No validity rows.</td></tr>`;
    renderLimitations("audit-limitations");
  }

  /* ----------------------------------------------------------- methodology */
  function renderMethodology() {
    const r = state.results;
    $("m-datahash").textContent = r.provenance.data_hash;
    $("method-limitations").innerHTML = `<ul>${r.limitations.map((item) => `<li>${esc(item)}</li>`).join("")}</ul><p class="muted mt-sm">Not claimed: a global archive, a validated correction beyond the calibrated delay domain, saturation/plume/canopy handling, or improved accuracy without independent evidence.</p>`;
    $("method-provenance").innerHTML = `
      <div class="kv">
        <span class="k">data_hash</span><span class="v">${esc(r.provenance.data_hash)}</span>
        <span class="k">config_hash</span><span class="v">${esc(r.provenance.config_hash)}</span>
        <span class="k">pipeline</span><span class="v">${esc(r.provenance.pipeline_version)}</span>
        <span class="k">model artifact SHA-256</span><span class="v">${esc(r.provenance.model_artifact_sha256)}</span>
        <span class="k">L1 canonical SHA-256</span><span class="v">${esc(r.provenance.l1_canonical_sha256)}</span>
        <span class="k">pairs SHA-256</span><span class="v">${esc(r.provenance.pairs_sha256)}</span>
        <span class="k">generated</span><span class="v">${esc(r.provenance.generated_at_utc)}</span>
        <span class="k">git commit</span><span class="v">${esc(r.provenance.git_commit)}</span>
        <span class="k">python / numpy / pandas</span><span class="v">${esc(r.provenance.library_versions.python)} / ${esc(r.provenance.library_versions.numpy)} / ${esc(r.provenance.library_versions.pandas)}</span>
      </div>`;
    renderLimitations("method-limitations-foot");
  }

  /* ------------------------------------------------------------ shared */
  function renderLimitations(id) {
    const node = $(id);
    if (!node || !state.results) return;
    node.innerHTML = `<b>Limitations and applicability.</b><ul>${state.results.limitations.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>`;
  }

  function renderGlobal() {
    const r = state.results;
    $("rail-datahash").textContent = r.provenance.data_hash_begins;
    $("rail-model").textContent = r.models.served;
    $("rail-resultshash").textContent = r.provenance.config_hash.slice(0, 12);
    $("rail-status").textContent = "Verified results loaded";
    $("foot-hash").textContent = r.provenance.data_hash.slice(0, 16) + "…";
    $("foot-model").textContent = `${r.models.served} · ${r.provenance.pipeline_version}`;
    $("top-model-badge").innerHTML = `<span class="sym">✓</span> ${esc(r.models.served)} served`;
    $("m-datahash").textContent = r.provenance.data_hash;
  }

  async function checkApi() {
    try {
      const health = await fetchJSON("/health");
      state.apiOnline = health.status === "ok";
      $("top-api-badge").className = "badge ok";
      $("top-api-badge").innerHTML = `<span class="sym">✓</span> API online · ${esc(health.model)}`;
    } catch (error) {
      state.apiOnline = false;
      $("top-api-badge").className = "badge bad";
      $("top-api-badge").innerHTML = `<span class="sym">✕</span> API unavailable`;
    }
  }

  async function boot() {
    try {
      state.results = await fetchJSON("/results", "./results.json");
      state.version = await fetchJSON("/version", "./version.json").catch(() => null);
      state.config = await fetchJSON("/config", "./config.json").catch(() => null);
      if (!state.config) {
        state.config = {
          aggregator_config_hash: state.results.provenance.config_hash,
          regions: state.results.gate.domain.regions,
          limitations: state.results.limitations,
        };
      }
      renderGlobal();
      renderOverview();
      renderExplorer();
      renderHarmonization();
      renderUncertainty();
      renderModels();
      renderAudit();
      renderMethodology();
      checkApi();
      const initial = window.location.hash.replace("#", "");
      navigate(titles[initial] ? initial : "overview");
    } catch (error) {
      $("rail-status").textContent = "Results unavailable";
      $("top-api-badge").className = "badge bad";
      $("top-api-badge").innerHTML = `<span class="sym">✕</span> results unavailable`;
      document.querySelector(".content").innerHTML = `<div class="panel" style="margin-top:24px"><div class="panel-head"><h2>Verified results unavailable</h2></div><p class="lede">The dashboard reads a hashed <span class="mono">results.json</span>. Run <span class="mono">scripts/03_run_analysis.py</span> and serve the app with FastAPI, or copy <span class="mono">artifacts/results/results.json</span> to <span class="mono">web/results.json</span> for a static copy.</p><div class="callout bad"><b>${esc(error.message)}</b></div></div>`;
      toast(`Dashboard could not load results: ${error.message}`, true);
    }
  }

  document.querySelectorAll(".nav button").forEach((button) => {
    button.addEventListener("click", () => navigate(button.dataset.page));
  });
  window.addEventListener("hashchange", () => {
    const page = window.location.hash.replace("#", "");
    if (titles[page] && page !== state.page) navigate(page);
  });
  boot();
})();
