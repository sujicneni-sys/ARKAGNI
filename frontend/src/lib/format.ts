/** Presentation-only formatters.  No scientific transformation happens here. */

const integerFormatter = new Intl.NumberFormat("en-US");

export function fmtInt(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return integerFormatter.format(Math.round(value));
}

export function fmtNum(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return Number(value).toFixed(digits);
}

export function fmtPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${(Number(value) * 100).toFixed(digits)}%`;
}

export function fmtSigned(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const number = Number(value);
  return `${number >= 0 ? "+" : ""}${number.toFixed(digits)}`;
}

export function fmtMw(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${Number(value).toFixed(digits)} MW`;
}

export function fmtCompactMw(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const number = Number(value);
  if (Math.abs(number) >= 1_000_000) return `${(number / 1_000_000).toFixed(2)}M MW`;
  if (Math.abs(number) >= 1_000) return `${(number / 1_000).toFixed(1)}k MW`;
  return `${number.toFixed(0)} MW`;
}

export function fmtHash(value: string | null | undefined, length = 12): string {
  if (!value) return "—";
  return value.slice(0, length);
}

export function humanRegion(value: string): string {
  return value.replaceAll("_", " ");
}

export function titleCase(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function fmtDate(value: string | null | undefined): string {
  if (!value) return "—";
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return value;
  return `${match[1]}-${match[2]}-${match[3]}`;
}

export function compactDate(value: string | null | undefined): string {
  if (!value) return "—";
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return value;
  return `${match[1].slice(2)}·${match[2]}·${match[3]}`;
}

export const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
] as const;

export function monthIndex(iso: string): number {
  const match = /^\d{4}-(\d{2})/.exec(iso);
  return match ? Number(match[1]) - 1 : -1;
}

export function yearOf(iso: string): number {
  return Number(iso.slice(0, 4));
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}
