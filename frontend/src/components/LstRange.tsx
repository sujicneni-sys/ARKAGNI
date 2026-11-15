import type { SatelliteYearLst } from "../lib/types";
import { fmtInt } from "../lib/format";

const SATELLITE_COLOR: Record<string, string> = {
  Aqua: "#B66F4D",
  Terra: "#C77B43",
  N: "#526B5B",
  N20: "#788B91",
};

const SATELLITE_LABEL: Record<string, string> = {
  Aqua: "Aqua MODIS",
  Terra: "Terra MODIS",
  N: "Suomi-NPP VIIRS",
  N20: "NOAA-20 VIIRS",
};

export function LstRange({ rows }: { rows: SatelliteYearLst[] }) {
  const grouped = Object.entries(
    rows.reduce<Record<string, SatelliteYearLst[]>>((accumulator, row) => {
      (accumulator[row.satellite] ??= []).push(row);
      return accumulator;
    }, {}),
  ).sort(([a], [b]) => a.localeCompare(b));

  return (
    <div>
      <div className="flex justify-between mono text-[9px] text-[#747873] mb-1 ml-[118px] mr-[70px]">
        <span>00</span>
        <span>06</span>
        <span>12</span>
        <span>18</span>
        <span>24 LST</span>
      </div>
      <div className="relative">
        <div className="absolute left-[118px] right-[70px] top-0 bottom-0 flex justify-between pointer-events-none">
          {[0, 6, 12, 18, 24].map((hour) => (
            <div key={hour} className="border-l border-[#efede6] h-full" style={{ width: 0 }} />
          ))}
        </div>
        {grouped.map(([satellite, entries]) => (
          <div key={satellite} className="mb-2">
            <div className="flex items-center gap-1 mb-1 ml-[118px]">
              <i className="swatch" style={{ background: SATELLITE_COLOR[satellite] ?? "#526B5B" }} />
              <span className="text-[10px] font-semibold">{SATELLITE_LABEL[satellite] ?? satellite}</span>
            </div>
            {entries
              .sort((a, b) => a.year - b.year)
              .map((row) => {
                const low = Math.max(0, Math.min(24, row.lst_p05_h));
                const high = Math.max(0, Math.min(24, row.lst_p95_h));
                const median = Math.max(0, Math.min(24, row.lst_median_h));
                const color = SATELLITE_COLOR[satellite] ?? "#526B5B";
                return (
                  <div key={`${satellite}-${row.year}`} className="flex items-center h-[20px]">
                    <div className="w-[114px] flex-none text-right pr-2 mono text-[9.5px] text-[#747873]">
                      {row.year}
                    </div>
                    <div className="flex-1 relative h-[10px] rounded bg-[#f2f0e9]">
                      <div
                        className="absolute top-0 h-[10px] rounded"
                        style={{
                          left: `${(low / 24) * 100}%`,
                          width: `${((high - low) / 24) * 100}%`,
                          background: color,
                          opacity: 0.34,
                        }}
                      />
                      <div
                        className="absolute top-1/2 w-[2px] h-[14px] -translate-y-1/2"
                        style={{ left: `${(median / 24) * 100}%`, background: color }}
                        title={`median ${row.lst_median_display} LST`}
                      />
                    </div>
                    <div className="w-[68px] flex-none pl-2 mono text-[9px] text-[#292D2B] whitespace-nowrap">
                      {row.lst_median_display}
                    </div>
                    <div className="w-[54px] flex-none text-right mono text-[8.5px] text-[#747873]">
                      {fmtInt(row.n)}
                    </div>
                  </div>
                );
              })}
          </div>
        ))}
      </div>
    </div>
  );
}
