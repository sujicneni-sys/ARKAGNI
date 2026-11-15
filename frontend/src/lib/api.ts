import type {
  AppConfig,
  DigitalTwin,
  HarmonizeResponse,
  HealthData,
  IngestionReport,
  LiveHarmonization,
  ObservationsPage,
  ObservationsSummary,
  Results,
  VersionData,
} from "./types";

// Same-origin by default: in production the FastAPI service serves the built
// SPA from its own port, so every request must stay relative.  Only set
// VITE_API_URL (or the legacy VITE_API_BASE) when the API lives elsewhere.
const API_BASE = (
  import.meta.env.VITE_API_URL ??
  import.meta.env.VITE_API_BASE ??
  ""
).replace(/\/$/, "");

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(message: string, status: number, detail: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function describeDetail(detail: unknown): string {
  if (!detail) return "The service returned an empty error body.";
  if (typeof detail === "string") return detail;
  if (typeof detail === "object") {
    const record = detail as Record<string, unknown>;
    if (typeof record.message === "string") {
      const fields = Array.isArray(record.fields) ? record.fields : [];
      if (fields.length > 0) {
        const labels = fields
          .map((field) => {
            const entry = field as Record<string, unknown>;
            return `${String(entry.field ?? "request")}: ${String(entry.message ?? "invalid")}`;
          })
          .join(" · ");
        return `${record.message} ${labels}`;
      }
      return record.message;
    }
  }
  try {
    return JSON.stringify(detail);
  } catch {
    return String(detail);
  }
}

async function readPayload<T>(response: Response): Promise<T> {
  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }

  if (!response.ok) {
    const detail =
      body && typeof body === "object" && "detail" in (body as Record<string, unknown>)
        ? (body as Record<string, unknown>).detail
        : body;
    throw new ApiError(describeDetail(detail), response.status, detail);
  }
  return body as T;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...(init?.headers ?? {}),
      },
    });
  } catch (error) {
    throw new ApiError(
      `Cannot reach the Arkagni API at ${API_BASE || "this origin"}. Is the service running?`,
      0,
      String(error),
    );
  }

  return readPayload<T>(response);
}

export function getResults(): Promise<Results> {
  return request<Results>("/results");
}

export function getConfig(): Promise<AppConfig> {
  return request<AppConfig>("/config");
}

export function getVersion(): Promise<VersionData> {
  return request<VersionData>("/version");
}

export function getHealth(): Promise<HealthData> {
  return request<HealthData>("/health");
}

export function getIngestion(): Promise<IngestionReport> {
  return request<IngestionReport>("/ingestion");
}

export function getIngestionHarmonization(): Promise<LiveHarmonization> {
  return request<LiveHarmonization>("/ingestion/harmonization");
}

export interface ObservationsQuery {
  region?: string;
  satellite?: string;
  year?: string;
  status?: string;
  daynight?: string;
  search?: string;
  sortBy?: string;
  sortDir?: "asc" | "desc";
  page?: number;
  pageSize?: number;
}

export function getObservations(query: ObservationsQuery): Promise<ObservationsPage> {
  const params = new URLSearchParams();
  if (query.region) params.set("region", query.region);
  if (query.satellite) params.set("satellite", query.satellite);
  if (query.year) params.set("year", query.year);
  if (query.status) params.set("status", query.status);
  if (query.daynight) params.set("daynight", query.daynight);
  if (query.search) params.set("search", query.search);
  if (query.sortBy) params.set("sort_by", query.sortBy);
  if (query.sortDir) params.set("sort_dir", query.sortDir);
  if (query.page) params.set("page", String(query.page));
  if (query.pageSize) params.set("page_size", String(query.pageSize));
  return request<ObservationsPage>(`/observations?${params.toString()}`);
}

export function getObservationsSummary(): Promise<ObservationsSummary> {
  return request<ObservationsSummary>("/observations/summary");
}

export function getDigitalTwin(): Promise<DigitalTwin> {
  return request<{ digital_twin: DigitalTwin }>("/audit/digital-twin").then(
    (payload) => payload.digital_twin,
  );
}

export interface HarmonizePayload {
  aggregator_config_hash: string;
  region: string[];
  date?: string[];
  latitude?: number[];
  longitude?: number[];
  cell_lat?: number[];
  cell_lon?: number[];
  frp_aqua_mw: number[];
  detections: number[];
  lst_aqua_h?: number[];
  acquisition_time_utc?: string[];
  scan_aqua: number[];
  area_ratio?: number[];
}

export function harmonize(payload: HarmonizePayload): Promise<HarmonizeResponse> {
  return request<HarmonizeResponse>("/harmonize", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * Upload a CSV/Parquet batch to the public live-analysis endpoint. The file is
 * sent as raw bytes; the backend parses it and routes every row through the
 * same L5 harmonization core used by POST /harmonize.
 */
export async function analyzeFile(file: File): Promise<HarmonizeResponse> {
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE}/live-analysis?filename=${encodeURIComponent(file.name)}`,
      {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": file.type || "application/octet-stream",
        },
        body: file,
      },
    );
  } catch (error) {
    throw new ApiError(
      `Cannot reach the Arkagni API at ${API_BASE || "this origin"}. Is the service running?`,
      0,
      String(error),
    );
  }
  return readPayload<HarmonizeResponse>(response);
}
