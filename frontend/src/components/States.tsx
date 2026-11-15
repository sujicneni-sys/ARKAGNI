import { AlertTriangle, RefreshCw } from "lucide-react";
import { useAppData } from "../context/AppData";
import { SkeletonPanel } from "./ui";

export function LoadingPage() {
  return (
    <div>
      <div className="page-head">
        <div>
          <div className="skeleton" style={{ height: 10, width: 150, marginBottom: 12 }} />
          <div className="skeleton" style={{ height: 40, width: "min(640px, 80%)", marginBottom: 12 }} />
          <div className="skeleton" style={{ height: 14, width: "min(760px, 92%)" }} />
        </div>
      </div>
      <div className="skeleton" style={{ height: 86, marginBottom: 16 }} />
      <div className="grid side">
        <SkeletonPanel height={360} />
        <SkeletonPanel height={360} />
      </div>
      <div className="grid two mt">
        <SkeletonPanel height={220} />
        <SkeletonPanel height={220} />
      </div>
    </div>
  );
}

export function ErrorPage({ message }: { message?: string | null }) {
  const { reload, apiOnline } = useAppData();
  return (
    <div className="panel" style={{ maxWidth: 760, margin: "40px auto" }}>
      <div className="flex items-start gap-3">
        <span className="text-[#A33C37] mt-[2px]">
          <AlertTriangle size={20} />
        </span>
        <div>
          <h2>The verified results payload is unavailable</h2>
          <p className="small muted mt-sm">
            {message ??
              "The dashboard reads only hash-verified server output. It will not substitute sample data or fabricated metrics."}
          </p>
          <div className="callout neutral mt">
            <span className="callout-title">How to bring the service up</span>
            From the project root run <code className="mono">docker compose up --build</code> or{" "}
            <code className="mono">.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000</code>.
            The dashboard is served from the same origin at <code className="mono">/</code>.
          </div>
          <div className="btn-row mt">
            <button type="button" className="btn" onClick={reload}>
              <RefreshCw size={13} /> Retry connection
            </button>
            <span className="small muted">
              API status: {apiOnline ? "reachable" : "not reachable"}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
