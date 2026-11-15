import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { Activity, Menu, X } from "lucide-react";
import { useAppData } from "../context/AppData";
import { fmtHash, fmtInt, fmtNum, fmtPct } from "../lib/format";
import { Badge } from "./ui";

interface PageMeta {
  path: string;
  index: string;
  label: string;
  title: string;
  description: string;
}

export const PAGES: PageMeta[] = [
  {
    path: "/",
    index: "01",
    label: "Overview",
    title: "Satellite Fire Data Harmonization",
    description:
      "Correcting timing-related FRP differences between Aqua MODIS and Suomi-NPP VIIRS, with measured uncertainty.",
  },
  {
    path: "/explorer",
    index: "02",
    label: "Data Explorer",
    title: "Data Explorer",
    description:
      "Actual L1 records, composition, dual UTC/LST display, ingest calendar and validation state.",
  },
  {
    path: "/harmonization",
    index: "03",
    label: "FRP Harmonization",
    title: "FRP Harmonization",
    description:
      "Map one Aqua cell-day to the SNPP 13.6 h reference, or receive a stated refusal.",
  },
  {
    path: "/uncertainty",
    index: "04",
    label: "Uncertainty Analysis",
    title: "Uncertainty Analysis",
    description:
      "Conformal coverage, interval behaviour and the pre-registered applicability domain.",
  },
  {
    path: "/models",
    index: "05",
    label: "Model Comparison",
    title: "Model Comparison",
    description:
      "Seven correction approaches, grouped cross-validation, and the governance boundary around the served model.",
  },
  {
    path: "/audit",
    index: "06",
    label: "Audit & Validation",
    title: "Audit & Validation",
    description:
      "Folds, regional transfer, pairing sensitivity, Terra out-of-regime evidence and unresolved weaknesses.",
  },
  {
    path: "/live",
    index: "07",
    label: "Live Analysis",
    title: "Live Analysis",
    description:
      "Upload a small CSV or Parquet batch, or move one cell-day by hand, and read the verified result at a glance.",
  },
];

function pageFor(pathname: string): PageMeta {
  if (pathname === "/" || pathname === "") return PAGES[0];
  return PAGES.find((page) => page.path !== "/" && pathname.startsWith(page.path)) ?? PAGES[0];
}

/**
 * v9 release target. The score and coverage are never typed in here: they are
 * read from the verified results payload, and the served identity is read from
 * /health. If the registry is re-issued to another model, change this constant
 * in the same commit so the strip cannot drift from the artifacts.
 */
const V9_TARGET_MODEL = "PR";

export function Layout() {
  const { results, version, apiOnline, health } = useAppData();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const page = pageFor(location.pathname);

  const v9Metric = results?.models.grouped_cv[V9_TARGET_MODEL];
  const coverage = results?.uncertainty.overall_coverage;
  const nominal = results?.uncertainty.nominal_coverage ?? 0.8;
  const floor = results?.gate.coverage_floor ?? 0.7;
  const coverageTone =
    coverage === null || coverage === undefined
      ? "none"
      : coverage >= nominal
        ? "ok"
        : coverage >= floor
          ? "warn"
          : "bad";
  const servedModel = health?.served_model ?? health?.model ?? results?.models.served;
  const pairCount = results?.pairs.count ?? health?.pairs;

  useEffect(() => {
    setOpen(false);
    window.scrollTo({ top: 0, behavior: "auto" });
  }, [location.pathname]);

  useEffect(() => {
    document.title = `${page.title} · Arkagni`;
  }, [page.title]);

  return (
    <div className="shell">
      {open && <div className="rail-backdrop" onClick={() => setOpen(false)} aria-hidden />}
      <aside className={`rail${open ? " open" : ""}`}>
        <div className="brand">
          <div className="brand-mark">
            <div>
              <div className="brand-name">Arkagni</div>
              <div className="brand-sub">Cross-Sensor Fire Harmonization</div>
            </div>
          </div>
        </div>

        <nav className="nav" aria-label="Primary">
          {PAGES.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === "/"}
              className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
            >
              <span className="nav-index">{item.index}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="flex items-center gap-3 min-w-0">
            <button
              type="button"
              className="btn secondary small mobile-menu"
              aria-label={open ? "Close navigation" : "Open navigation"}
              onClick={() => setOpen((value) => !value)}
            >
              {open ? <X size={14} /> : <Menu size={14} />}
            </button>
            <div className="min-w-0">
              <div className="topbar-title">{page.title}</div>
              <div className="topbar-desc">{page.description}</div>
            </div>
          </div>
          <div className="topbar-status">
            <Badge
              tone={apiOnline && v9Metric ? "ok" : v9Metric ? "warn" : "none"}
              title={`v9 target model ${V9_TARGET_MODEL} · API ${
                apiOnline ? "live" : "offline"
              } · currently served ${servedModel ?? "—"}`}
            >
              Model {V9_TARGET_MODEL}
            </Badge>
            <Badge
              tone="plain"
              title={`${V9_TARGET_MODEL} grouped cross-validation RMSE in ln-ratio units, read from results.json`}
            >
              RMSE {fmtNum(v9Metric?.rmse, 3)}
            </Badge>
            <Badge
              tone={coverageTone}
              title={`Out-of-fold nested conformal coverage across all delay bins · nominal ${fmtPct(
                nominal,
              )} · floor ${fmtPct(floor)}`}
            >
              Coverage {fmtPct(coverage)}
            </Badge>
            <Badge tone="plain" title="Matched Aqua–Suomi-NPP pairs, read from results.json">
              <Activity size={11} strokeWidth={2.4} />
              {fmtInt(pairCount)} pairs
            </Badge>
          </div>
        </header>

        <main className="content">
          <Outlet />
        </main>

        <footer className="footer">
          <div>
            <b>Limitations stay visible:</b> four regions · five 5-day windows per year · no
            saturation/plume/canopy model · no correction beyond the calibrated delay domain.
          </div>
          <div>
            results <span className="mono">{fmtHash(version?.results_sha256)}</span> · model{" "}
            <span className="mono">{results?.models.served ?? "—"}</span> · config{" "}
            <span className="mono">{fmtHash(version?.config_hash)}</span>
          </div>
        </footer>
      </div>
    </div>
  );
}
