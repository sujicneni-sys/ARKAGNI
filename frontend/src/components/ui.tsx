import type { ReactNode } from "react";
import { CircleCheck, CircleSlash, CircleX, Info, Minus, TriangleAlert } from "lucide-react";
import { renderToString } from "katex";
import "katex/dist/katex.min.css";

export type BadgeTone = "ok" | "warn" | "bad" | "none" | "info" | "fire" | "plain";

const BADGE_SYMBOL: Record<BadgeTone, ReactNode> = {
  ok: <CircleCheck size={11} strokeWidth={2.4} />,
  warn: <TriangleAlert size={11} strokeWidth={2.4} />,
  bad: <CircleX size={11} strokeWidth={2.4} />,
  none: <CircleSlash size={11} strokeWidth={2.2} />,
  info: <Info size={11} strokeWidth={2.2} />,
  fire: <span aria-hidden>◆</span>,
  plain: <Minus size={11} strokeWidth={2.4} />,
};

export function Badge({
  tone = "none",
  children,
  symbol,
  className = "",
  title,
}: {
  tone?: BadgeTone;
  children: ReactNode;
  symbol?: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span className={`badge ${tone} ${className}`.trim()} title={title}>
      <span className="sym" aria-hidden>
        {symbol ?? BADGE_SYMBOL[tone]}
      </span>
      {children}
    </span>
  );
}

export function Panel({
  children,
  title,
  meta,
  className = "",
  id,
  actions,
}: {
  children: ReactNode;
  title?: ReactNode;
  meta?: ReactNode;
  className?: string;
  id?: string;
  actions?: ReactNode;
}) {
  return (
    <section className={`panel ${className}`.trim()} id={id}>
      {(title !== undefined || meta !== undefined || actions !== undefined) && (
        <div className="panel-head">
          {title !== undefined ? <h2>{title}</h2> : <span />}
          <div className="flex items-center gap-2">
            {meta !== undefined && <span className="panel-meta">{meta}</span>}
            {actions}
          </div>
        </div>
      )}
      {children}
    </section>
  );
}

export function PanelTitle({ children, meta }: { children: ReactNode; meta?: ReactNode }) {
  return (
    <div className="panel-head">
      <h3>{children}</h3>
      {meta !== undefined && <span className="panel-meta">{meta}</span>}
    </div>
  );
}

export function Metric({
  label,
  value,
  hint,
  small = false,
  badge,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  small?: boolean;
  badge?: ReactNode;
}) {
  return (
    <div className="metric">
      <div className="metric-head">
        <div className="metric-label">{label}</div>
        {badge !== undefined && <span className="metric-badge">{badge}</span>}
      </div>
      <div className={`metric-value${small ? " small-value" : ""}`}>{value}</div>
      {hint !== undefined && <div className="metric-hint">{hint}</div>}
    </div>
  );
}

export function MetricStrip({
  children,
  columns = 5,
}: {
  children: ReactNode;
  columns?: 3 | 4 | 5;
}) {
  return <div className={`metric-strip${columns === 5 ? "" : ` ${columns === 4 ? "four" : "three"}`}`}>{children}</div>;
}

export function Callout({
  tone = "neutral",
  title,
  children,
  className = "",
}: {
  tone?: "neutral" | "good" | "warn" | "bad" | "fire";
  title?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`callout ${tone} ${className}`.trim()}>
      {title !== undefined && <span className="callout-title">{title}</span>}
      {children}
    </div>
  );
}

export function KeyValue({ rows }: { rows: Array<[ReactNode, ReactNode]> }) {
  return (
    <div className="kv">
      {rows.map(([key, value], index) => (
        <div key={index} className="contents">
          <div className="k">{key}</div>
          <div className="v">{value}</div>
        </div>
      ))}
    </div>
  );
}

export function Equation({
  children,
  label,
  latex = false,
}: {
  children: ReactNode;
  label?: string;
  latex?: boolean;
}) {
  if (latex) {
    const tex = typeof children === "string" ? children : String(children);
    return (
      <div className="eq-block" aria-label={label}>
        {label !== undefined && <div className="eq-label">{label}</div>}
        <div
          className="eq math"
          dangerouslySetInnerHTML={{
            __html: renderToString(tex, {
              displayMode: true,
              throwOnError: false,
              strict: false,
            }),
          }}
        />
      </div>
    );
  }
  return (
    <div className="eq" aria-label={label}>
      {children}
    </div>
  );
}

export function PageHeader({
  kicker,
  title,
  lede,
  side,
}: {
  kicker: string;
  title: string;
  lede: ReactNode;
  side?: ReactNode;
}) {
  return (
    <header className="page-head">
      <div>
        <div className="kicker">{kicker}</div>
        <h1>{title}</h1>
        <p className="lede">{lede}</p>
      </div>
      {side !== undefined && <div className="page-head-side">{side}</div>}
    </header>
  );
}

export function Limitations({ items, title = "Limitations carried with every result" }: { items: ReadonlyArray<string>; title?: string }) {
  return (
    <section className="panel mt" aria-label={title}>
      <div className="panel-head">
        <h3>{title}</h3>
        <span className="panel-meta">visible by design · never hidden in a tooltip</span>
      </div>
      <div className="grid two">
        {items.map((item) => (
          <div key={item} className="flex gap-2 items-start text-[11.5px] text-ink">
            <span className="mt-[3px] text-fire" aria-hidden>
              ◆
            </span>
            <span>{item}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

export function SkeletonPanel({ height = 160, className = "" }: { height?: number; className?: string }) {
  return (
    <div className={`panel ${className}`.trim()}>
      <div className="skeleton" style={{ height: 12, width: "38%", marginBottom: 10 }} />
      <div className="skeleton" style={{ height }} />
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="callout neutral">
      <span className="callout-title">{title}</span>
      {children}
    </div>
  );
}

export function InlineCode({ children }: { children: ReactNode }) {
  return <code className="mono text-[0.93em]">{children}</code>;
}
