/**
 * Typed view of the frozen results payload, the L6 API contract and the
 * read-only explorer endpoints.  Nothing here computes science: these are
 * purely the shapes the backend already serves.
 */

export type ModelId = "B0" | "B1" | "B2" | "P" | "H" | "M" | "PR";

export interface Provenance {
  cell_days_sha256: string;
  config_hash: string;
  data_hash: string;
  data_hash_begins: string;
  generated_at_utc: string;
  git_commit: string;
  l1_canonical_sha256: string;
  library_versions: Record<string, string>;
  model_artifact: string;
  model_artifact_sha256: string;
  pairs_sha256: string;
  pipeline_version: string;
  runtime_s: number;
  source_archive_sha256: string;
}

export interface RegionBounds {
  lat_min: number;
  lat_max: number;
  lon_min: number;
  lon_max: number;
  rows: number;
}

export interface Dataset {
  date_max: string;
  date_min: string;
  flags: {
    frp_not_above_zero: number;
    night: number;
    type_not_0: number;
  };
  region_bounds: Record<string, RegionBounds>;
  regions: number;
  rows: number;
  rows_by_region: Record<string, number>;
  rows_by_satellite: Record<string, number>;
  rows_by_year: Record<string, number>;
  validated_by_satellite: Record<string, number>;
  validated_rows: number;
  window_days: number;
  window_starts: string[];
  windows: number;
}

export interface PairRegionSummary {
  delay_mean_h: number;
  delay_median_h: number;
  n: number;
  raw_bias: number;
  raw_rmse: number;
  share: number;
}

export interface Pairs {
  aqua_cell_days: number;
  by_region: Record<string, number>;
  count: number;
  delay_ref_max_h: number;
  delay_ref_mean_h: number;
  delay_ref_median_h: number;
  delay_ref_min_h: number;
  noaa20_snpp_pairs: number;
  region_summary: Record<string, PairRegionSummary>;
  share_by_region: Record<string, number>;
  snpp_cell_days: number;
  terra_pairs: number;
  y_mean: number;
  y_std: number;
}

export interface GateBin {
  applicable: boolean;
  bin: string;
  calibration_n: number;
  coverage: number;
  fallback_pooled: boolean;
  quantile: number;
  reason: string | null;
}

export interface GateDomain {
  delay_high: number;
  delay_low: number;
  regions: string[];
  scan_high: number;
  scan_low: number;
}

export interface Gate {
  alpha: number;
  bins: Record<string, GateBin>;
  coverage_floor: number;
  domain: GateDomain;
  min_calibration_pairs: number;
  nominal_coverage: number;
}

export interface CoverageBin {
  bin: string;
  coverage: number;
  covered: number;
  n: number;
  quantile: number;
}

export interface CalibrationBin {
  bin: string;
  fallback_pooled: boolean;
  median_width_factor: number;
  n: number;
  quantile: number;
  width_factor: number;
}

export interface Uncertainty {
  alpha: number;
  bin_order: string[];
  calibration: Record<string, CalibrationBin>;
  in_sample: Record<string, CoverageBin>;
  in_sample_coverage: number;
  nested: Record<string, CoverageBin>;
  nominal_coverage: number;
  overall_coverage: number;
}

export interface Metric {
  bias: number;
  mae: number;
  n: number;
  rmse: number;
}

export interface LoyoRegion {
  n: number;
  B0: Metric;
  H: Metric;
  P: Metric;
}

export interface FoldResult {
  n_test: number;
  n_train: number;
  [model: string]: Metric | number;
}

export interface ModelParams {
  b: number;
  c: number;
  offsets?: Record<string, number>;
  sigma: number;
  t0: number;
}

export interface Selection {
  folds: Record<string, FoldResult>;
  mean_rmse: Record<string, number>;
  winner: string;
  years: number[];
}

export interface ModelsData {
  available: string[];
  grouped_cv: Record<string, Metric>;
  loyo: Record<string, LoyoRegion>;
  params: Record<string, ModelParams>;
  selection: Selection;
  served: string;
  served_note: string;
}

export interface BiasBin {
  corrected_bias: number;
  corrected_rmse: number;
  n: number;
  raw_bias: number;
  raw_rmse: number;
}

export interface FreTrend {
  available: boolean;
  ci_high_percent: number;
  ci_low_percent: number;
  naive_slope_percent_per_year: number;
  significant: boolean;
  unit: string;
  yearly_frp: Record<string, number>;
}

export interface Identifiability {
  available: boolean;
  block_level_se: number | null;
  cell_level_se: number;
  independent_unit: string;
  mean_bias: number;
  n_blocks: number;
  n_cells: number;
}

export interface PairingStat {
  ci_high: number;
  ci_low: number;
  iterations: number;
  n: number;
  n_blocks: number;
  slope_per_hour: number;
}

export interface PairingSensitivity {
  cell_day_sum: PairingStat;
  near_coincident: PairingStat;
  near_coincident_n: number;
}

export interface TerraExtrapolation {
  available: boolean;
  delay_mean_h: number;
  h_rmse: number;
  n: number;
  physics_rmse: number;
  raw_bias: number;
  raw_rmse: number;
}

export interface AuditData {
  bias_by_bin: Record<string, BiasBin>;
  fre_trend: FreTrend;
  identifiability: Identifiability;
  not_evaluated: string[];
  pairing_sensitivity: PairingSensitivity;
  pending: string[];
  terra_extrapolation: TerraExtrapolation;
}

export interface ValidityBin {
  applicable: number;
  coverage: number | null;
  gate_reason?: string | null;
  n: number;
  raw_bias: number;
}

export interface ValidityRegion {
  bins: Record<string, ValidityBin>;
  n_pairs: number;
  share: number;
}

export type ValidityMap = Record<string, ValidityRegion>;

export interface ActualExample {
  cell: string;
  date: string;
  delay_h: number;
  detections: number;
  frp_aqua_mw: number;
  lst_aqua_h: number;
  observed_frp_snpp_mw: number;
  region: string;
  scan_aqua: number;
}

export interface IngestionSource {
  sensor_key: string;
  filename: string;
  path: string;
  sha256: string;
  bytes: number;
  rows: number;
  columns: string[];
  satellites: string[];
}

export interface IngestionCheck {
  actual: unknown;
  expected: unknown;
  passed: boolean;
}

export interface IngestionVerification {
  passed: boolean;
  checks: Record<string, IngestionCheck>;
  failed: string[];
  expected_source: string;
}

export interface IngestionReport {
  schema_version: string;
  status: string;
  generated_at_utc: string;
  source_policy: string;
  data_hash: string;
  data_hash_expected: string;
  hash_verified: boolean;
  sources: IngestionSource[];
  dataset: Dataset;
  pairs: Pairs;
  verification: IngestionVerification;
  live_harmonization_endpoint: string;
  limitations: string[];
}

export interface LiveHarmonizationMetrics {
  n: number;
  applicable: number;
  refused: number;
  coverage: number | null;
  raw_rmse: number | null;
  harmonized_rmse: number | null;
  mean_correction_percent: number | null;
}

export interface LiveHarmonizationExample {
  cell: string;
  region: string;
  date: string;
  delay_h: number;
  delay_bin: string;
  frp_aqua_mw: number;
  observed_frp_snpp_mw: number;
  harmonized_frp_mw: number;
  interval_lower_mw: number;
  interval_upper_mw: number;
  correction_percent: number;
  covered: boolean;
}

export interface LiveHarmonization {
  schema_version: string;
  method: string;
  interpretation: string;
  n_pairs: number;
  n_applicable: number;
  n_refused: number;
  refusals: Record<string, number>;
  coverage: number | null;
  coverage_n: number;
  raw_rmse: number | null;
  harmonized_rmse: number | null;
  mean_correction_percent: number | null;
  median_correction_percent: number | null;
  by_bin: Record<string, LiveHarmonizationMetrics>;
  by_region: Record<string, LiveHarmonizationMetrics>;
  examples: LiveHarmonizationExample[];
  provenance: { data_hash: string; model: string };
}

export interface Results {
  actual_examples: ActualExample[];
  audit: AuditData;
  dataset: Dataset;
  gate: Gate;
  generated_at_utc: string;
  limitations: string[];
  live_ingestion?: IngestionReport;
  models: ModelsData;
  pairs: Pairs;
  provenance: Provenance;
  schema_version: string;
  uncertainty: Uncertainty;
  validity_map: ValidityMap;
}

export interface GridConfig {
  cell_size_degrees: number;
  snap_rule: string;
  latitude_range: [number, number];
  longitude_range: [number, number];
}

export interface AppConfig {
  aggregator_config_hash: string;
  data_hash: string;
  served_model: string;
  model_labels: Record<string, string>;
  regions: string[];
  limitations: string[];
  nominal_coverage: number;
  alpha: number;
  max_cells: number;
  refusal_codes: string[];
  windows: string[];
  window_days: number;
  domain: GateDomain;
  gate: {
    min_calibration_pairs: number;
    coverage_floor: number;
  };
  examples: ActualExample[];
  grid: GridConfig;
}

export interface VersionData {
  name: string;
  version: string;
  served_model: string;
  schema_version: string;
  pipeline_version: string;
  data_hash: string;
  data_hash_begins: string;
  config_hash: string;
  git_commit: string;
  model_artifact_sha256: string;
  results_sha256: string;
  library_versions: Record<string, string>;
  limitations: string[];
}

export interface HealthData {
  status: string;
  model_loaded: boolean;
  model: string;
  served_model: string;
  data_hash_begins: string;
  config_hash_begins: string;
  artifact_sha256_begins: string;
  results_sha256_begins: string;
  dataset_rows: number;
  pairs: number;
  ingestion_verified: boolean;
  ingestion_sources: number;
  ingestion_rows: number;
}

export interface HarmonizeCell {
  region: string;
  cell: string;
  cell_lat: number;
  cell_lon: number;
  cell_bounds: { lat: [number, number]; lon: [number, number] };
  input_latitude: number;
  input_longitude: number;
  lst_aqua_h: number;
  lst_display: string;
  delay_h: number;
  delay_bin: string | null;
  original_frp_mw: number;
  predicted_log_ratio: number | null;
  harmonized_frp_mw: number | null;
  correction_percent: number | null;
  interval_lower_mw: number | null;
  interval_upper_mw: number | null;
  interval_width_mw: number | null;
  quantile_log: number | null;
  interval_level: number;
  applicable: boolean;
  reason: string | null;
  refusal_message: string | null;
  calibration_n: number;
  coverage: number | null;
  delay_in_domain: boolean;
  scan_in_domain: boolean;
  region_in_domain: boolean;
}

export interface RegionalContext {
  available: boolean;
  h_rmse: number | null;
  raw_rmse: number | null;
  caution: boolean;
  note: string;
}

export interface HarmonizeResponse {
  cells: HarmonizeCell[];
  count: number;
  model: string;
  prediction_level: number;
  regional_context: Record<string, RegionalContext>;
  refusals: string[];
  limitations: string[];
  provenance: {
    data_hash: string;
    config_hash: string;
    model_artifact_sha256: string;
    results_sha256: string;
    pipeline_version: string;
  };
  gate_version: {
    alpha: number;
    min_calibration_pairs: number;
    coverage_floor: number;
  };
}

export interface ApiErrorDetail {
  code?: string;
  message?: string;
  fields?: Array<{ field: string; message: string; type: string }>;
  [key: string]: unknown;
}

export interface ObservationRow {
  observation_id: string;
  satellite: string;
  region: string;
  latitude: number;
  longitude: number;
  cell: string;
  date: string;
  window_start: string;
  utc: string;
  lst: number;
  lst_display: string;
  lst_derivation: string;
  frp_mw: number;
  scan_km: number;
  track_km: number;
  status: string;
  flags_uint8: number;
  time_was_padded: boolean;
}

export interface ObservationsPage {
  total: number;
  page: number;
  page_size: number;
  pages: number;
  has_more: boolean;
  sort_by: string;
  sort_dir: string;
  rows: ObservationRow[];
}

export interface SatelliteYearLst {
  satellite: string;
  year: number;
  n: number;
  lst_median_h: number;
  lst_p05_h: number;
  lst_p95_h: number;
  lst_median_display: string;
}

export interface FrpBySatellite {
  satellite: string;
  n: number;
  median_mw: number;
  p95_mw: number;
  max_mw: number;
}

export interface SparseNote {
  year: number;
  region: string;
  raw_rows: number;
  matched_pairs: number;
  message: string;
}

export interface ObservationsSummary {
  satellite_year_lst: SatelliteYearLst[];
  frp_by_satellite: FrpBySatellite[];
  status_counts: Record<string, number>;
  daynight_counts: Record<string, number>;
  pairs_by_year_region: Record<string, Record<string, number>>;
  sparse_notes: SparseNote[];
  windows: string[];
  window_days: number;
  active_dates: string[];
  status_definition: Record<string, string>;
}

export interface DigitalTwinBin {
  n: number;
  injected_log_offset: number;
  recovered_log_offset: number;
  absolute_error: number;
  within_tolerance: boolean;
}

export interface DigitalTwin {
  available: boolean;
  tolerance_log_units: number;
  max_absolute_error: number | null;
  passed: boolean;
  bins: Record<string, DigitalTwinBin>;
  validation_status: string;
  note: string;
  reason?: string;
}
