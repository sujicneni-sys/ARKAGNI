"""L6 serving: FastAPI wrapper around the pure harmonize core.

The service contains no science.  It loads one hash-verified model artifact,
validates the columnar request, calls ``predict_harmonized`` and returns
columnar arrays plus provenance and limitations.
"""

from __future__ import annotations

import hashlib
import json
import pickle
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pyroharmonize import config
from pyroharmonize.l2 import (
    NOMINAL_FOOTPRINT_KM,
    REGION_ORDER,
    cell_label,
    local_solar_time,
)
from pyroharmonize.models import predict_harmonized

RESULTS_PATH = config.ARTIFACTS_DIR / "results" / "results.json"
WEB_DIR = config.PROJECT_ROOT / "web"
MAX_CELLS = 100_000


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class State:
    results: dict[str, Any]
    artifact: dict[str, Any]
    artifact_sha256: str


state = State()


def _load_state() -> None:
    if not RESULTS_PATH.is_file():
        raise RuntimeError(
            f"results file missing: {RESULTS_PATH}. Run scripts/03_run_analysis.py"
        )
    results = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    artifact_path = Path(results["provenance"]["model_artifact"])
    if not artifact_path.is_absolute():
        artifact_path = config.PROJECT_ROOT / artifact_path
    if not artifact_path.is_file():
        raise RuntimeError(f"model artifact missing: {artifact_path}")
    actual_hash = _sha256(artifact_path)
    expected_hash = results["provenance"]["model_artifact_sha256"]
    if actual_hash != expected_hash:
        raise RuntimeError(
            "model artifact hash mismatch; refusing to serve an unverified model"
        )
    with artifact_path.open("rb") as handle:
        artifact = pickle.load(handle)
    state.results = results
    state.artifact = artifact
    state.artifact_sha256 = actual_hash


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_state()
    yield


app = FastAPI(
    title="Arkagni API",
    version="1.0.0",
    description=(
        "Aqua MODIS cell-day FRP harmonization to the SNPP VIIRS 13.6 h "
        "reference, with conformal intervals and an applicability gate."
    ),
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class HarmonizeRequest(BaseModel):
    """Columnar request.  One element in each list is one 1-degree cell-day."""

    model_config = ConfigDict(extra="forbid")

    aggregator_config_hash: str = Field(min_length=64, max_length=64)
    region: list[str]
    frp_aqua_mw: list[float]
    detections: list[int]
    lst_aqua_h: list[float]
    scan_aqua: list[float]
    date: list[str] | None = None
    cell_lat: list[int] | None = None
    cell_lon: list[int] | None = None
    latitude: list[float] | None = None
    longitude: list[float] | None = None
    area_ratio: list[float] | None = None

    @field_validator("region")
    @classmethod
    def supported_regions(cls, values: list[str]) -> list[str]:
        unknown = sorted(set(values) - set(REGION_ORDER))
        if unknown:
            raise ValueError(f"unsupported region(s): {unknown}; supported: {list(REGION_ORDER)}")
        return values

    @model_validator(mode="after")
    def same_lengths(self) -> "HarmonizeRequest":
        lengths = {
            "region": len(self.region),
            "frp_aqua_mw": len(self.frp_aqua_mw),
            "detections": len(self.detections),
            "lst_aqua_h": len(self.lst_aqua_h),
            "scan_aqua": len(self.scan_aqua),
        }
        for name in ("date", "cell_lat", "cell_lon", "latitude", "longitude", "area_ratio"):
            value = getattr(self, name)
            if value is not None:
                lengths[name] = len(value)
        if len(set(lengths.values())) != 1:
            raise ValueError(f"all arrays must have the same length: {lengths}")
        if not lengths["region"]:
            raise ValueError("at least one cell is required")
        if lengths["region"] > MAX_CELLS:
            raise ValueError(f"request exceeds the {MAX_CELLS:,}-cell cap")
        return self


def _validate_values(payload: HarmonizeRequest) -> None:
    if payload.aggregator_config_hash != state.results["provenance"]["config_hash"]:
        raise HTTPException(
            status_code=422,
            detail=(
                "aggregator_config_hash does not match the training aggregation. "
                "Build cell-days with the published configuration before calling "
                "/harmonize."
            ),
        )
    for i, value in enumerate(payload.frp_aqua_mw):
        if not np.isfinite(value) or value <= 0:
            raise HTTPException(422, f"frp_aqua_mw[{i}] must be finite and > 0")
    for i, value in enumerate(payload.detections):
        if value < 1:
            raise HTTPException(422, f"detections[{i}] must be >= 1")
    for i, value in enumerate(payload.lst_aqua_h):
        if not np.isfinite(value) or not (0 <= value <= 24):
            raise HTTPException(422, f"lst_aqua_h[{i}] must be in [0, 24]")
    for i, value in enumerate(payload.scan_aqua):
        if not np.isfinite(value) or value <= 0:
            raise HTTPException(422, f"scan_aqua[{i}] must be finite and > 0")
    if payload.area_ratio is not None:
        for i, value in enumerate(payload.area_ratio):
            if not np.isfinite(value) or value < 0.9 or value > 12:
                raise HTTPException(422, f"area_ratio[{i}] must be in [0.9, 12]")
    if payload.date is not None:
        windows = state.results["dataset"].get("window_starts", [])
        window_days = int(state.results["dataset"].get("window_days", 5))
        for i, value in enumerate(payload.date):
            try:
                requested = pd.Timestamp(value).normalize()
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(422, f"date[{i}] is not an ISO date") from exc
            covered = any(
                pd.Timestamp(start) <= requested < pd.Timestamp(start) + pd.Timedelta(days=window_days)
                for start in windows
            )
            if not covered:
                raise HTTPException(
                    422,
                    f"date[{i}]={value} is outside the verified 5-day sampling windows",
                )


def _columnar_examples() -> list[dict[str, Any]]:
    return list(state.results.get("actual_examples", []))


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "model_loaded": bool(state.artifact),
        "model": state.results["models"]["served"],
        "data_hash_begins": state.results["provenance"]["data_hash_begins"],
        "artifact_sha256_begins": state.artifact_sha256[:12],
    }


@app.get("/version")
def version() -> dict[str, Any]:
    provenance = state.results["provenance"]
    return {
        "name": "Arkagni",
        "model": state.results["models"]["served"],
        "model_version": state.results["schema_version"],
        "pipeline_version": provenance["pipeline_version"],
        "data_hash": provenance["data_hash"],
        "data_hash_begins": provenance["data_hash_begins"],
        "config_hash": provenance["config_hash"],
        "git_commit": provenance.get("git_commit", "unknown"),
        "model_artifact_sha256": provenance["model_artifact_sha256"],
        "library_versions": provenance["library_versions"],
        "limitations": state.results["limitations"],
    }


@app.get("/validity")
def validity() -> dict[str, Any]:
    return {
        "gate": state.results["gate"],
        "validity_map": state.results["validity_map"],
        "uncertainty": state.results["uncertainty"],
        "regions": list(REGION_ORDER),
        "limitations": state.results["limitations"],
        "provenance": state.results["provenance"],
    }


@app.get("/audit")
def audit() -> dict[str, Any]:
    """Alias of /validity; the payload is identical by design (C-02)."""
    return validity()


@app.get("/results")
def results() -> dict[str, Any]:
    return state.results


@app.get("/config")
def config_payload() -> dict[str, Any]:
    return {
        "aggregator_config_hash": state.results["provenance"]["config_hash"],
        "data_hash": state.results["provenance"]["data_hash"],
        "regions": list(REGION_ORDER),
        "limitations": state.results["limitations"],
        "nominal_coverage": state.results["uncertainty"]["nominal_coverage"],
        "max_cells": MAX_CELLS,
        "examples": _columnar_examples(),
    }


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


@app.post("/harmonize")
def harmonize(payload: HarmonizeRequest) -> JSONResponse:
    _validate_values(payload)
    n = len(payload.region)
    frame = pd.DataFrame(
        {
            "region": payload.region,
            "frp_sum_aqua": np.asarray(payload.frp_aqua_mw, dtype="float64"),
            "n_aqua": np.asarray(payload.detections, dtype="float64"),
            "lst_aqua": np.asarray(payload.lst_aqua_h, dtype="float64"),
            "scan_aqua": np.asarray(payload.scan_aqua, dtype="float64"),
            "delay_ref": np.asarray(payload.lst_aqua_h, dtype="float64") - 13.6,
            "latitude": np.asarray(payload.latitude, dtype="float64")
            if payload.latitude is not None
            else np.zeros(n),
            "longitude": np.asarray(payload.longitude, dtype="float64")
            if payload.longitude is not None
            else np.zeros(n),
            "area_ratio_aqua": np.asarray(payload.area_ratio, dtype="float64")
            if payload.area_ratio is not None
            else np.asarray(payload.scan_aqua, dtype="float64"),
        }
    )
    output = predict_harmonized(frame, state.artifact, model_id="H")
    cells = []
    for i, row in output.iterrows():
        cells.append(
            {
                "region": row["region"],
                "delay_h": _json_safe(row["delay_h"]),
                "delay_bin": _json_safe(row["delay_bin"]),
                "predicted_log_ratio": _json_safe(row["predicted_log_ratio"]),
                "harmonized_frp_mw": _json_safe(row["harmonized_frp_mw"]),
                "interval_lower_mw": _json_safe(row["interval_lower_mw"]),
                "interval_upper_mw": _json_safe(row["interval_upper_mw"]),
                "interval_width_mw": _json_safe(row["interval_width_mw"]),
                "applicable": bool(row["applicable"]),
                "reason": None if bool(row["applicable"]) else str(row["reason"]),
                "scan_in_domain": bool(row["scan_in_domain"]),
                "delay_in_domain": bool(row["delay_in_domain"]),
            }
        )
    response = {
        "cells": cells,
        "count": len(cells),
        "prediction_level": state.results["uncertainty"]["nominal_coverage"],
        "model": state.results["models"]["served"],
        "limitations": state.results["limitations"],
        "provenance": {
            "data_hash": state.results["provenance"]["data_hash"],
            "config_hash": state.results["provenance"]["config_hash"],
            "model_artifact_sha256": state.results["provenance"]["model_artifact_sha256"],
            "pipeline_version": state.results["provenance"]["pipeline_version"],
        },
        "gate_version": state.results["gate"]["alpha"],
    }
    return JSONResponse(response)


@lru_cache(maxsize=1)
def _observations() -> pd.DataFrame:
    """Actual L1 pixel records, loaded once.  Used only by the Data Explorer."""
    path = config.PROCESSED_DIR / "l1_canonical.parquet"
    columns = [
        "observation_id",
        "satellite",
        "sampling_region",
        "acquisition_date",
        "acquisition_time_utc",
        "latitude",
        "longitude",
        "frp",
        "type",
        "daynight",
        "scan",
        "track",
    ]
    frame = pd.read_parquet(path, columns=columns)
    frame["lst"] = local_solar_time(frame["acquisition_time_utc"], frame["longitude"])
    frame["year"] = frame["acquisition_date"].dt.year
    frame["cell_id"] = cell_label(
        np.floor(frame["latitude"]).astype(int), np.floor(frame["longitude"]).astype(int)
    )
    type_ok = frame["type"].astype(str).str.strip() == "0"
    frp_ok = frame["frp"] > 0
    day_ok = frame["daynight"].astype(str).str.strip().str.upper() == "D"
    frame["status"] = np.select(
        [~type_ok | (frame["frp"] < 0), (~frp_ok) | (~day_ok)],
        ["excluded", "flagged"],
        default="validated",
    )
    frame["utc_display"] = (
        frame["acquisition_time_utc"].str.slice(0, 2)
        + ":"
        + frame["acquisition_time_utc"].str.slice(2, 4)
    )
    return frame


@app.get("/observations")
def observations(
    region: str | None = None,
    satellite: str | None = None,
    year: int | None = None,
    status: str | None = None,
    daynight: str | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
) -> dict[str, Any]:
    frame = _observations()
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
        sat_values = aliases.get(satellite.lower(), [satellite])
        filtered = filtered[filtered["satellite"].isin(sat_values)]
    if year:
        filtered = filtered[filtered["year"] == year]
    if status:
        filtered = filtered[filtered["status"] == status.lower()]
    if daynight:
        filtered = filtered[filtered["daynight"].str.upper() == daynight.upper()]
    if search:
        needle = search.strip().lower()
        mask = filtered["observation_id"].str.lower().str.contains(needle, na=False)
        mask |= filtered["cell_id"].str.lower().str.contains(needle, na=False)
        filtered = filtered[mask]
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
                "utc": str(row["utc_display"]),
                "lst": _json_safe(round(float(row["lst"]), 4)),
                "frp_mw": _json_safe(round(float(row["frp"]), 4)),
                "scan_km": _json_safe(round(float(row["scan"]), 4)),
                "track_km": _json_safe(round(float(row["track"]), 4)),
                "status": str(row["status"]),
            }
        )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "rows": rows,
    }


if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
