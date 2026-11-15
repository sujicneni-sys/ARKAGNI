import { Badge } from "./ui";
import { describeFlags } from "../lib/science";

export function FlagCell({ flags, status }: { flags: number; status: string }) {
  const bits = describeFlags(flags);
  const setBits = bits.filter((bit) => bit.set && !bit.reserved);
  const tone = status === "validated" ? "ok" : status === "flagged" ? "warn" : "bad";
  return (
    <div className="flex flex-col gap-1">
      <Badge tone={tone}>{status}</Badge>
      <div className="flag-stack" title={`uint8 ${flags} · bits 3–7 reserved / not evaluated`}>
        <span className="flag-bit">u8 {flags}</span>
        {setBits.length === 0 ? (
          <span className="flag-bit">no flags</span>
        ) : (
          setBits.map((bit) => (
            <span key={bit.bit} className="flag-bit set" title={`bit ${bit.bit}: ${bit.name}`}>
              b{bit.bit}
            </span>
          ))
        )}
        <span className="flag-bit reserved" title="bits 3–7 reserved: saturation, plume, canopy, two spare">
          rsv 3–7
        </span>
      </div>
    </div>
  );
}
