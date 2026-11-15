import { useEffect, useMemo, useRef, useState } from "react";
import { MapContainer, Polygon, Rectangle, TileLayer, Tooltip as LeafletTooltip, useMap } from "react-leaflet";
import type { LatLngBoundsExpression, LatLngExpression } from "leaflet";
import { Play, RotateCcw } from "lucide-react";
import type { RegionBounds } from "../lib/types";
import { fmtInt, fmtNum, fmtPct, humanRegion } from "../lib/format";
import { Badge } from "./ui";

interface RegionMapProps {
  regionBounds: Record<string, RegionBounds>;
  shareByRegion: Record<string, number>;
  regionSummary: Record<string, { delay_median_h: number; n: number; raw_bias: number; raw_rmse: number; share: number }>;
}

const TILE_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const WORLD_BOUNDS: LatLngBoundsExpression = [
  [-85, -180],
  [85, 180],
];

function FitRegions({ bounds }: { bounds: LatLngBoundsExpression }) {
  const map = useMap();
  useEffect(() => {
    map.fitBounds(bounds, { padding: [26, 26] });
  }, [map, bounds]);
  return null;
}

function easeOutCubic(value: number): number {
  return 1 - Math.pow(1 - value, 3);
}

export function RegionMap({ regionBounds, shareByRegion, regionSummary }: RegionMapProps) {
  const names = useMemo(
    () => Object.keys(regionBounds).sort((a, b) => (shareByRegion[b] ?? 0) - (shareByRegion[a] ?? 0)),
    [regionBounds, shareByRegion],
  );
  const [selected, setSelected] = useState<string>(names[0] ?? "Southern_Africa");
  const [phase, setPhase] = useState(1);
  const frame = useRef<number | null>(null);

  const overallBounds = useMemo<LatLngBoundsExpression>(() => {
    const entries = Object.values(regionBounds);
    if (entries.length === 0) return [[-45, -130], [46, 156]];
    return [
      [
        Math.min(...entries.map((entry) => entry.lat_min)),
        Math.min(...entries.map((entry) => entry.lon_min)),
      ],
      [
        Math.max(...entries.map((entry) => entry.lat_max)),
        Math.max(...entries.map((entry) => entry.lon_max)),
      ],
    ];
  }, [regionBounds]);

  const animate = useMemo(
    () => () => {
      if (frame.current !== null) cancelAnimationFrame(frame.current);
      const start = performance.now();
      const duration = 950;
      setPhase(0);
      const tick = (now: number) => {
        const t = Math.min(1, (now - start) / duration);
        setPhase(easeOutCubic(t));
        if (t < 1) frame.current = requestAnimationFrame(tick);
      };
      frame.current = requestAnimationFrame(tick);
    },
    [],
  );

  useEffect(() => {
    animate();
    return () => {
      if (frame.current !== null) cancelAnimationFrame(frame.current);
    };
  }, [selected, animate]);

  const bounds = regionBounds[selected];
  const shareMax = Math.max(1e-9, ...names.map((name) => shareByRegion[name] ?? 0));
  const share = shareByRegion[selected] ?? 0;
  const relativeScale = 0.32 + 0.68 * Math.sqrt(share / shareMax);

  const bowtie = useMemo(() => {
    if (!bounds) return null;
    const centerLat = (bounds.lat_min + bounds.lat_max) / 2;
    const centerLon = (bounds.lon_min + bounds.lon_max) / 2;
    const latSpan = Math.max(1, bounds.lat_max - bounds.lat_min);
    const lonSpan = Math.max(1, bounds.lon_max - bounds.lon_min);
    const radius = Math.max(latSpan, lonSpan) * 0.55 * relativeScale * phase;
    const rx = Math.max(radius * 0.62, 0.35 * phase);
    const ry = Math.max(radius, 0.35 * phase);
    const center: LatLngExpression = [centerLat, centerLon];
    const right: LatLngExpression[] = [
      center,
      [centerLat + ry, centerLon + rx],
      [centerLat - ry, centerLon + rx],
    ];
    const left: LatLngExpression[] = [
      center,
      [centerLat + ry, centerLon - rx],
      [centerLat - ry, centerLon - rx],
    ];
    return { center, right, left, centerLat, centerLon };
  }, [bounds, relativeScale, phase]);

  const summary = regionSummary[selected];

  return (
    <div>
      <div className="map-frame">
        <MapContainer
          center={[0, 20]}
          zoom={2}
          minZoom={2}
          maxBounds={WORLD_BOUNDS}
          maxBoundsViscosity={1.0}
          worldCopyJump={false}
          scrollWheelZoom={false}
          style={{ height: "100%", width: "100%" }}
          attributionControl
        >
          <TileLayer
            url={TILE_URL}
            attribution={TILE_ATTRIBUTION}
            subdomains="abc"
            maxZoom={19}
            noWrap
            bounds={WORLD_BOUNDS}
          />
          <FitRegions bounds={overallBounds} />
          {names.map((name) => {
            const entry = regionBounds[name];
            const active = name === selected;
            const regionBoundsExpression: LatLngBoundsExpression = [
              [entry.lat_min, entry.lon_min],
              [entry.lat_max, entry.lon_max],
            ];
            return (
              <Rectangle
                key={name}
                bounds={regionBoundsExpression}
                pathOptions={{
                  color: active ? "#526B5B" : "#8FA793",
                  weight: active ? 2 : 1,
                  fillColor: active ? "#526B5B" : "#B9C6B7",
                  fillOpacity: active ? 0.16 : 0.08,
                  dashArray: active ? undefined : "4 4",
                }}
                eventHandlers={{ click: () => setSelected(name) }}
              >
                <LeafletTooltip sticky>
                  <div style={{ fontSize: 11 }}>
                    <b>{humanRegion(name)}</b>
                    <br />
                    {fmtInt(entry.rows)} raw rows · {fmtPct(shareByRegion[name] ?? 0)} of pairs
                  </div>
                </LeafletTooltip>
              </Rectangle>
            );
          })}
          {bowtie && (
            <>
              <Polygon
                positions={bowtie.right}
                pathOptions={{
                  color: "#B66F4D",
                  weight: 1.2,
                  fillColor: "#C77B43",
                  fillOpacity: 0.13,
                  dashArray: "3 3",
                }}
              />
              <Polygon
                positions={bowtie.left}
                pathOptions={{
                  color: "#B66F4D",
                  weight: 1.2,
                  fillColor: "#C77B43",
                  fillOpacity: 0.13,
                  dashArray: "3 3",
                }}
              >
                <LeafletTooltip permanent direction="top" offset={[0, -4]} opacity={0.94}>
                  <span style={{ fontSize: 10 }}>
                    Schematic bowtie · {humanRegion(selected)}
                  </span>
                </LeafletTooltip>
              </Polygon>
            </>
          )}
        </MapContainer>
      </div>

      <div className="bowtie-slider mt-sm">
        <span className="mono text-[9.5px] whitespace-nowrap">FOOTPRINT EXPANSION</span>
        <input
          type="range"
          min={0}
          max={100}
          value={Math.round(phase * 100)}
          onChange={(event) => {
            if (frame.current !== null) cancelAnimationFrame(frame.current);
            setPhase(Number(event.target.value) / 100);
          }}
          aria-label="Bowtie footprint expansion"
        />
        <span className="mono text-[9.5px] w-9 text-right">{Math.round(phase * 100)}%</span>
        <button type="button" className="btn secondary small" onClick={animate} title="Replay expansion">
          <RotateCcw size={11} /> Replay
        </button>
      </div>

      <div className="grid two mt-sm" style={{ gap: 8 }}>
        {names.map((name) => {
          const entry = regionBounds[name];
          const regionShare = shareByRegion[name] ?? 0;
          const active = name === selected;
          return (
            <button
              key={name}
              type="button"
              className={`region-tile${active ? " active" : ""}`}
              onClick={() => setSelected(name)}
            >
              <span className="region-name">{humanRegion(name)}</span>
              <span className="mono text-[9.5px] text-[#747873]">
                {fmtPct(regionShare)} pairs · {fmtInt(entry.rows)} rows
              </span>
            </button>
          );
        })}
      </div>

      <div className="callout neutral mt-sm">
        <span className="callout-title">What the bowtie is — and is not</span>
        Rectangles are the measured latitude/longitude envelopes of validated observations. The
        bowtie expands from the region centroid in proportion to that region&apos;s share of matched
        pairs. It is a <b>schematic sampling-footprint indicator</b>, not a fire perimeter, not an
        individual fire location, and not an uncertainty estimate.
      </div>

      {bounds && summary && (
        <div className="flex flex-wrap items-center gap-2 mt-sm">
          <Badge tone="ok">{humanRegion(selected)} selected</Badge>
          <span className="tiny muted">
            {fmtInt(summary.n)} pairs · median delay {fmtNum(summary.delay_median_h, 3)} h · raw RMSE{" "}
            {fmtNum(summary.raw_rmse, 3)} ln
          </span>
          <span className="tiny muted mono ml-auto">
            cell bounds {fmtNum(bounds.lat_min, 1)}..{fmtNum(bounds.lat_max, 1)}° lat /{" "}
            {fmtNum(bounds.lon_min, 1)}..{fmtNum(bounds.lon_max, 1)}° lon
          </span>
        </div>
      )}
    </div>
  );
}
