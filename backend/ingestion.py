"""L1/L2 ingestion from the three real cleaned FIRMS CSVs.

This is the only serving-side module that reads the cleaned source files.  It
hashes them, validates the documented schema, types the values, builds the
canonical pixel table, aggregates validated pixels to 1-degree cell-days, and
pairs Aqua with Suomi-NPP.  Missing files, schema drift, a hash mismatch, or a
row/pair mismatch against the frozen measured release all raise.  There is no
synthetic data and no silent fallback.

The L5 core remains pure.  This module is the L1/L2 I/O boundary and may read
files, the clock, and configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend import config, core
from data.adapters import apply_pixel_contract, build_cell_days, pair_cell_days

# Documented hash order.  It is part of the data-hash definition and must not
# be reordered.
HASH_ORDER: tuple[str, ...] = ("MODIS", "VIIRS_SNPP", "VIIRS_NOAA20")

# Values in the cleaned tables are carried as strings until explicitly typed.
STRING_COLUMNS: tuple[str, ...] = (
    "satellite",
    "instrument",
    "confidence",
    "version",
    "daynight",
    "type",
    "source_product",
    "sampling_region",
    "confidence_raw",
    "brightness_primary_source",
    "confidence_encoding",
)

NUMERIC_COLUMNS: tuple[str, ...] = (
    "latitude",
    "longitude",
    "scan",
    "track",
    "frp",
    "brightness",
    "bright_t31",
    "bright_ti4",
    "bright_ti5",
    "brightness_temperature_primary_k",
    "brightness_temperature_secondary_k",
)

REQUIRED_COLUMNS: tuple[str, ...] = (
    "latitude",
    "longitude",
    "scan",
    "track",
    "frp",
    "type",
    "daynight",
    "satellite",
    "sampling_region",
    "sample_window_start",
    "sample_window_days",
    "acquisition_date",
    "acquisition_time_utc",
    "acq_time",
    "observation_id",
    "source_product",
)

READ_COLUMNS: tuple[str, ...] = tuple(
    dict.fromkeys(
        REQUIRED_COLUMNS
        + STRING_COLUMNS
        + NUMERIC_COLUMNS
        + (
            "quality_flag_invalid_frp",
            "quality_flag_invalid_scan_track",
        )
    )
)

OBSERVATION_COLUMNS: tuple[str, ...] = (
    "observation_id",
    "satellite",
    "sampling_region",
    "sample_window_start",
    "sample_window_days",
    "acquisition_date",
    "acquisition_time_utc",
    "latitude",
    "longitude",
    "frp",
    "type",
    "daynight",
    "scan",
    "track",
    "lst",
    "year",
    "cell_lat",
    "cell_lon",
    "cell_id",
    "flags",
    "validated",
    "l1_time_was_padded",
    "l1_quality_status",
)


class IngestionError(RuntimeError):
    """Raised when the real source files cannot reproduce the served release."""


@dataclass(frozen=True)
class SourceSpec:
    key: str
    filename: str
    satellites: tuple[str, ...]


SOURCE_SPECS: tuple[SourceSpec, ...] = (
    SourceSpec("MODIS", "MODIS_SP_cleaned.csv", ("Aqua", "Terra")),
    SourceSpec("VIIRS_SNPP", "VIIRS_SNPP_SP_cleaned.csv", ("N",)),
    SourceSpec("VIIRS_NOAA20", "VIIRS_NOAA20_SP_cleaned.csv", ("N20",)),
)

# The user-facing data/ location is preferred, then the frozen raw tree, then
# the repository root copies.  All candidates are real files; whichever is
# found first is hashed and reported.
CANDIDATE_DIRS: tuple[Path, ...] = (
    config.DATA_DIR,
    config.DATA_DIR / "cleaned",
    config.DATA_DIR / "raw" / "NASA_Fire_Data_Engine" / "data" / "cleaned",
    config.DATA_DIR / "raw" / "unzipped" / "NASA_Fire_Data_Engine" / "data" / "cleaned",
    config.PROJECT_ROOT,
)


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(config.PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def _counts(series: pd.Series) -> dict[str, int]:
    return {str(key): int(value) for key, value in series.value_counts().items()}


def _round(value: Any, digits: int = 6) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(numeric):
        return None
    return round(numeric, digits)


@dataclass
class SourceInfo:
    spec: SourceSpec
    path: Path
    columns: tuple[str, ...]
    sha256: str
    bytes: int
    rows: int = 0


@dataclass
class IngestionSnapshot:
    sources: list[SourceInfo]
    observations: pd.DataFrame
    pairs: pd.DataFrame
    cell_days: dict[str, pd.DataFrame]
    paired: dict[str, pd.DataFrame]
    report: dict[str, Any]
    data_hash: str


# ---------------------------------------------------------------------------
# Source discovery and reading
# ---------------------------------------------------------------------------


def discover_sources() -> list[SourceInfo]:
    """Locate the three cleaned CSVs and verify their documented schema."""
    sources: list[SourceInfo] = []
    missing: list[str] = []
    for spec in SOURCE_SPECS:
        chosen: Path | None = None
        for directory in CANDIDATE_DIRS:
            candidate = directory / spec.filename
            if candidate.is_file():
                chosen = candidate
                break
        if chosen is None:
            missing.append(spec.filename)
            continue

        columns = tuple(str(column) for column in pd.read_csv(chosen, nrows=0).columns)
        absent = [column for column in REQUIRED_COLUMNS if column not in columns]
        if absent:
            raise IngestionError(
                f"{spec.filename}: missing required cleaned columns {absent}; "
                "refusing to invent or impute them"
            )
        sources.append(
            SourceInfo(
                spec=spec,
                path=chosen,
                columns=columns,
                sha256=_sha256(chosen),
                bytes=int(chosen.stat().st_size),
            )
        )

    if missing:
        searched = ", ".join(str(directory) for directory in CANDIDATE_DIRS)
        raise IngestionError(
            "cleaned source file(s) missing: "
            f"{missing}. Searched: {searched}. Place the three real cleaned CSVs "
            "in data/ (or the frozen raw tree) before starting the service."
        )
    return sources


def documented_data_hash(sources: list[SourceInfo]) -> str:
    """SHA-256 of the per-file SHA-256 digests concatenated in documented order."""
    import hashlib

    by_key = {source.spec.key: source for source in sources}
    try:
        ordered = [by_key[key] for key in HASH_ORDER]
    except KeyError as exc:  # pragma: no cover - discover_sources prevents this
        raise IngestionError(f"missing source for documented hash order: {exc}") from exc
    return hashlib.sha256("".join(source.sha256 for source in ordered).encode("ascii")).hexdigest()


def _read_source(source: SourceInfo) -> pd.DataFrame:
    usecols = [column for column in READ_COLUMNS if column in source.columns]
    frame = pd.read_csv(
        source.path,
        usecols=usecols,
        dtype={"acq_time": "string", "acquisition_time_utc": "string"},
        low_memory=False,
    )
    source.rows = int(len(frame))
    if frame.empty:
        raise IngestionError(f"{source.spec.filename}: source file is empty")
    return frame


def _parse_hhmm(series: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Vectorised HHMM normalization; never repairs an invalid value."""
    text = series.astype("string").str.strip()
    missing = text.isna() | (text == "") | text.str.lower().isin(["nan", "none", "nat"])
    digits = text.str.fullmatch(r"\d{1,4}").fillna(False)
    usable = digits & ~missing

    padded = text.where(usable).str.zfill(4)
    hour = pd.to_numeric(padded.str.slice(0, 2), errors="coerce").astype("Int64")
    minute = pd.to_numeric(padded.str.slice(2, 4), errors="coerce").astype("Int64")
    valid = usable & hour.between(0, 23) & minute.between(0, 59)

    normalized = padded.where(valid)
    was_padded = (valid & (text.str.len() < 4)).fillna(False).astype(bool)

    status = pd.Series("invalid", index=series.index, dtype="string")
    status[missing] = "missing"
    status[valid] = "valid"
    return normalized, was_padded, status


def _assign_quality_status(frame: pd.DataFrame) -> pd.Series:
    status = np.select(
        [
            frame["l1_validity_invalid_coords"],
            frame["l1_time_status"] != "valid",
            frame["l1_frp_status"].isin(["invalid_missing", "invalid_negative"]),
            frame["l1_validity_duplicate_id"],
            frame["l1_frp_status"] == "flagged_zero",
        ],
        [
            "invalid_coordinates",
            "invalid_time",
            "invalid_frp",
            "invalid_duplicate_id",
            "valid_flagged_zero_frp",
        ],
        default="valid",
    )
    return pd.Series(status, index=frame.index, dtype="string")


def _type_and_derive(frame: pd.DataFrame, source: SourceInfo, row_offset: int) -> pd.DataFrame:
    out = frame.copy()

    out["acquisition_time_utc"] = (
        out["acquisition_time_utc"].astype("string").str.replace(r"\.0$", "", regex=True)
    )
    out["acq_time"] = out["acq_time"].astype("string")
    normalized, was_padded, time_status = _parse_hhmm(out["acquisition_time_utc"])

    for column in STRING_COLUMNS:
        if column in out.columns:
            out[column] = out[column].astype("string")
    for column in NUMERIC_COLUMNS:
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")

    out["acquisition_date"] = pd.to_datetime(
        out["acquisition_date"], format="%Y-%m-%d", errors="coerce"
    )
    out["sample_window_start"] = pd.to_datetime(
        out["sample_window_start"], format="%Y-%m-%d", errors="coerce"
    )
    out["sample_window_days"] = pd.to_numeric(
        out["sample_window_days"], errors="coerce"
    ).astype("Int64")
    out["observation_id"] = out["observation_id"].astype("string")

    unknown = sorted(set(out["satellite"].dropna().unique()) - set(source.spec.satellites))
    if unknown:
        raise IngestionError(
            f"{source.spec.filename}: unexpected satellite code(s) {unknown}; "
            f"expected {list(source.spec.satellites)}"
        )

    out["l1_time_utc_hhmm"] = normalized
    out["l1_time_was_padded"] = was_padded
    out["l1_time_status"] = time_status

    frp = out["frp"]
    frp_status = pd.Series("valid", index=out.index, dtype="string")
    frp_status[frp.isna()] = "invalid_missing"
    frp_status[frp < 0] = "invalid_negative"
    frp_status[frp == 0] = "flagged_zero"
    out["l1_frp_status"] = frp_status
    out["l1_validity_zero_frp"] = frp.eq(0).fillna(False).astype(bool)
    out["l1_validity_negative_frp"] = frp.lt(0).fillna(False).astype(bool)
    out["l1_validity_missing_frp"] = frp.isna()

    out["l1_validity_invalid_coords"] = ~(
        out["latitude"].between(-90, 90) & out["longitude"].between(-180, 180)
    )
    out["l1_validity_invalid_scan_track"] = (
        out["scan"].isna()
        | out["track"].isna()
        | (out["scan"] <= 0)
        | (out["track"] <= 0)
    )
    out["l1_validity_duplicate_id"] = False

    out["l1_row_id"] = pd.Series(
        range(row_offset, row_offset + len(out)), index=out.index, dtype="int64"
    )
    out["l1_source_file"] = source.spec.filename
    out["l1_sensor_key"] = source.spec.key
    out["l1_platform"] = out["satellite"].map(
        {"Aqua": "Aqua", "Terra": "Terra", "N": "SNPP", "N20": "NOAA-20"}
    ).astype("string")
    out["l1_quality_status"] = _assign_quality_status(out)
    return out


# ---------------------------------------------------------------------------
# Derived serving tables
# ---------------------------------------------------------------------------


def _observation_frame(pixels: pd.DataFrame) -> pd.DataFrame:
    frame = pixels.loc[:, list(OBSERVATION_COLUMNS)].copy()
    time_text = frame["acquisition_time_utc"].astype("string").str.zfill(4)
    frame["utc_display"] = time_text.str.slice(0, 2) + ":" + time_text.str.slice(2, 4)
    frame["lst_display"] = core.format_lst(frame["lst"].to_numpy())

    type_bad = (frame["flags"].to_numpy() & core.FLAG_TYPE_NOT_0) != 0
    frp_bad = (frame["flags"].to_numpy() & core.FLAG_FRP_NOT_POSITIVE) != 0
    night = (frame["flags"].to_numpy() & core.FLAG_NIGHT) != 0
    negative = frame["frp"].to_numpy() < 0
    frame["status"] = np.select(
        [
            type_bad | negative,
            frp_bad & ~(type_bad | negative),
            night & ~(type_bad | negative),
        ],
        ["excluded", "flagged", "flagged"],
        default="validated",
    )
    return frame


def _region_bounds(pixels: pd.DataFrame) -> dict[str, dict[str, Any]]:
    bounds: dict[str, dict[str, Any]] = {}
    for region, group in pixels.groupby("sampling_region", observed=True):
        bounds[str(region)] = {
            "lat_min": _round(group["latitude"].min()),
            "lat_max": _round(group["latitude"].max()),
            "lon_min": _round(group["longitude"].min()),
            "lon_max": _round(group["longitude"].max()),
            "rows": int(len(group)),
        }
    return bounds


def _dataset_report(pixels: pd.DataFrame) -> dict[str, Any]:
    windows = sorted(
        pixels["sample_window_start"].dropna().dt.strftime("%Y-%m-%d").unique().tolist()
    )
    window_days_series = pixels["sample_window_days"].dropna()
    window_days = int(window_days_series.mode().iloc[0]) if not window_days_series.empty else 5
    return {
        "rows": int(len(pixels)),
        "validated_rows": int(pixels["validated"].sum()),
        "flags": core.flag_counts(pixels["flags"]),
        "rows_by_satellite": _counts(pixels["satellite"]),
        "validated_by_satellite": _counts(pixels.loc[pixels["validated"], "satellite"]),
        "rows_by_region": _counts(pixels["sampling_region"]),
        "rows_by_year": {
            str(int(year)): int(count)
            for year, count in pixels["year"].value_counts().sort_index().items()
        },
        "regions": int(pixels["sampling_region"].nunique()),
        "region_bounds": _region_bounds(pixels),
        "window_starts": windows,
        "windows": int(len(windows)),
        "window_days": window_days,
        "date_min": pixels["acquisition_date"].min().date().isoformat(),
        "date_max": pixels["acquisition_date"].max().date().isoformat(),
    }


def _region_pair_summary(pairs: pd.DataFrame) -> dict[str, dict[str, Any]]:
    total = len(pairs)
    summary: dict[str, dict[str, Any]] = {}
    for region, group in pairs.groupby("region", observed=True):
        y = group["y"].to_numpy(dtype="float64")
        summary[str(region)] = {
            "n": int(len(group)),
            "delay_mean_h": _round(group["delay_ref"].mean()),
            "delay_median_h": _round(group["delay_ref"].median()),
            "raw_bias": _round(np.mean(y)),
            "raw_rmse": _round(np.sqrt(np.mean(np.square(y)))),
            "share": _round(len(group) / total if total else 0.0),
        }
    return summary


def _pairs_report(
    cell_days: dict[str, pd.DataFrame],
    paired: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    pairs = paired["aqua_snpp"]
    total = len(pairs)
    region_summary = _region_pair_summary(pairs)
    return {
        "count": int(total),
        "aqua_cell_days": int(len(cell_days["Aqua"])),
        "snpp_cell_days": int(len(cell_days["N"])),
        "terra_pairs": int(len(paired["terra_snpp"])),
        "noaa20_snpp_pairs": int(len(paired["noaa20_snpp"])),
        "by_region": _counts(pairs["region"]),
        "share_by_region": {region: row["share"] for region, row in region_summary.items()},
        "region_summary": region_summary,
        "delay_ref_min_h": _round(pairs["delay_ref"].min()),
        "delay_ref_max_h": _round(pairs["delay_ref"].max()),
        "delay_ref_mean_h": _round(pairs["delay_ref"].mean()),
        "delay_ref_median_h": _round(pairs["delay_ref"].median()),
        "y_mean": _round(pairs["y"].mean()),
        "y_std": _round(pairs["y"].std()),
    }


# ---------------------------------------------------------------------------
# Verification against the frozen measured release
# ---------------------------------------------------------------------------


def _record(
    checks: dict[str, dict[str, Any]],
    name: str,
    actual: Any,
    expected: Any,
) -> None:
    checks[name] = {
        "actual": actual,
        "expected": expected,
        "passed": bool(actual == expected),
    }


def _record_number(
    checks: dict[str, dict[str, Any]],
    name: str,
    actual: Any,
    expected: Any,
    tolerance: float = 1e-5,
) -> None:
    if actual is None or expected is None:
        passed = actual is None and expected is None
    else:
        passed = bool(np.isclose(float(actual), float(expected), rtol=0.0, atol=tolerance))
    checks[name] = {"actual": actual, "expected": expected, "passed": passed}


def _verify(
    data_hash: str,
    expected_hash: str,
    dataset: dict[str, Any],
    pairs: dict[str, Any],
    frozen: dict[str, Any],
) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    _record(checks, "data_hash", data_hash, expected_hash)

    expected_dataset = frozen["dataset"]
    for key in (
        "rows",
        "validated_rows",
        "flags",
        "rows_by_satellite",
        "validated_by_satellite",
        "rows_by_region",
        "rows_by_year",
        "regions",
        "window_starts",
        "windows",
        "window_days",
        "date_min",
        "date_max",
    ):
        _record(checks, f"dataset.{key}", dataset[key], expected_dataset[key])

    expected_bounds = expected_dataset.get("region_bounds", {})
    for region, bounds in dataset["region_bounds"].items():
        expected_rows = expected_bounds.get(region, {}).get("rows")
        _record(checks, f"dataset.region_bounds.{region}.rows", bounds["rows"], expected_rows)

    expected_pairs = frozen["pairs"]
    for key in (
        "count",
        "aqua_cell_days",
        "snpp_cell_days",
        "terra_pairs",
        "noaa20_snpp_pairs",
        "by_region",
    ):
        _record(checks, f"pairs.{key}", pairs[key], expected_pairs[key])

    for key in (
        "delay_ref_min_h",
        "delay_ref_max_h",
        "delay_ref_mean_h",
        "delay_ref_median_h",
        "y_mean",
        "y_std",
    ):
        _record_number(checks, f"pairs.{key}", pairs[key], expected_pairs[key])

    for region, row in pairs["region_summary"].items():
        expected = expected_pairs.get("region_summary", {}).get(region, {})
        for key in ("n", "delay_mean_h", "delay_median_h", "raw_bias", "raw_rmse", "share"):
            if key == "n":
                _record(checks, f"pairs.region_summary.{region}.{key}", row[key], expected.get(key))
            else:
                _record_number(
                    checks,
                    f"pairs.region_summary.{region}.{key}",
                    row[key],
                    expected.get(key),
                )

    failed = [name for name, check in checks.items() if not check["passed"]]
    return {
        "passed": not failed,
        "checks": checks,
        "failed": failed,
        "expected_source": "backend/artifacts/results.json",
    }


# ---------------------------------------------------------------------------
# Public lifecycle
# ---------------------------------------------------------------------------


def load_snapshot(frozen_results: dict[str, Any]) -> IngestionSnapshot:
    """Read the real files and build every serving table, verifying the result."""
    sources = discover_sources()
    computed_hash = documented_data_hash(sources)
    expected_hash = str(frozen_results["provenance"]["data_hash"])
    if computed_hash != expected_hash:
        raise IngestionError(
            "cleaned source data hash does not match the served release: "
            f"{computed_hash} != {expected_hash}. Refusing to serve."
        )

    frames: list[pd.DataFrame] = []
    offset = 0
    for source in sources:
        raw = _read_source(source)
        typed = _type_and_derive(raw, source, offset)
        frames.append(typed)
        offset += len(typed)

    canonical = pd.concat(frames, ignore_index=True)
    canonical["l1_validity_duplicate_id"] = canonical["observation_id"].duplicated(
        keep=False
    )
    canonical["l1_quality_status"] = _assign_quality_status(canonical)

    pixels = apply_pixel_contract(canonical)
    pixels["cell_id"] = core.cell_label(pixels["cell_lat"], pixels["cell_lon"])
    observations = _observation_frame(pixels)

    cell_days = {
        key: build_cell_days(pixels, key) for key in ("Aqua", "Terra", "N", "N20")
    }
    paired = {
        "aqua_snpp": pair_cell_days(cell_days["Aqua"], cell_days["N"], "SNPP"),
        "terra_snpp": pair_cell_days(cell_days["Terra"], cell_days["N"], "SNPP"),
        "noaa20_snpp": pair_cell_days(cell_days["N20"], cell_days["N"], "SNPP"),
    }

    dataset = _dataset_report(pixels)
    pairs = _pairs_report(cell_days, paired)
    verification = _verify(computed_hash, expected_hash, dataset, pairs, frozen_results)

    report = {
        "schema_version": "pyroharmonize.ingestion.v1",
        "status": "ok" if verification["passed"] else "mismatch",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_policy": (
            "Read directly from the three cleaned CSVs at service start; no synthetic "
            "or cached fallback is used."
        ),
        "data_hash": computed_hash,
        "data_hash_expected": expected_hash,
        "hash_verified": computed_hash == expected_hash,
        "sources": [
            {
                "sensor_key": source.spec.key,
                "filename": source.spec.filename,
                "path": _display_path(source.path),
                "sha256": source.sha256,
                "bytes": source.bytes,
                "rows": source.rows,
                "columns": list(source.columns),
                "satellites": list(source.spec.satellites),
            }
            for source in sources
        ],
        "dataset": dataset,
        "pairs": pairs,
        "verification": verification,
        "live_harmonization_endpoint": "/ingestion/harmonization",
        "limitations": [
            "Ingestion verifies the cleaned CSVs against the frozen measured release; "
            "it does not re-fit the served model.",
            "Source files are the supplied FIRMS cleaned products, not raw satellite "
            "granules.",
        ],
    }

    if not verification["passed"]:
        failed = ", ".join(verification["failed"])
        raise IngestionError(
            "real-file ingestion does not reproduce the frozen measured release: "
            f"{failed}. Refusing to serve a mismatched dataset."
        )

    return IngestionSnapshot(
        sources=sources,
        observations=observations,
        pairs=paired["aqua_snpp"],
        cell_days=cell_days,
        paired=paired,
        report=report,
        data_hash=computed_hash,
    )


def live_harmonization(
    snapshot: IngestionSnapshot,
    artifact: dict[str, Any],
    model_id: str = "H",
) -> dict[str, Any]:
    """Apply the frozen model to every real Aqua-SNPP pair and summarize."""
    pairs = snapshot.pairs
    output = core.predict_harmonized(pairs, artifact, model_id=model_id)

    applicable = output["applicable"].to_numpy(dtype=bool)
    observed = output["frp_sum_snpp"].to_numpy(dtype="float64")
    lower = output["interval_lower_mw"].to_numpy(dtype="float64")
    upper = output["interval_upper_mw"].to_numpy(dtype="float64")
    covered = applicable & np.isfinite(lower) & np.isfinite(upper) & (lower <= observed) & (
        observed <= upper
    )

    raw_residual = output["y"].to_numpy(dtype="float64")
    corrected_residual = raw_residual - output["predicted_log_ratio"].to_numpy(dtype="float64")
    correction = (
        (output["harmonized_frp_mw"].to_numpy(dtype="float64") - output["frp_sum_aqua"].to_numpy(dtype="float64"))
        / output["frp_sum_aqua"].to_numpy(dtype="float64")
        * 100.0
    )

    def _metrics(frame: pd.DataFrame) -> dict[str, Any]:
        mask = frame["applicable"].to_numpy(dtype=bool)
        n = int(len(frame))
        n_applicable = int(mask.sum())
        frame_covered = (
            mask
            & np.isfinite(frame["interval_lower_mw"].to_numpy(dtype="float64"))
            & (frame["interval_lower_mw"].to_numpy(dtype="float64") <= frame["frp_sum_snpp"].to_numpy(dtype="float64"))
            & (frame["frp_sum_snpp"].to_numpy(dtype="float64") <= frame["interval_upper_mw"].to_numpy(dtype="float64"))
        )
        residual = (
            frame["y"].to_numpy(dtype="float64")
            - frame["predicted_log_ratio"].to_numpy(dtype="float64")
        )
        return {
            "n": n,
            "applicable": n_applicable,
            "refused": n - n_applicable,
            "coverage": _round(frame_covered.sum() / n_applicable) if n_applicable else None,
            "raw_rmse": _round(np.sqrt(np.mean(np.square(frame["y"].to_numpy(dtype="float64"))))),
            "harmonized_rmse": _round(np.sqrt(np.mean(np.square(residual[mask])))) if n_applicable else None,
            "mean_correction_percent": _round(
                np.mean(
                    (
                        frame["harmonized_frp_mw"].to_numpy(dtype="float64")[mask]
                        - frame["frp_sum_aqua"].to_numpy(dtype="float64")[mask]
                    )
                    / frame["frp_sum_aqua"].to_numpy(dtype="float64")[mask]
                    * 100.0
                )
            )
            if n_applicable
            else None,
        }

    by_bin: dict[str, dict[str, Any]] = {}
    bin_labels = output["delay_bin"].astype("string")
    for label in core.DELAY_BIN_LABELS:
        mask = (bin_labels == label).to_numpy()
        if mask.any():
            by_bin[str(label)] = _metrics(output.loc[mask])

    by_region: dict[str, dict[str, Any]] = {}
    for region, frame in output.groupby("region", observed=True):
        by_region[str(region)] = _metrics(frame)

    examples: list[dict[str, Any]] = []
    example_source = output.loc[applicable].sort_values(
        ["delay_bin", "region", "acquisition_date"], kind="stable"
    )
    for _, row in example_source.groupby("delay_bin", dropna=False, observed=True).head(2).head(12).iterrows():
        examples.append(
            {
                "cell": str(row["cell_id"]),
                "region": str(row["region"]),
                "date": pd.Timestamp(row["acquisition_date"]).date().isoformat(),
                "delay_h": _round(row["delay_ref"]),
                "delay_bin": str(row["delay_bin"]),
                "frp_aqua_mw": _round(row["frp_sum_aqua"]),
                "observed_frp_snpp_mw": _round(row["frp_sum_snpp"]),
                "harmonized_frp_mw": _round(row["harmonized_frp_mw"]),
                "interval_lower_mw": _round(row["interval_lower_mw"]),
                "interval_upper_mw": _round(row["interval_upper_mw"]),
                "correction_percent": _round(
                    (float(row["harmonized_frp_mw"]) - float(row["frp_sum_aqua"]))
                    / float(row["frp_sum_aqua"])
                    * 100.0
                ),
                "covered": bool(
                    float(row["interval_lower_mw"])
                    <= float(row["frp_sum_snpp"])
                    <= float(row["interval_upper_mw"])
                ),
            }
        )

    return {
        "schema_version": "pyroharmonize.live_harmonization.v1",
        "method": (
            "Frozen model H applied to every real Aqua-SNPP cell-day pair built from "
            "the cleaned CSVs at service start."
        ),
        "interpretation": (
            "In-sample replay against the frozen artifact. It is not independent model "
            "validation and does not replace the grouped cross-validation in /results."
        ),
        "n_pairs": int(len(output)),
        "n_applicable": int(applicable.sum()),
        "n_refused": int((~applicable).sum()),
        "refusals": _counts(output.loc[~applicable, "reason"].dropna()),
        "coverage": _round(covered.sum() / applicable.sum()) if applicable.any() else None,
        "coverage_n": int(applicable.sum()),
        "raw_rmse": _round(np.sqrt(np.mean(np.square(raw_residual)))),
        "harmonized_rmse": _round(np.sqrt(np.mean(np.square(corrected_residual[applicable]))))
        if applicable.any()
        else None,
        "mean_correction_percent": _round(np.mean(correction[applicable])) if applicable.any() else None,
        "median_correction_percent": _round(np.median(correction[applicable])) if applicable.any() else None,
        "by_bin": by_bin,
        "by_region": by_region,
        "examples": examples,
        "provenance": {
            "data_hash": snapshot.data_hash,
            "model": model_id,
        },
    }
