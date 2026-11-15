import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { CalibrationBin, GateBin, Metric } from "../lib/types";
import { fmtCompactMw, fmtInt, fmtNum, fmtPct } from "../lib/format";
import { modelFamily } from "../lib/science";

interface TooltipItem {
  name?: string | number;
  value?: number | string;
  color?: string;
  dataKey?: string | number;
  payload?: Record<string, unknown>;
}

interface ChartTooltipProps {
  active?: boolean;
  payload?: TooltipItem[];
  label?: string | number;
  digits?: number;
  unit?: string;
  percent?: boolean;
  integer?: boolean;
}

function formatTooltipValue(
  value: number | string | undefined,
  { digits = 3, unit = "", percent = false, integer = false }: ChartTooltipProps,
): string {
  if (value === undefined || value === null) return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  if (percent) return fmtPct(number, digits === 3 ? 1 : digits);
  if (integer) return `${fmtInt(number)}${unit ? ` ${unit}` : ""}`;
  return `${number.toFixed(digits)}${unit ? ` ${unit}` : ""}`;
}

export function ChartTooltip(props: ChartTooltipProps) {
  const { active, payload, label } = props;
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="chart-tooltip">
      {label !== undefined && <div className="tooltip-title">{label}</div>}
      {payload.map((item, index) => (
        <div className="tooltip-row" key={`${String(item.dataKey ?? index)}`}>
          <span style={{ color: item.color ?? undefined }}>{String(item.name ?? "")}</span>
          <span>{formatTooltipValue(item.value, props)}</span>
        </div>
      ))}
    </div>
  );
}

const AXIS = { fontSize: 10, fill: "#747873" };
const GRID = "#efede6";

/* ------------------------------------------------------------------ bars */

export interface SimpleBarDatum {
  label: string;
  value: number;
  display?: string;
  color?: string;
  note?: string;
}

export function SimpleBars({
  data,
  height = 210,
  integer = false,
  unit = "",
  leftWidth = 96,
}: {
  data: SimpleBarDatum[];
  height?: number;
  integer?: boolean;
  unit?: string;
  leftWidth?: number;
}) {
  return (
    <div className="chart-frame" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 4, right: 74, bottom: 4, left: 0 }}
          barCategoryGap={8}
        >
          <CartesianGrid horizontal={false} stroke={GRID} />
          <XAxis type="number" tick={AXIS} axisLine={false} tickLine={false} hide />
          <YAxis
            type="category"
            dataKey="label"
            tick={AXIS}
            axisLine={false}
            tickLine={false}
            width={leftWidth}
          />
          <Tooltip
            cursor={{ fill: "rgba(82,107,91,0.06)" }}
            content={<ChartTooltip integer={integer} unit={unit} digits={0} />}
          />
          <Bar dataKey="value" name="Count" radius={[0, 1, 1, 0]} maxBarSize={18}>
            {data.map((entry) => (
              <Cell key={entry.label} fill={entry.color ?? "#526B5B"} />
            ))}
            <LabelList
              dataKey="display"
              position="right"
              style={{ fontSize: 10, fill: "#292D2B", fontFamily: "Cascadia Mono, monospace" }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/* --------------------------------------------------------------- coverage */

export function CoverageChart({
  bins,
  order,
  nominal,
  floor,
}: {
  bins: Record<string, GateBin>;
  order: string[];
  nominal: number;
  floor: number;
}) {
  const data = order.map((label) => {
    const entry = bins[label];
    return {
      label,
      coverage: entry?.coverage ?? 0,
      n: entry?.calibration_n ?? 0,
      applicable: entry?.applicable ?? false,
    };
  });

  return (
    <div className="chart-frame" style={{ height: 300 }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 22, right: 12, bottom: 26, left: 4 }}>
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis dataKey="label" tick={AXIS} axisLine={false} tickLine={false} interval={0} angle={-18} textAnchor="end" height={48} />
          <YAxis
            domain={[0, 1]}
            tick={AXIS}
            axisLine={false}
            tickLine={false}
            tickFormatter={(value: number) => `${Math.round(value * 100)}%`}
            width={38}
          />
          <Tooltip content={<ChartTooltip percent digits={1} />} cursor={{ fill: "rgba(82,107,91,0.05)" }} />
          <ReferenceLine
            y={nominal}
            stroke="#B66F4D"
            strokeDasharray="3 3"
            label={{ value: "80% nominal", position: "insideTopRight", fontSize: 9, fill: "#B66F4D" }}
          />
          <ReferenceLine
            y={floor}
            stroke="#A33C37"
            strokeDasharray="2 4"
            label={{ value: "0.70 floor", position: "insideBottomRight", fontSize: 9, fill: "#A33C37" }}
          />
          <Bar dataKey="coverage" name="Empirical coverage" maxBarSize={46} radius={[1, 1, 0, 0]}>
            {data.map((entry) => (
              <Cell key={entry.label} fill={entry.applicable ? "#526B5B" : "#C77B43"} />
            ))}
            <LabelList
              dataKey="coverage"
              position="top"
              formatter={(value: number) => `${(value * 100).toFixed(1)}%`}
              style={{ fontSize: 9, fill: "#292D2B", fontFamily: "Cascadia Mono, monospace" }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ------------------------------------------------------------- model rmse */

export function ModelRmseChart({
  grouped,
  served,
  family,
}: {
  grouped: Record<string, Metric>;
  served: string;
  family: (model: string) => "operational" | "research";
}) {
  const data = Object.entries(grouped)
    .map(([model, metric]) => ({
      label: model,
      rmse: metric.rmse,
      bias: metric.bias,
      mae: metric.mae,
      n: metric.n,
      family: family(model),
      served: model === served,
    }))
    .sort((a, b) => a.rmse - b.rmse);
  const minimum = Math.min(...data.map((entry) => entry.rmse));
  const maximum = Math.max(...data.map((entry) => entry.rmse));
  const lower = Math.max(0, Math.floor((minimum - 0.015) * 100) / 100);
  const upper = Math.ceil((maximum + 0.008) * 100) / 100;

  return (
    <div className="chart-frame" style={{ height: 300 }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 64, bottom: 4, left: 0 }} barCategoryGap={7}>
          <CartesianGrid horizontal={false} stroke={GRID} />
          <XAxis
            type="number"
            domain={[lower, upper]}
            tick={AXIS}
            axisLine={false}
            tickLine={false}
            tickFormatter={(value: number) => value.toFixed(2)}
          />
          <YAxis type="category" dataKey="label" tick={AXIS} axisLine={false} tickLine={false} width={38} />
          <Tooltip content={<ChartTooltip digits={4} />} cursor={{ fill: "rgba(82,107,91,0.06)" }} />
          <Bar dataKey="rmse" name="Grouped-CV RMSE" maxBarSize={20} radius={[0, 1, 1, 0]}>
            {data.map((entry) => (
              <Cell
                key={entry.label}
                fill={entry.served ? "#3B5345" : entry.family === "research" ? "#788B91" : "#8FA793"}
              />
            ))}
            <LabelList
              dataKey="rmse"
              position="right"
              formatter={(value: number) => value.toFixed(4)}
              style={{ fontSize: 10, fill: "#292D2B", fontFamily: "Cascadia Mono, monospace" }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ------------------------------------------------------------------- bias */

export function BiasChart({
  bins,
  order,
}: {
  bins: Record<string, { raw_bias: number; corrected_bias: number }>;
  order: string[];
}) {
  const data = order.map((label) => ({
    label,
    raw: bins[label]?.raw_bias ?? 0,
    corrected: bins[label]?.corrected_bias ?? 0,
  }));

  return (
    <div className="chart-frame" style={{ height: 290 }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 12, right: 10, bottom: 34, left: 0 }} barCategoryGap={16}>
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis dataKey="label" tick={AXIS} axisLine={false} tickLine={false} interval={0} angle={-18} textAnchor="end" height={52} />
          <YAxis tick={AXIS} axisLine={false} tickLine={false} tickFormatter={(value: number) => value.toFixed(2)} width={40} />
          <Tooltip content={<ChartTooltip digits={4} />} cursor={{ fill: "rgba(82,107,91,0.05)" }} />
          <ReferenceLine y={0} stroke="#9A968C" />
          <Bar dataKey="raw" name="Raw bias" fill="#788B91" maxBarSize={22} radius={[1, 1, 0, 0]} />
          <Bar dataKey="corrected" name="Corrected (H) bias" fill="#526B5B" maxBarSize={22} radius={[1, 1, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ------------------------------------------------------------------ years */

export function YearBars({ data }: { data: Record<string, number> }) {
  const rows = Object.entries(data)
    .sort(([a], [b]) => Number(a) - Number(b))
    .map(([year, value]) => ({ label: year, value }));

  return (
    <div className="chart-frame" style={{ height: 220 }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 22, right: 10, bottom: 4, left: 0 }}>
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis dataKey="label" tick={AXIS} axisLine={false} tickLine={false} />
          <YAxis
            tick={AXIS}
            axisLine={false}
            tickLine={false}
            tickFormatter={(value: number) => `${(value / 1_000_000).toFixed(1)}M`}
            width={42}
          />
          <Tooltip content={<ChartTooltip integer unit="MW" />} cursor={{ fill: "rgba(199,123,67,0.08)" }} />
          <Bar dataKey="value" name="Validated annual FRP total" fill="#C77B43" maxBarSize={46} radius={[1, 1, 0, 0]}>
            <LabelList
              dataKey="value"
              position="top"
              formatter={(value: number) => fmtCompactMw(value)}
              style={{ fontSize: 8.5, fill: "#292D2B", fontFamily: "Cascadia Mono, monospace" }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ----------------------------------------------------------------- support */

export function SupportBars({
  bins,
  order,
}: {
  bins: Record<string, GateBin>;
  order: string[];
}) {
  const data = order.map((label) => ({
    label,
    n: bins[label]?.calibration_n ?? 0,
    applicable: bins[label]?.applicable ?? false,
  }));

  return (
    <div className="chart-frame" style={{ height: 235 }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 20, right: 10, bottom: 30, left: 0 }}>
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis dataKey="label" tick={AXIS} axisLine={false} tickLine={false} interval={0} angle={-18} textAnchor="end" height={48} />
          <YAxis tick={AXIS} axisLine={false} tickLine={false} tickFormatter={(value: number) => fmtInt(value)} width={42} />
          <Tooltip content={<ChartTooltip integer unit="pairs" />} cursor={{ fill: "rgba(82,107,91,0.05)" }} />
          <Bar dataKey="n" name="Calibration pairs" maxBarSize={42} radius={[1, 1, 0, 0]}>
            {data.map((entry) => (
              <Cell key={entry.label} fill={entry.applicable ? "#8FA793" : "#C77B43"} />
            ))}
            <LabelList
              dataKey="n"
              position="top"
              style={{ fontSize: 9, fill: "#292D2B", fontFamily: "Cascadia Mono, monospace" }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ----------------------------------------------------------- width factors */

export function WidthFactorChart({
  calibration,
  order,
}: {
  calibration: Record<string, CalibrationBin>;
  order: string[];
}) {
  const data = order.map((label) => ({
    label,
    value: calibration[label]?.width_factor ?? 0,
    display: `${(calibration[label]?.width_factor ?? 0).toFixed(2)}×`,
    color: calibration[label]?.n && calibration[label].n < 40 ? "#C77B43" : "#526B5B",
  }));

  return <SimpleBars data={data} height={235} leftWidth={68} integer={false} />;
}

/* ------------------------------------------------------------ forest plot */

export interface Estimate {
  label: string;
  slope: number;
  low: number;
  high: number;
  n: number;
  color: string;
  note: string;
}

export function EstimatePlot({ estimates }: { estimates: Estimate[] }) {
  const all = estimates.flatMap((estimate) => [estimate.low, estimate.high, estimate.slope]);
  const domainLow = Math.min(-0.4, ...all) - 0.04;
  const domainHigh = Math.max(0.4, ...all) + 0.04;
  const span = domainHigh - domainLow;
  const position = (value: number) => ((value - domainLow) / span) * 100;
  const ticks = [domainLow, 0, domainHigh];

  return (
    <div>
      <div className="relative h-[168px] ml-[132px] mr-3 mt-3">
        {ticks.map((tick) => (
          <div
            key={tick}
            className="absolute top-0 bottom-0 border-l"
            style={{
              left: `${position(tick)}%`,
              borderColor: Math.abs(tick) < 1e-9 ? "#9A968C" : "#efede6",
              borderLeftStyle: Math.abs(tick) < 1e-9 ? "solid" : "dashed",
            }}
          />
        ))}
        {estimates.map((estimate, index) => (
          <div
            key={estimate.label}
            className="absolute flex items-center"
            style={{ top: 20 + index * 62, left: 0, right: 0, height: 34 }}
          >
            <div
              className="absolute -left-[132px] w-[124px] text-right text-[10.5px] leading-tight"
              style={{ color: "#292D2B" }}
            >
              <div className="font-semibold">{estimate.label}</div>
              <div className="mono text-[9px] text-[#747873]">n={fmtInt(estimate.n)}</div>
            </div>
            <div className="relative w-full h-[2px] rounded" style={{ background: "#d8d4ca" }}>
              <div
                className="absolute top-0 h-[2px]"
                style={{
                  left: `${position(estimate.low)}%`,
                  width: `${position(estimate.high) - position(estimate.low)}%`,
                  background: estimate.color,
                  opacity: 0.55,
                }}
              />
              <div
                className="absolute top-1/2 h-[11px] w-[11px] -translate-x-1/2 -translate-y-1/2 rounded-full border-2"
                style={{ left: `${position(estimate.slope)}%`, background: "#FEFDF9", borderColor: estimate.color }}
                title={`${estimate.slope.toFixed(4)} h⁻¹`}
              />
              <div
                className="absolute -top-[18px] mono text-[9px] -translate-x-1/2 whitespace-nowrap"
                style={{ left: `${position(estimate.slope)}%`, color: estimate.color }}
              >
                {estimate.slope >= 0 ? "+" : ""}
                {estimate.slope.toFixed(3)}
              </div>
            </div>
          </div>
        ))}
      </div>
      <div className="ml-[132px] mr-3 flex justify-between mono text-[9px] text-[#747873] mt-2">
        {ticks.map((tick) => (
          <span key={tick}>{tick.toFixed(2)} h⁻¹</span>
        ))}
      </div>
      <div className="chart-legend">
        {estimates.map((estimate) => (
          <span key={estimate.label}>
            <i className="swatch" style={{ background: estimate.color }} />
            {estimate.note}
          </span>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------- misc */

export function ModelBars({
  values,
  highlight,
}: {
  values: Record<string, number>;
  highlight?: string;
}) {
  const data = Object.entries(values)
    .map(([label, value]) => ({
      label,
      value,
      display: value.toFixed(4),
      color: label === highlight ? "#3B5345" : modelFamily(label) === "research" ? "#788B91" : "#8FA793",
    }))
    .sort((a, b) => a.value - b.value);
  return <SimpleBars data={data} height={250} leftWidth={40} />;
}
