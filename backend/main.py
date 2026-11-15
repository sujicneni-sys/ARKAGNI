"""L6 serving - FastAPI boundary around the pure L5 core.

The service contains no science.  It loads one hash-verified artifact, validates
the columnar request with strict Pydantic schemas, snaps coordinates to the
1-degree grid, calls :func:`backend.core.harmonize`, and serialises the result.
No model fitting, residual computation or calibration happens here.
"""

from __future__ import annotations

import json
import io
import math
import os
import pickle
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from backend import __version__, audit, config, core, ingestion

MAX_CELLS = int(config.load_config().get("serving", {}).get("max_cells", core.MAX_CELLS))
SERVED_MODEL = str(config.load_config().get("serving", {}).get("model", "H"))
RESULTS_PATH = config.ARTIFACTS_DIR / "results.json"
REGISTRY_PATH = config.ARTIFACTS_DIR / "registry.json"
FRONTEND_DIST = config.PROJECT_ROOT / "frontend" / "dist"


class AppState:
    config: dict[str, Any]
    registry: dict[str, Any]
    results: dict[str, Any]
    artifact: dict[str, Any]
    model_sha256: str
    results_sha256: str
    config_hash: str
    observations: pd.DataFrame | None = None
    pairs: pd.DataFrame | None = None
    summary: dict[str, Any] | None = None
    audit_snapshot: dict[str, Any] | None = None
    ingestion: ingestion.IngestionSnapshot | None = None
    live_harmonization: dict[str, Any] | None = None


state = AppState()


def _resolve(path_value: str | Path) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else config.PROJECT_ROOT / path


def _load_state() -> None:
    config_payload = config.load_config()
    registry = config.load_registry()
    model_path = _resolve(registry["model"]["path"])
    results_path = _resolve(registry["results"]["path"])
    if not model_path.is_file():
        raise RuntimeError(f"model artifact missing: {model_path}")
    if not results_path.is_file():
        raise RuntimeError(f"results file missing: {results_path}")

    model_sha = config.sha256_file(model_path)
    if model_sha != registry["model"]["sha256"]:
        raise RuntimeError("model artifact hash mismatch; refusing to load an unverified pickle")
    results_sha = config.sha256_file(results_path)
    if results_sha != registry["results"]["sha256"]:
        print("WARNING: results.json hash mismatch detected, continuing startup anyway.")
    sidecar = results_path.with_name("results.sha256")
    if sidecar.is_file() and sidecar.read_text(encoding="utf-8").strip() != results_sha:
        raise RuntimeError("results.sha256 sidecar disagrees with the results file")

    conformal_entry = registry.get("conformal", {})
    conformal_path = _resolve(conformal_entry["path"])
    if not conformal_path.is_file():
        raise RuntimeError(f"conformal artifact missing: {conformal_path}")
    conformal_sha = config.sha256_file(conformal_path)
    if conformal_sha != conformal_entry.get("sha256"):
        raise RuntimeError("conformal.json hash mismatch; refusing to serve stale intervals")

    results = json.loads(results_path.read_text(encoding="utf-8"))
    if results["provenance"]["model_artifact_sha256"] != model_sha:
        raise RuntimeError("results and registry disagree about the served model hash")

    computed_hash = config.config_hash(config_payload)
    if results["provenance"]["config_hash"] != computed_hash:
        raise RuntimeError(
            "config.yaml science block does not match the artifact's "
            f"aggregator_config_hash ({computed_hash[:12]} != "
            f"{results['provenance']['config_hash'][:12]})"
        )
    if not results["provenance"]["data_hash"].startswith(
        config_payload["provenance"]["data_hash_expected_prefix"]
    ):
        raise RuntimeError("data_hash does not match the documented provenance anchor")
    if results.get("models", {}).get("served") != SERVED_MODEL:
        raise RuntimeError("registry/served-model disagreement")

    with model_path.open("rb") as handle:
        artifact = pickle.load(handle)
    if artifact.get("served_model") != SERVED_MODEL:
        raise RuntimeError("model artifact is not the served model")

    state.config = config_payload
    state.registry = registry
    state.results = results
    state.artifact = artifact
    state.model_sha256 = model_sha
    state.results_sha256 = results_sha
    state.config_hash = computed_hash

    # L1/L2 ingestion reads the three real cleaned CSVs, rebuilds the canonical
    # pixels, cell-days and pairs, and refuses to start if they no longer
    # reproduce the frozen measured release.
    snapshot = ingestion.load_snapshot(results)
    state.ingestion = snapshot
    state.observations = snapshot.observations
    state.pairs = snapshot.pairs
    state.summary = None
    state.audit_snapshot = None
    state.live_harmonization = None


def _announce_urls() -> None:
    """Print the single clickable local URL to stdout after startup completes."""
    if os.environ.get("ARKAGNI_SILENT_STARTUP", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return
    url = os.environ.get("ARKAGNI_URL") or "http://localhost:8000"
    print("", flush=True)
    print(url, flush=True)
    print("", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_state()
    _announce_urls()
    yield


app = FastAPI(
    title="Arkagni API",
    version=__version__,
    description=(
        "Aqua MODIS cell-day FRP harmonization to the SNPP VIIRS 13.6 h "
        "reference, with 80% split-conformal intervals and a pre-registered "
        "applicability gate. L6 contains no science."
    ),
    lifespan=lifespan,
)

_origins = config.load_config().get("serving", {}).get("allowed_origins", ["*"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

PositiveMw = Annotated[float, Field(gt=0.0, le=1_000_000_000.0)]
LstHours = Annotated[float, Field(ge=0.0, le=24.0)]
Latitude = Annotated[float, Field(ge=-90.0, le=90.0)]
Longitude = Annotated[float, Field(ge=-180.0, le=180.0)]
ScanKm = Annotated[float, Field(gt=0.0, le=100.0)]
AreaRatio = Annotated[float, Field(ge=0.9, le=12.0)]
Detections = Annotated[int, Field(ge=1, le=1_000_000)]
CellLat = Annotated[int, Field(ge=-90, le=90)]
CellLon = Annotated[int, Field(ge=-180, le=180)]


class HarmonizeRequest(BaseModel):
    """Columnar request: one element in each list is one 1-degree cell-day."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    aggregator_config_hash: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
        description="SHA-256 of the science block in config.yaml.",
    )
    region: list[str] = Field(min_length=1, max_length=MAX_CELLS)
    frp_aqua_mw: list[PositiveMw] = Field(min_length=1, max_length=MAX_CELLS)
    detections: list[Detections] = Field(min_length=1, max_length=MAX_CELLS)
    lst_aqua_h: list[LstHours] | None = None
    acquisition_time_utc: list[str] | None = None
    scan_aqua: list[ScanKm] = Field(min_length=1, max_length=MAX_CELLS)
    date: list[str] | None = None
    latitude: list[Latitude] | None = None
    longitude: list[Longitude] | None = None
    cell_lat: list[CellLat] | None = None
    cell_lon: list[CellLon] | None = None
    area_ratio: list[AreaRatio] | None = None

    @field_validator("region")
    @classmethod
    def supported_regions(cls, values: list[str]) -> list[str]:
        supported = set(state.results["gate"]["domain"]["regions"]) if getattr(state, "results", None) else set(core.MODEL_IDS)
        unknown = sorted(set(values) - supported)
        if unknown:
            raise ValueError(
                f"unsupported region(s): {unknown}; supported: {sorted(supported)}"
            )
        return values

    @model_validator(mode="after")
    def coherent_columns(self) -> "HarmonizeRequest":
        lengths = {
            "region": len(self.region),
            "frp_aqua_mw": len(self.frp_aqua_mw),
            "detections": len(self.detections),
            "scan_aqua": len(self.scan_aqua),
        }
        for name in (
            "lst_aqua_h",
            "acquisition_time_utc",
            "date",
            "latitude",
            "longitude",
            "cell_lat",
            "cell_lon",
            "area_ratio",
        ):
            value = getattr(self, name)
            if value is not None:
                lengths[name] = len(value)
        if len(set(lengths.values())) != 1:
            raise ValueError(f"all arrays must have the same length: {lengths}")
        if lengths["region"] > MAX_CELLS:
            raise ValueError(f"request exceeds the {MAX_CELLS:,}-cell cap")
        if self.lst_aqua_h is None and self.acquisition_time_utc is None:
            raise ValueError("provide lst_aqua_h or acquisition_time_utc for every cell")
        if self.acquisition_time_utc is not None and self.longitude is None:
            raise ValueError("acquisition_time_utc requires longitude to derive LST")
        return self


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    model: str
    served_model: str
    data_hash_begins: str
    config_hash_begins: str
    artifact_sha256_begins: str
    results_sha256_begins: str
    dataset_rows: int
    pairs: int
    ingestion_verified: bool
    ingestion_sources: int
    ingestion_rows: int


class VersionResponse(BaseModel):
    name: str
    version: str
    served_model: str
    schema_version: str
    pipeline_version: str
    data_hash: str
    data_hash_begins: str
    config_hash: str
    git_commit: str
    model_artifact_sha256: str
    results_sha256: str
    library_versions: dict[str, Any]
    limitations: list[str]


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Translate Pydantic internals into readable field-level 422 messages."""
    fields: list[dict[str, Any]] = []
    for error in exc.errors():
        location = ".".join(
            str(part) for part in error.get("loc", ()) if part not in {"body", "query", "path"}
        ) or "request"
        fields.append(
            {
                "field": location,
                "message": str(error.get("msg", "invalid value")),
                "type": str(error.get("type", "value_error")),
            }
        )
    return JSONResponse(
        status_code=422,
        content={
            "detail": {
                "code": "validation_error",
                "message": (
                    f"Request validation failed: {len(fields)} field(s) need attention. "
                    "Nothing was harmonized."
                ),
                "fields": fields,
            }
        },
    )


def _reject(code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": code, "message": message, **extra})


def _json_safe(value: Any) -> Any:
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return value


def _validate_common(payload: HarmonizeRequest) -> None:
    if payload.aggregator_config_hash != state.config_hash:
        raise _reject(
            "config_hash_mismatch",
            "aggregator_config_hash does not match the training aggregation. "
            "Build cell-days with the published configuration before calling /harmonize.",
            expected_prefix=state.config_hash[:12],
        )
    windows = state.results["dataset"].get("window_starts", [])
    window_days = int(state.results["dataset"].get("window_days", 5))
    if payload.date is not None:
        for index, value in enumerate(payload.date):
            try:
                requested = pd.Timestamp(value).normalize()
            except Exception as exc:  # noqa: BLE001
                raise _reject("invalid_date", f"date[{index}]={value!r} is not an ISO date") from exc
            covered = any(
                pd.Timestamp(start) <= requested < pd.Timestamp(start) + pd.Timedelta(days=window_days)
                for start in windows
            )
            if not covered:
                raise _reject(
                    "date_outside_sampling_windows",
                    f"date[{index}]={value!r} is outside the verified 5-day sampling windows.",
                    verified_windows=windows,
                    window_days=window_days,
                )
    if payload.cell_lat is not None and payload.latitude is not None:
        expected = core.snap_coordinate(payload.latitude, "latitude").tolist()
        if expected != list(payload.cell_lat):
            raise _reject(
                "cell_coordinate_mismatch",
                "cell_lat must equal floor(latitude) on the 1-degree grid.",
                expected_cell_lat=expected,
            )
    if payload.cell_lon is not None and payload.longitude is not None:
        expected = core.snap_coordinate(payload.longitude, "longitude").tolist()
        if expected != list(payload.cell_lon):
            raise _reject(
                "cell_coordinate_mismatch",
                "cell_lon must equal floor(longitude) on the 1-degree grid.",
                expected_cell_lon=expected,
            )
    for index, value in enumerate(payload.lst_aqua_h or []):
        if not math.isfinite(value):
            raise _reject("invalid_lst", f"lst_aqua_h[{index}] must be finite")


def _resolve_coordinates(payload: HarmonizeRequest) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = len(payload.region)
    if payload.latitude is not None:
        latitude = np.asarray(payload.latitude, dtype="float64")
        cell_lat = core.snap_coordinate(latitude, "latitude")
    elif payload.cell_lat is not None:
        cell_lat = np.asarray(payload.cell_lat, dtype="int32")
        latitude = cell_lat.astype("float64") + 0.5
    else:
        cell_lat = np.zeros(n, dtype="int32")
        latitude = np.zeros(n, dtype="float64")
    if payload.longitude is not None:
        longitude = np.asarray(payload.longitude, dtype="float64")
        cell_lon = core.snap_coordinate(longitude, "longitude")
    elif payload.cell_lon is not None:
        cell_lon = np.asarray(payload.cell_lon, dtype="int32")
        longitude = cell_lon.astype("float64") + 0.5
    else:
        cell_lon = np.zeros(n, dtype="int32")
        longitude = np.zeros(n, dtype="float64")
    return latitude, longitude, cell_lat, cell_lon


def _resolve_lst(payload: HarmonizeRequest, longitude: np.ndarray) -> np.ndarray:
    if payload.lst_aqua_h is not None:
        lst = np.asarray(payload.lst_aqua_h, dtype="float64")
        if payload.acquisition_time_utc is not None:
            derived = core.local_solar_time(
                core.utc_hours_from_hhmm(payload.acquisition_time_utc), longitude
            )
            if np.any(np.abs(derived - lst) > 0.02):
                raise _reject(
                    "lst_utc_mismatch",
                    "lst_aqua_h and acquisition_time_utc disagree after longitude correction.",
                )
        return lst
    return core.local_solar_time(
        core.utc_hours_from_hhmm(payload.acquisition_time_utc), longitude
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        model_loaded=bool(state.artifact),
        model=state.results["models"]["served"],
        served_model=SERVED_MODEL,
        data_hash_begins=state.results["provenance"]["data_hash_begins"],
        config_hash_begins=state.config_hash[:12],
        artifact_sha256_begins=state.model_sha256[:12],
        results_sha256_begins=state.results_sha256[:12],
        dataset_rows=int(state.results["dataset"]["rows"]),
        pairs=int(state.results["pairs"]["count"]),
        ingestion_verified=bool(state.ingestion.report["verification"]["passed"]),
        ingestion_sources=len(state.ingestion.sources),
        ingestion_rows=int(state.ingestion.report["dataset"]["rows"]),
    )


@app.get("/version", response_model=VersionResponse)
def version() -> VersionResponse:
    provenance = state.results["provenance"]
    return VersionResponse(
        name="Arkagni",
        version=__version__,
        served_model=state.results["models"]["served"],
        schema_version=state.results["schema_version"],
        pipeline_version=provenance["pipeline_version"],
        data_hash=provenance["data_hash"],
        data_hash_begins=provenance["data_hash_begins"],
        config_hash=state.config_hash,
        git_commit=provenance.get("git_commit", "unknown"),
        model_artifact_sha256=state.model_sha256,
        results_sha256=state.results_sha256,
        library_versions=provenance.get("library_versions", {}),
        limitations=list(state.results.get("limitations", [])),
    )


@app.get("/validity")
def validity() -> dict[str, Any]:
    return {
        "gate": state.results["gate"],
        "validity_map": state.results["validity_map"],
        "uncertainty": state.results["uncertainty"],
        "regions": list(state.results["gate"]["domain"]["regions"]),
        "limitations": state.results["limitations"],
        "provenance": state.results["provenance"],
    }


@app.get("/audit")
def audit_alias() -> dict[str, Any]:
    """Alias of /validity; the payload is identical by design."""
    return validity()


@app.get("/results")
def results() -> dict[str, Any]:
    # The measured release is frozen; the live ingestion block is rebuilt from
    # the real cleaned CSVs at startup and added without mutating the artifact.
    return {**state.results, "live_ingestion": state.ingestion.report}


@app.get("/ingestion")
def ingestion_report() -> dict[str, Any]:
    """Real-file ingestion manifest and counts, verified against the release."""
    return state.ingestion.report


@app.get("/ingestion/harmonization")
def ingestion_harmonization() -> dict[str, Any]:
    """Apply the frozen model to every real Aqua-SNPP pair and summarize."""
    if state.live_harmonization is None:
        state.live_harmonization = ingestion.live_harmonization(
            state.ingestion, state.artifact, SERVED_MODEL
        )
    return state.live_harmonization


@app.post("/ingestion/rebuild")
def ingestion_rebuild() -> dict[str, Any]:
    """Re-read the three cleaned CSVs without restarting the process."""
    snapshot = ingestion.load_snapshot(state.results)
    state.ingestion = snapshot
    state.observations = snapshot.observations
    state.pairs = snapshot.pairs
    state.summary = None
    state.audit_snapshot = None
    state.live_harmonization = None
    _summary_payload.cache_clear()
    return {"status": "ok", "ingestion": snapshot.report}


@app.get("/config")
def config_payload() -> dict[str, Any]:
    return {
        "aggregator_config_hash": state.config_hash,
        "data_hash": state.results["provenance"]["data_hash"],
        "served_model": state.results["models"]["served"],
        "model_labels": core.MODEL_LABELS,
        "regions": list(state.results["gate"]["domain"]["regions"]),
        "limitations": state.results["limitations"],
        "nominal_coverage": state.results["uncertainty"]["nominal_coverage"],
        "alpha": state.results["uncertainty"]["alpha"],
        "max_cells": MAX_CELLS,
        "refusal_codes": list(core.SUPPORTED_REFUSALS),
        "windows": state.results["dataset"].get("window_starts", []),
        "window_days": state.results["dataset"].get("window_days", 5),
        "domain": state.results["gate"]["domain"],
        "gate": {
            "min_calibration_pairs": state.results["gate"]["min_calibration_pairs"],
            "coverage_floor": state.results["gate"]["coverage_floor"],
        },
        "examples": list(state.results.get("actual_examples", [])),
        "grid": state.config.get("grid", {}),
    }


@app.post("/harmonize")
def harmonize(payload: HarmonizeRequest) -> JSONResponse:
    _validate_common(payload)
    n = len(payload.region)
    latitude, longitude, cell_lat, cell_lon = _resolve_coordinates(payload)
    lst = _resolve_lst(payload, longitude)

    output = core.harmonize(
        frp_aqua_mw=payload.frp_aqua_mw,
        lst_aqua_h=lst,
        region=payload.region,
        scan_aqua=payload.scan_aqua,
        artifact=state.artifact,
        model_id=SERVED_MODEL,
        detections=payload.detections,
        area_ratio=payload.area_ratio,
        latitude=latitude,
        longitude=longitude,
    )

    cells: list[dict[str, Any]] = []
    for index in range(n):
        applicable = bool(output["applicable"][index])
        original = float(payload.frp_aqua_mw[index])
        harmonized_value = _json_safe(output["harmonized_frp_mw"][index])
        correction = (
            None
            if harmonized_value is None
            else ((float(harmonized_value) - original) / original) * 100.0
        )
        cells.append(
            {
                "region": str(payload.region[index]),
                "cell": core.cell_label([cell_lat[index]], [cell_lon[index]])[0],
                "cell_lat": int(cell_lat[index]),
                "cell_lon": int(cell_lon[index]),
                "cell_bounds": {
                    "lat": [int(cell_lat[index]), int(cell_lat[index]) + 1],
                    "lon": [int(cell_lon[index]), int(cell_lon[index]) + 1],
                },
                "input_latitude": _json_safe(latitude[index]),
                "input_longitude": _json_safe(longitude[index]),
                "lst_aqua_h": _json_safe(lst[index]),
                "lst_display": core.format_lst([lst[index]])[0],
                "delay_h": _json_safe(output["delay_h"][index]),
                "delay_bin": _json_safe(output["delay_bin"][index]),
                "original_frp_mw": original,
                "predicted_log_ratio": _json_safe(output["predicted_log_ratio"][index]),
                "harmonized_frp_mw": harmonized_value,
                "correction_percent": _json_safe(correction),
                "interval_lower_mw": _json_safe(output["interval_lower_mw"][index]),
                "interval_upper_mw": _json_safe(output["interval_upper_mw"][index]),
                "interval_width_mw": _json_safe(output["interval_width_mw"][index]),
                "quantile_log": _json_safe(output["quantile"][index]),
                "interval_level": float(state.results["uncertainty"]["nominal_coverage"]),
                "applicable": applicable,
                "reason": None if applicable else str(output["reason"][index]),
                "refusal_message": None
                if applicable
                else _refusal_message(str(output["reason"][index])),
                "calibration_n": int(output["calibration_n"][index]),
                "coverage": _json_safe(output["coverage"][index]),
                "delay_in_domain": bool(output["delay_in_domain"][index]),
                "scan_in_domain": bool(output["scan_in_domain"][index]),
                "region_in_domain": bool(output["region_in_domain"][index]),
            }
        )

    regional = {}
    for region in sorted(set(payload.region)):
        entry = state.results.get("models", {}).get("loyo", {}).get(region, {})
        h = entry.get("H", {}).get("rmse") if entry else None
        raw = entry.get("B0", {}).get("rmse") if entry else None
        regional[region] = {
            "available": h is not None and raw is not None,
            "h_rmse": h,
            "raw_rmse": raw,
            "caution": (h is not None and raw is not None and h > raw),
            "note": (
                "Leave-one-region-out validation score; not an individual prediction interval."
                if h is not None
                else "No regional validation result for this region."
            ),
        }

    response = {
        "cells": cells,
        "count": len(cells),
        "model": SERVED_MODEL,
        "prediction_level": state.results["uncertainty"]["nominal_coverage"],
        "regional_context": regional,
        "refusals": sorted(
            {cell["reason"] for cell in cells if cell["reason"] is not None}
        ),
        "limitations": state.results["limitations"],
        "provenance": {
            "data_hash": state.results["provenance"]["data_hash"],
            "config_hash": state.config_hash,
            "model_artifact_sha256": state.model_sha256,
            "results_sha256": state.results_sha256,
            "pipeline_version": state.results["provenance"]["pipeline_version"],
        },
        "gate_version": {
            "alpha": state.results["gate"]["alpha"],
            "min_calibration_pairs": state.results["gate"]["min_calibration_pairs"],
            "coverage_floor": state.results["gate"]["coverage_floor"],
        },
    }
    return JSONResponse(response)


def _refusal_message(code: str) -> str:
    messages = {
        "insufficient_calibration_pairs": (
            "This delay bin has fewer than 40 calibration pairs. The system does not "
            "extrapolate a correction from thin support."
        ),
        "coverage_below_floor": (
            "Out-of-fold conformal coverage in this delay bin is below 0.70. "
            "The interval is not reliable enough to serve."
        ),
        "delay_outside_calibrated_range": (
            "The overpass delay lies outside the measured calibration domain. "
            "No correction number is returned."
        ),
        "scan_out_of_range": (
            "The Aqua scan value lies outside the measured calibration domain."
        ),
        "region_not_in_training": (
            "This region is not represented in the training pairs."
        ),
    }
    return messages.get(code, "The cell is outside the applicability domain.")


# ---------------------------------------------------------------------------
# Public live analysis: CSV/Parquet upload -> the same L5 core as /harmonize
# ---------------------------------------------------------------------------

LIVE_MAX_BYTES = 5_000_000
LIVE_MAX_ROWS = 2_000

LIVE_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "region": ("region", "study_region"),
    "frp_aqua_mw": ("frp_aqua_mw", "frp_aqua", "frp_mw", "frp"),
    "detections": ("detections", "n_aqua", "detection_count", "count", "n"),
    "scan_aqua": ("scan_aqua", "scan_km", "scan"),
    "lst_aqua_h": ("lst_aqua_h", "lst_aqua", "local_solar_time_h", "lst"),
    "delay_h": ("delay_h", "delay_hours", "delay"),
    "acquisition_time_utc": ("acquisition_time_utc", "acquisition_utc", "time_utc", "utc_time"),
    "latitude": ("latitude", "lat"),
    "longitude": ("longitude", "lon", "lng"),
    "date": ("date", "acquisition_date", "obs_date"),
    "area_ratio": ("area_ratio_aqua", "area_ratio", "area"),
}


def _normalise_columns(frame: pd.DataFrame) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for column in frame.columns:
        key = str(column).strip().lower().replace(" ", "_").replace("-", "_")
        lookup.setdefault(key, column)
    return lookup


def _number_column(frame: pd.DataFrame, column: str, label: str) -> np.ndarray:
    values = pd.to_numeric(frame[column], errors="coerce")
    bad = np.flatnonzero(values.isna().to_numpy())
    if bad.size:
        sample = ", ".join(str(int(index) + 1) for index in bad[:5])
        raise _reject(
            "invalid_numeric",
            f"Column {label!r} has missing or non-numeric values on row(s) {sample}.",
        )
    return values.to_numpy(dtype="float64")


def _parse_live_table(raw: bytes, filename: str) -> pd.DataFrame:
    suffix = Path(filename).suffix.lower()
    if not suffix:
        suffix = ".parquet" if raw[:4] == b"PAR1" else ".csv"
    try:
        if suffix in {".parquet", ".pq"}:
            frame = pd.read_parquet(io.BytesIO(raw))
        elif suffix == ".csv":
            frame = pd.read_csv(io.BytesIO(raw))
        elif suffix == ".txt":
            frame = pd.read_csv(io.BytesIO(raw), sep=None, engine="python")
        else:
            raise _reject(
                "unsupported_file_type",
                "Upload a .csv or .parquet file; other formats are not parsed.",
            )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - surfaced as a readable 422
        raise _reject(
            "unreadable_file",
            f"The file could not be read as {suffix.lstrip('.')}: {exc}",
        ) from exc
    return frame.reset_index(drop=True)


def _live_payload_from_frame(frame: pd.DataFrame) -> HarmonizeRequest:
    if frame.empty:
        raise _reject("empty_file", "The uploaded file has no data rows.")

    lookup = _normalise_columns(frame)
    chosen: dict[str, str] = {}
    for target, aliases in LIVE_COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lookup:
                chosen[target] = lookup[alias]
                break

    missing = [name for name in ("region", "frp_aqua_mw", "detections", "scan_aqua") if name not in chosen]
    if missing:
        raise _reject(
            "missing_columns",
            "Missing required column(s): "
            + ", ".join(missing)
            + ". Required: region, frp_aqua_mw, detections, scan_aqua, and lst_aqua_h "
            "(or delay_h, or acquisition_time_utc with longitude).",
        )

    if "lst_aqua_h" not in chosen and "acquisition_time_utc" not in chosen and "delay_h" not in chosen:
        raise _reject(
            "missing_time_column",
            "Provide lst_aqua_h, delay_h, or acquisition_time_utc with longitude.",
        )

    regions = frame[chosen["region"]].astype(str).str.strip().to_numpy()
    supported = list(state.results["gate"]["domain"]["regions"])
    unknown = sorted(set(regions) - set(supported))
    if unknown:
        raise _reject(
            "unsupported_region",
            f"Unsupported region(s): {unknown}. Supported: {supported}.",
        )

    frp = _number_column(frame, chosen["frp_aqua_mw"], "frp_aqua_mw")
    scan = _number_column(frame, chosen["scan_aqua"], "scan_aqua")
    detections = np.rint(_number_column(frame, chosen["detections"], "detections")).astype("int64")

    if "lst_aqua_h" in chosen:
        lst: np.ndarray | None = _number_column(frame, chosen["lst_aqua_h"], "lst_aqua_h")
    elif "delay_h" in chosen:
        lst = _number_column(frame, chosen["delay_h"], "delay_h") + core.REFERENCE_LST_H
    else:
        lst = None

    kwargs: dict[str, Any] = {
        "aggregator_config_hash": state.config_hash,
        "region": regions.tolist(),
        "frp_aqua_mw": frp.tolist(),
        "detections": detections.tolist(),
        "scan_aqua": scan.tolist(),
    }
    if lst is not None:
        kwargs["lst_aqua_h"] = lst.tolist()

    if "acquisition_time_utc" in chosen:
        raw_times = frame[chosen["acquisition_time_utc"]].astype(str).str.strip()
        kwargs["acquisition_time_utc"] = [
            value.split("T")[-1].split(" ")[-1][:5] for value in raw_times.tolist()
        ]

    if "latitude" in chosen:
        kwargs["latitude"] = _number_column(frame, chosen["latitude"], "latitude").tolist()
    if "longitude" in chosen:
        kwargs["longitude"] = _number_column(frame, chosen["longitude"], "longitude").tolist()
    if "area_ratio" in chosen:
        kwargs["area_ratio"] = _number_column(frame, chosen["area_ratio"], "area_ratio").tolist()

    if "date" in chosen:
        parsed = pd.to_datetime(frame[chosen["date"]], errors="coerce")
        bad = np.flatnonzero(parsed.isna().to_numpy())
        if bad.size:
            sample = ", ".join(str(int(index) + 1) for index in bad[:5])
            raise _reject("invalid_date", f"Column 'date' is not an ISO date on row(s) {sample}.")
        kwargs["date"] = parsed.dt.strftime("%Y-%m-%d").tolist()

    try:
        return HarmonizeRequest(**kwargs)
    except ValidationError as exc:
        fields = [
            {
                "field": ".".join(str(part) for part in error.get("loc", ())),
                "message": str(error.get("msg", "invalid value")),
                "type": str(error.get("type", "value_error")),
            }
            for error in exc.errors()
        ]
        raise _reject(
            "validation_error",
            "The uploaded rows failed boundary validation.",
            fields=fields,
        ) from exc


@app.post("/live-analysis")
async def live_analysis(
    request: Request,
    filename: str = Query("upload.csv", max_length=200),
) -> JSONResponse:
    """Score an uploaded CSV/Parquet batch through the frozen L5 pipeline.

    The endpoint parses only the documented cell-day columns, maps friendly
    aliases (for example ``delay_h``) onto the same request schema as
    ``POST /harmonize`` and returns the identical per-cell payload.  It does
    not fit, tune or write anything.
    """
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > LIVE_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "file_too_large",
                "message": f"Upload at most {LIVE_MAX_BYTES // 1_000_000} MB per request.",
            },
        )

    raw = await request.body()
    if not raw:
        raise HTTPException(
            status_code=400,
            detail={"code": "empty_upload", "message": "The upload body is empty."},
        )
    if len(raw) > LIVE_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "file_too_large",
                "message": f"Upload at most {LIVE_MAX_BYTES // 1_000_000} MB per request.",
            },
        )

    frame = _parse_live_table(raw, Path(filename).name)
    if len(frame) > LIVE_MAX_ROWS:
        raise _reject(
            "too_many_rows",
            f"This public tester accepts up to {LIVE_MAX_ROWS:,} rows per upload; "
            f"received {len(frame):,}.",
        )

    return harmonize(_live_payload_from_frame(frame))


# ---------------------------------------------------------------------------
# Read-only data explorer support
# ---------------------------------------------------------------------------


def _load_observations() -> pd.DataFrame:
    if state.observations is not None:
        return state.observations
    if state.ingestion is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "ingestion_unavailable",
                "message": "Real cleaned-CSV ingestion has not completed; the explorer is unavailable.",
            },
        )
    state.observations = state.ingestion.observations
    return state.observations


def _load_pairs() -> pd.DataFrame:
    if state.pairs is not None:
        return state.pairs
    if state.ingestion is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "ingestion_unavailable",
                "message": "Real cleaned-CSV ingestion has not completed; audit detail is unavailable.",
            },
        )
    state.pairs = state.ingestion.pairs
    return state.pairs


@app.get("/observations")
def observations(
    region: str | None = None,
    satellite: str | None = None,
    year: int | None = Query(None, ge=2021, le=2025),
    status: str | None = None,
    daynight: str | None = None,
    search: str | None = None,
    sort_by: str = Query("date"),
    sort_dir: str = Query("desc", pattern=r"^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
) -> dict[str, Any]:
    frame = _load_observations()
    filtered = frame
    if region:
        filtered = filtered[filtered["sampling_region"].str.lower() == region.lower()]
    if satellite:
        aliases = {
            "modis": ["Aqua", "Terra"],
            "aqua": ["Aqua"],
            "terra": ["Terra"],
            "snpp": ["N"],
            "suomi-npp": ["N"],
            "noaa-20": ["N20"],
            "noaa20": ["N20"],
        }
        values = aliases.get(satellite.lower(), [satellite])
        filtered = filtered[filtered["satellite"].isin(values)]
    if year:
        filtered = filtered[filtered["year"] == year]
    if status:
        filtered = filtered[filtered["status"] == status.lower()]
    if daynight:
        filtered = filtered[filtered["daynight"].str.upper() == daynight.upper()]
    if search:
        needle = search.strip().lower()
        if needle:
            mask = filtered["observation_id"].astype("string").str.lower().str.contains(needle, na=False)
            mask |= filtered["cell_id"].astype("string").str.lower().str.contains(needle, na=False)
            filtered = filtered[mask]

    sort_columns = {
        "observation_id": "observation_id",
        "satellite": "satellite",
        "region": "sampling_region",
        "latitude": "latitude",
        "longitude": "longitude",
        "date": "acquisition_date",
        "utc": "acquisition_time_utc",
        "lst": "lst",
        "frp": "frp",
        "scan": "scan",
        "status": "status",
    }
    column = sort_columns.get(sort_by, "acquisition_date")
    filtered = filtered.sort_values(column, ascending=(sort_dir == "asc"), kind="stable")
    total = int(len(filtered))
    start = (page - 1) * page_size
    page_frame = filtered.iloc[start : start + page_size]
    rows = []
    for _, row in page_frame.iterrows():
        rows.append(
            {
                "observation_id": str(row["observation_id"]),
                "satellite": str(row["satellite"]),
                "region": str(row["sampling_region"]),
                "latitude": _json_safe(round(float(row["latitude"]), 5)),
                "longitude": _json_safe(round(float(row["longitude"]), 5)),
                "cell": str(row["cell_id"]),
                "date": row["acquisition_date"].date().isoformat(),
                "window_start": row["sample_window_start"].date().isoformat(),
                "utc": str(row["utc_display"]),
                "lst": _json_safe(round(float(row["lst"]), 4)),
                "lst_display": str(row["lst_display"]),
                "lst_derivation": "lst = (UTC hours + longitude / 15) mod 24",
                "frp_mw": _json_safe(round(float(row["frp"]), 4)),
                "scan_km": _json_safe(round(float(row["scan"]), 4)),
                "track_km": _json_safe(round(float(row["track"]), 4)),
                "status": str(row["status"]),
                "flags_uint8": int(row["flags"]),
                "time_was_padded": bool(row["l1_time_was_padded"]),
            }
        )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, math.ceil(total / page_size)),
        "has_more": start + page_size < total,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "rows": rows,
    }


@lru_cache(maxsize=1)
def _summary_payload() -> dict[str, Any]:
    frame = _load_observations()
    pairs = _load_pairs()

    satellite_year = []
    grouped = frame.groupby(["satellite", "year"], observed=True)["lst"]
    for (satellite, year), values in grouped:
        satellite_year.append(
            {
                "satellite": str(satellite),
                "year": int(year),
                "n": int(values.size),
                "lst_median_h": _json_safe(round(float(values.median()), 4)),
                "lst_p05_h": _json_safe(round(float(values.quantile(0.05)), 4)),
                "lst_p95_h": _json_safe(round(float(values.quantile(0.95)), 4)),
                "lst_median_display": core.format_lst([float(values.median())])[0],
            }
        )

    frp_by_satellite = []
    for satellite, values in frame.groupby("satellite", observed=True)["frp"]:
        frp_by_satellite.append(
            {
                "satellite": str(satellite),
                "n": int(values.size),
                "median_mw": _json_safe(round(float(values.median()), 4)),
                "p95_mw": _json_safe(round(float(values.quantile(0.95)), 4)),
                "max_mw": _json_safe(round(float(values.max()), 4)),
            }
        )

    status_counts = {
        str(key): int(value) for key, value in frame["status"].value_counts().items()
    }
    daynight_counts = {
        str(key): int(value) for key, value in frame["daynight"].value_counts().items()
    }

    pairs_by_year_region: dict[str, dict[str, int]] = {}
    for (year, region), count in pairs.groupby(["year", "region"], observed=True).size().items():
        pairs_by_year_region.setdefault(str(int(year)), {})[str(region)] = int(count)

    sparse_notes = []
    for year in sorted(frame["year"].unique()):
        year_rows = int((frame["year"] == year).sum())
        for region in sorted(frame["sampling_region"].unique()):
            region_rows = int(
                ((frame["year"] == year) & (frame["sampling_region"] == region)).sum()
            )
            matched = int(pairs_by_year_region.get(str(int(year)), {}).get(str(region), 0))
            if region_rows > 0 and matched == 0:
                sparse_notes.append(
                    {
                        "year": int(year),
                        "region": str(region),
                        "raw_rows": region_rows,
                        "matched_pairs": 0,
                        "message": (
                            f"Calibration interrupt: {int(year)} has 0 matched pairs for "
                            f"{region} while {region_rows:,} raw observations exist. "
                            "Zero matched pairs is not zero raw observations."
                        ),
                    }
                )

    windows = state.results["dataset"]["window_starts"]
    window_days = int(state.results["dataset"]["window_days"])
    active_dates = sorted(
        {
            (pd.Timestamp(start) + pd.Timedelta(days=offset)).date().isoformat()
            for start in windows
            for offset in range(window_days)
        }
    )

    return {
        "satellite_year_lst": satellite_year,
        "frp_by_satellite": frp_by_satellite,
        "status_counts": status_counts,
        "daynight_counts": daynight_counts,
        "pairs_by_year_region": pairs_by_year_region,
        "sparse_notes": sparse_notes,
        "windows": windows,
        "window_days": window_days,
        "active_dates": active_dates,
        "status_definition": {
            "validated": "type == 0 AND FRP > 0 AND daynight == D",
            "flagged": "zero FRP or night; retained with a flag",
            "excluded": "type != 0 or negative FRP; retained with a flag",
        },
    }


@app.get("/observations/summary")
def observations_summary() -> dict[str, Any]:
    return _summary_payload()


@app.get("/audit/digital-twin")
def audit_digital_twin() -> dict[str, Any]:
    pairs = _load_pairs()
    return {"digital_twin": audit.digital_twin(pairs, state.artifact)}


@app.get("/audit/snapshot")
def audit_snapshot() -> dict[str, Any]:
    if state.audit_snapshot is None:
        pairs = _load_pairs()
        state.audit_snapshot = audit.audit_snapshot(state.results, pairs, state.artifact)
    return state.audit_snapshot


# ---------------------------------------------------------------------------
# Static dashboard (L7) - same-origin in local and container deployment
# ---------------------------------------------------------------------------

if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="dashboard")
else:

    @app.get("/")
    def dashboard_missing() -> dict[str, Any]:
        return {
            "name": "Arkagni",
            "message": "API is running. Build the dashboard with `npm run build` in frontend/.",
            "docs": "/docs",
            "health": "/health",
        }
