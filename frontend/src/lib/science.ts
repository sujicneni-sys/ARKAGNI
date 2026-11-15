/**
 * Display-side mirrors of the published contract.
 *
 * These helpers only preview the grid snap, the LST display, the sampling
 * windows and pixel flags so the interface can explain what the API will do.
 * The served harmonized value always comes from POST /harmonize.
 */

export const REFERENCE_LST_H = 13.6;
export const ALPHA = 0.2;
export const NOMINAL_COVERAGE = 0.8;
export const MIN_CALIBRATION_PAIRS = 40;
export const COVERAGE_FLOOR = 0.7;

export const DELAY_BIN_EDGES: ReadonlyArray<number> = [-3, 0, 0.5, 1, 1.5, 2, 3.5];
export const DELAY_BIN_LABELS: ReadonlyArray<string> = [
  "(-3, 0]",
  "(0, 0.5]",
  "(0.5, 1]",
  "(1, 1.5]",
  "(1.5, 2]",
  "(2, 3.5]",
];

export const FLAG_BITS = [
  { bit: 0, mask: 1 << 0, name: "type != 0", state: "excluded", reserved: false },
  { bit: 1, mask: 1 << 1, name: "FRP <= 0", state: "flagged", reserved: false },
  { bit: 2, mask: 1 << 2, name: "night", state: "flagged", reserved: false },
  { bit: 3, mask: 1 << 3, name: "saturation", state: "not evaluated", reserved: true },
  { bit: 4, mask: 1 << 4, name: "plume scattering", state: "not evaluated", reserved: true },
  { bit: 5, mask: 1 << 5, name: "canopy occlusion", state: "not evaluated", reserved: true },
  { bit: 6, mask: 1 << 6, name: "reserved", state: "not evaluated", reserved: true },
  { bit: 7, mask: 1 << 7, name: "reserved", state: "not evaluated", reserved: true },
] as const;

/** floor() on the published 1-degree grid. */
export function snapCoordinate(value: number): number {
  return Math.floor(value);
}

export function cellLabel(lat: number, lon: number): string {
  const latInt = Math.floor(lat);
  const lonInt = Math.floor(lon);
  const ns = latInt < 0 ? "S" : "N";
  const ew = lonInt < 0 ? "W" : "E";
  return `${ns}${String(Math.abs(latInt)).padStart(2, "0")}${ew}${String(Math.abs(lonInt)).padStart(3, "0")}`;
}

export function parseCell(label: string): { lat: number; lon: number } | null {
  const match = /^([NS])(\d{2})([EW])(\d{3})$/.exec(label);
  if (!match) return null;
  const lat = Number(match[2]) * (match[1] === "S" ? -1 : 1);
  const lon = Number(match[4]) * (match[3] === "W" ? -1 : 1);
  return { lat, lon };
}

/** lst = (UTC hours + longitude / 15) mod 24 */
export function localSolarTime(utcHours: number, longitude: number): number {
  return ((utcHours + longitude / 15) % 24 + 24) % 24;
}

export function parseLstText(text: string): number | null {
  const match = /^(\d{1,2}):(\d{2})$/.exec(text.trim());
  if (!match) return null;
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  if (hours < 0 || hours > 23 || minutes < 0 || minutes > 59) return null;
  return hours + minutes / 60;
}

export function lstFromHours(hours: number): string {
  const wrapped = ((hours % 24) + 24) % 24;
  const totalMinutes = Math.round(wrapped * 60) % (24 * 60);
  const hh = Math.floor(totalMinutes / 60);
  const mm = totalMinutes % 60;
  return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
}

export function delayFromLst(lstHours: number): number {
  return lstHours - REFERENCE_LST_H;
}

export function assignDelayBin(delay: number): string | null {
  for (let index = 0; index < DELAY_BIN_EDGES.length - 1; index += 1) {
    const low = DELAY_BIN_EDGES[index];
    const high = DELAY_BIN_EDGES[index + 1];
    if (delay > low && delay <= high) return DELAY_BIN_LABELS[index];
  }
  return null;
}

export function dateCovered(
  isoDate: string,
  windowStarts: ReadonlyArray<string>,
  windowDays: number,
): boolean {
  if (!isoDate) return false;
  const target = Date.parse(`${isoDate}T00:00:00Z`);
  if (!Number.isFinite(target)) return false;
  return windowStarts.some((start) => {
    const begin = Date.parse(`${start}T00:00:00Z`);
    const end = begin + windowDays * 86_400_000;
    return target >= begin && target < end;
  });
}

export function activeWindowFor(
  isoDate: string,
  windowStarts: ReadonlyArray<string>,
  windowDays: number,
): string | null {
  const target = Date.parse(`${isoDate}T00:00:00Z`);
  if (!Number.isFinite(target)) return null;
  for (const start of windowStarts) {
    const begin = Date.parse(`${start}T00:00:00Z`);
    const end = begin + windowDays * 86_400_000;
    if (target >= begin && target < end) return start;
  }
  return null;
}

/** Exponential slider mapping for FRP: 0.001 MW .. 5,000 MW. */
export const FRP_SLIDER_MIN_MW = 0.001;
export const FRP_SLIDER_MAX_MW = 5_000;

export function frpFromSlider(position: number, min = FRP_SLIDER_MIN_MW, max = FRP_SLIDER_MAX_MW): number {
  const t = Math.min(1, Math.max(0, position / 1000));
  return min * Math.pow(max / min, t);
}

export function sliderFromFrp(value: number, min = FRP_SLIDER_MIN_MW, max = FRP_SLIDER_MAX_MW): number {
  const clamped = Math.min(max, Math.max(min, value));
  return Math.round((Math.log(clamped / min) / Math.log(max / min)) * 1000);
}

export interface FlagDescriptor {
  bit: number;
  mask: number;
  name: string;
  state: string;
  reserved: boolean;
  set: boolean;
}

export function describeFlags(flags: number): FlagDescriptor[] {
  return FLAG_BITS.map((entry) => ({
    ...entry,
    set: (flags & entry.mask) !== 0,
  }));
}

export function flagState(flags: number): "validated" | "flagged" | "excluded" {
  if ((flags & (1 << 0)) !== 0) return "excluded";
  if ((flags & (1 << 1)) !== 0 || (flags & (1 << 2)) !== 0) return "flagged";
  return "validated";
}

export function delayBinBounds(label: string): [number, number] | null {
  const index = DELAY_BIN_LABELS.indexOf(label);
  if (index < 0) return null;
  return [DELAY_BIN_EDGES[index], DELAY_BIN_EDGES[index + 1]];
}

export function modelFamily(model: string): "operational" | "research" {
  return model === "M" || model === "PR" ? "research" : "operational";
}

export const MODEL_ROLES: Record<string, string> = {
  B0: "No correction",
  B1: "Global multiplicative correction",
  B2: "Regional multiplicative correction",
  P: "Physics diurnal shape",
  H: "Physics + regional offsets",
  M: "Gradient-boosted trees",
  PR: "Physics + boosted residual",
};

export const MODEL_SHORT: Record<string, string> = {
  B0: "Raw",
  B1: "Global",
  B2: "Regional",
  P: "Physics",
  H: "Physics+offsets",
  M: "Boosted",
  PR: "Physics+boost",
};
