"""Reproducible L2-L5 analysis pipeline.

Reads the L1 canonical parquet, builds cell-days and pairs, fits every model
with grouped cross-validation, calibrates conformal intervals, builds the
applicability gate, runs the audits and writes a single hashed results file.

The pipeline never writes to ``data/raw`` or the L1 canonical table.
"""

from __future__ import annotations

import hashlib
import json
import math
import pickle
import platform
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import scipy
import sklearn

from pyroharmonize import config
from pyroharmonize.l2 import (
    DELAY_BIN_LABELS,
    REFERENCE_LST_H,
    REGION_ORDER,
    add_pixel_contract,
    build_cell_days,
    composition,
    delay_bin,
    pair_cell_days,
    region_weights,
)
from pyroharmonize.models import (
    ALPHA,
    COVERAGE_FLOOR,
    FEATURES,
    MIN_CALIBRATION_PAIRS,
    MODEL_IDS,
    NOMINAL_COVERAGE,
    calibration_table,
    build_gate,
    coverage_table,
    fit_models,
    nested_conformal_coverage,
    predict_harmonized,
    predict_models,
    residual_metrics,
)
from pyroharmonize.provenance import sha256_file, write_json

L1_CANONICAL = config.PROCESSED_DIR / "l1_canonical.parquet"
CELL_DAYS_PATH = config.PROCESSED_DIR / "cell_days.parquet"
PAIRS_PATH = config.PROCESSED_DIR / "pairs_aqua_snpp.parquet"
PAIRS_TERRA_PATH = config.PROCESSED_DIR / "pairs_terra_snpp.parquet"
PAIRS_NOAA20_PATH = config.PROCESSED_DIR / "pairs_noaa20_snpp.parquet"
RESULTS_PATH = config.ARTIFACTS_DIR / "results" / "results.json"
RESULTS_HASH_PATH = config.ARTIFACTS_DIR / "results" / "results.sha256"
MODEL_DIR = config.ARTIFACTS_DIR / "models"
REPORT_PATH = config.REPORT_DIR / "l2_l5_analysis.json"

SERVED_MODEL = "H"
PIPELINE_VERSION = "l2-l5-v1"

LIMITATIONS: tuple[str, ...] = (
    "Four study regions only; this is not a global archive.",
    "Five 5-day sampling windows per year from 2021 to 2025.",
    "Saturation, plume scattering and canopy occlusion are not modelled; "
    "they are reported as not evaluated.",
    "Corrections above 2 h of delay are refused because calibration support is thin.",
    "Pairing only detections biases the sample toward larger fires.",
    "Conformal intervals describe cell-day noise, not individual-pixel accuracy.",
    "Improved agreement between sensors is not proof of improved accuracy without "
    "independent reference data.",
)

REQUIRED_COLUMNS = [
    "satellite",
    "sampling_region",
    "sample_window_start",
    "sample_window_days",
    "acquisition_date",
    "acquisition_time_utc",
    "latitude",
    "longitude",
    "frp",
    "scan",
    "track",
    "type",
    "daynight",
]


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, pd.Interval):
        return str(value)
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def _data_hash() -> str:
    """Documented data_hash from the Phase 0 per-file digests.

    data_hash = SHA-256(concat(per-file SHA-256 hex, MODIS, SNPP, NOAA-20)).
    The manifest already holds the verified digests, so no 288 MB read is
    repeated here.
    """
    manifest = json.loads(config.MANIFEST_PATH.read_text(encoding="utf-8"))
    digests = {entry["path"]: entry["sha256"] for entry in manifest["files"]}
    concatenated = "".join(
        digests[config.CLEANED_FILES[sensor]] for sensor in config.SENSOR_ORDER
    )
    return hashlib.sha256(concatenated.encode("ascii")).hexdigest()


def _clean_float(value: Any, digits: int = 6) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(numeric):
        return None
    return round(numeric, digits)


def _round_dict(payload: dict[str, Any], digits: int = 6) -> dict[str, Any]:
    return {
        key: round(float(value), digits) if isinstance(value, (int, float, np.integer, np.floating)) else value
        for key, value in payload.items()
    }


def _oof_predictions(pairs: pd.DataFrame) -> pd.DataFrame:
    """Leave-one-sampling-window-out predictions for every model."""
    blocks = sorted(pairs["block_id"].astype(str).unique())
    columns: dict[str, np.ndarray] = {
        model: np.full(len(pairs), np.nan, dtype="float64") for model in MODEL_IDS
    }
    for block in blocks:
        test_mask = (pairs["block_id"].astype(str) == block).to_numpy()
        train = pairs.loc[~test_mask].copy()
        test = pairs.loc[test_mask].copy()
        model_set = fit_models(train)
        predictions = predict_models(model_set, test)
        for model in MODEL_IDS:
            values = columns[model]
            values[test_mask] = predictions[model]
    result = pairs.copy()
    for model in MODEL_IDS:
        result[f"yhat_{model}"] = columns[model]
        result[f"residual_{model}"] = result["y"] - result[f"yhat_{model}"]
    return result


def _loyo_metrics(pairs: pd.DataFrame) -> dict[str, Any]:
    """Leave-one-region-out RMSE for raw, P and H (the compared models)."""
    regions = sorted(pairs["region"].astype(str).unique())
    payload: dict[str, Any] = {}
    for region in regions:
        test_mask = (pairs["region"].astype(str) == region).to_numpy()
        train = pairs.loc[~test_mask]
        test = pairs.loc[test_mask]
        if len(train) < 20 or len(test) < 5:
            continue
        model_set = fit_models(train)
        predictions = predict_models(model_set, test)
        payload[region] = {
            "n": int(len(test)),
            "B0": _round_dict(residual_metrics(test["y"].to_numpy(), predictions["B0"])),
            "P": _round_dict(residual_metrics(test["y"].to_numpy(), predictions["P"])),
            "H": _round_dict(residual_metrics(test["y"].to_numpy(), predictions["H"])),
        }
    return payload


def _year_selection(pairs: pd.DataFrame, years: tuple[int, ...] = (2021, 2023)) -> dict[str, Any]:
    """Pre-registered selection: leave-one-year-out RMSE on 2021 and 2023."""
    payload: dict[str, Any] = {}
    scores: dict[str, list[float]] = {model: [] for model in MODEL_IDS}
    for year in years:
        train = pairs[(pairs["year"] != year) & (pairs["year"].between(min(years), max(years)))].copy()
        test = pairs[pairs["year"] == year].copy()
        if len(train) < 50 or len(test) < 5:
            continue
        model_set = fit_models(train)
        predictions = predict_models(model_set, test)
        payload[str(year)] = {"n_train": int(len(train)), "n_test": int(len(test))}
        for model in MODEL_IDS:
            metrics = residual_metrics(test["y"].to_numpy(), predictions[model])
            payload[str(year)][model] = _round_dict(metrics)
            scores[model].append(metrics["rmse"])
    mean_scores = {
        model: (float(np.mean(values)) if values else None)
        for model, values in scores.items()
    }
    winner = min(
        (model for model in MODEL_IDS if mean_scores[model] is not None),
        key=lambda model: mean_scores[model],
    )
    return {"folds": payload, "mean_rmse": mean_scores, "winner": winner, "years": list(years)}


def _bootstrap_slope(
    x: np.ndarray,
    y: np.ndarray,
    blocks: np.ndarray,
    iterations: int = 500,
    seed: int = 20261109,
) -> dict[str, Any]:
    """OLS slope with a block-bootstrap 95% interval."""
    if len(x) < 3:
        return {"slope": None, "ci_low": None, "ci_high": None, "n": int(len(x))}
    slope = float(np.polyfit(x, y, 1)[0])
    rng = np.random.default_rng(seed)
    unique_blocks = pd.unique(blocks)
    block_indices = {block: np.flatnonzero(blocks == block) for block in unique_blocks}
    draws: list[float] = []
    for _ in range(iterations):
        sample = rng.choice(unique_blocks, size=len(unique_blocks), replace=True)
        indices = np.concatenate([block_indices[block] for block in sample])
        if len(indices) < 3 or np.std(x[indices]) == 0:
            continue
        draws.append(float(np.polyfit(x[indices], y[indices], 1)[0]))
    if not draws:
        ci_low = ci_high = None
    else:
        ci_low = float(np.quantile(draws, 0.025))
        ci_high = float(np.quantile(draws, 0.975))
    return {
        "slope_per_hour": slope,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "n": int(len(x)),
        "n_blocks": int(len(unique_blocks)),
        "iterations": int(iterations),
    }


def _pairing_sensitivity(pairs: pd.DataFrame) -> dict[str, Any]:
    near = pairs[pairs["delay_pair"].abs() <= 0.5]
    return {
        "cell_day_sum": _bootstrap_slope(
            pairs["delay_ref"].to_numpy(),
            pairs["y"].to_numpy(),
            pairs["block_id"].astype(str).to_numpy(),
        ),
        "near_coincident": _bootstrap_slope(
            near["delay_ref"].to_numpy(),
            near["y"].to_numpy(),
            near["block_id"].astype(str).to_numpy(),
        ),
        "near_coincident_n": int(len(near)),
    }


def _bias_by_bin(pairs: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {}
    bins = delay_bin(pairs["delay_ref"])
    for label in DELAY_BIN_LABELS:
        mask = (bins == label).to_numpy()
        if not mask.any():
            result[label] = {"n": 0}
            continue
        subset = pairs.loc[mask]
        result[label] = {
            "n": int(len(subset)),
            "raw_bias": _clean_float(subset["y"].mean()),
            "raw_rmse": _clean_float(np.sqrt(np.mean(np.square(subset["y"])))),
            "corrected_bias": _clean_float(subset["residual_H"].mean()),
            "corrected_rmse": _clean_float(np.sqrt(np.mean(np.square(subset["residual_H"])))),
        }
    return result


def _terra_audit(aqua_pairs: pd.DataFrame, terra_pairs: pd.DataFrame) -> dict[str, Any]:
    """Out-of-regime test: Aqua-trained physics model applied to Terra."""
    if terra_pairs.empty:
        return {"available": False, "reason": "no Terra-SNPP pairs"}
    model_set = fit_models(aqua_pairs)
    predictions = predict_models(model_set, terra_pairs)
    return {
        "available": True,
        "n": int(len(terra_pairs)),
        "delay_mean_h": _clean_float(terra_pairs["delay_ref"].mean()),
        "raw_rmse": _clean_float(residual_metrics(terra_pairs["y"].to_numpy(), predictions["B0"])["rmse"]),
        "physics_rmse": _clean_float(residual_metrics(terra_pairs["y"].to_numpy(), predictions["P"])["rmse"]),
        "h_rmse": _clean_float(residual_metrics(terra_pairs["y"].to_numpy(), predictions["H"])["rmse"]),
        "raw_bias": _clean_float(terra_pairs["y"].mean()),
    }


def _fre_trend(pixels: pd.DataFrame) -> dict[str, Any]:
    """Naive log-linear FRP trend with a standard 95% interval."""
    yearly = (
        pixels.loc[pixels["validated"]]
        .groupby("year", observed=True)["frp"]
        .sum()
        .sort_index()
    )
    years = yearly.index.to_numpy(dtype="float64")
    log_total = np.log(yearly.to_numpy(dtype="float64"))
    if len(years) < 3:
        return {"available": False}
    slope, intercept = np.polyfit(years, log_total, 1)
    fitted = intercept + slope * years
    residual = log_total - fitted
    dof = len(years) - 2
    sse = float(np.sum(np.square(residual)))
    se = math.sqrt(sse / dof / np.sum(np.square(years - years.mean())))
    # t critical ~2.776 for 4 dof; use normal 1.96 for a transparent report.
    ci_low = slope - 1.96 * se
    ci_high = slope + 1.96 * se
    return {
        "available": True,
        "unit": "annual validated FRP total, all sensors",
        "naive_slope_percent_per_year": _clean_float((math.exp(slope) - 1.0) * 100.0),
        "ci_low_percent": _clean_float((math.exp(ci_low) - 1.0) * 100.0),
        "ci_high_percent": _clean_float((math.exp(ci_high) - 1.0) * 100.0),
        "significant": bool(ci_low > 0 or ci_high < 0),
        "yearly_frp": {str(int(year)): _clean_float(value) for year, value in yearly.items()},
    }


def _identifiability(pairs: pd.DataFrame) -> dict[str, Any]:
    """Late-delay bias uncertainty at cell level versus date-region blocks."""
    late = pairs[delay_bin(pairs["delay_ref"]) == "(2, 3.5]"]
    if late.empty:
        return {"available": False}
    block_means = late.groupby("block_id", observed=True)["y"].mean()
    n_cells = len(late)
    n_blocks = len(block_means)
    cell_se = float(late["y"].std() / math.sqrt(n_cells)) if n_cells > 1 else None
    block_se = float(block_means.std() / math.sqrt(n_blocks)) if n_blocks > 1 else None
    return {
        "available": True,
        "n_cells": int(n_cells),
        "n_blocks": int(n_blocks),
        "mean_bias": _clean_float(late["y"].mean()),
        "cell_level_se": _clean_float(cell_se),
        "block_level_se": _clean_float(block_se),
        "independent_unit": "date-region sampling window block",
    }


def _validity_map(pairs: pd.DataFrame, gate: dict[str, Any]) -> dict[str, Any]:
    """Per-region and per-bin counts and applicability of the grouped OOF model."""
    bins = delay_bin(pairs["delay_ref"])
    result: dict[str, Any] = {}
    for region in REGION_ORDER:
        subset = pairs[pairs["region"].astype(str) == region]
        region_bins = delay_bin(subset["delay_ref"])
        bin_rows: dict[str, Any] = {}
        for label in DELAY_BIN_LABELS:
            mask = region_bins == label
            if not mask.any():
                bin_rows[label] = {"n": 0, "applicable": 0, "coverage": None}
                continue
            piece = subset.loc[mask]
            gate_bin = gate["bins"][label]
            bin_rows[label] = {
                "n": int(len(piece)),
                "applicable": int(len(piece)) if gate_bin["applicable"] else 0,
                "coverage": gate_bin["coverage"],
                "gate_reason": gate_bin["reason"],
                "raw_bias": _clean_float(piece["y"].mean()),
            }
        result[region] = {
            "n_pairs": int(len(subset)),
            "share": _clean_float(len(subset) / len(pairs)),
            "bins": bin_rows,
        }
    return result


def _lat_lon_bounds(pixels: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for region, subset in pixels.groupby("sampling_region", observed=True):
        result[str(region)] = {
            "lat_min": _clean_float(subset["latitude"].min(), 4),
            "lat_max": _clean_float(subset["latitude"].max(), 4),
            "lon_min": _clean_float(subset["longitude"].min(), 4),
            "lon_max": _clean_float(subset["longitude"].max(), 4),
            "rows": int(len(subset)),
        }
    return result


def _region_summary(pairs: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for region in REGION_ORDER:
        subset = pairs[pairs["region"].astype(str) == region]
        if subset.empty:
            result[region] = {"n": 0}
            continue
        result[region] = {
            "n": int(len(subset)),
            "share": _clean_float(len(subset) / len(pairs)),
            "delay_mean_h": _clean_float(subset["delay_ref"].mean()),
            "delay_median_h": _clean_float(subset["delay_ref"].median()),
            "raw_bias": _clean_float(subset["y"].mean()),
            "raw_rmse": _clean_float(np.sqrt(np.mean(np.square(subset["y"])))),
        }
    return result


def run_analysis(force: bool = False) -> dict[str, Any]:
    if not force and RESULTS_PATH.exists():
        existing = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
        return {"skipped": True, **existing.get("provenance", {})}

    started = datetime.now(timezone.utc)
    print("[analysis] reading L1 canonical ...")
    pixels = pd.read_parquet(L1_CANONICAL, columns=REQUIRED_COLUMNS)
    pixels = add_pixel_contract(pixels)
    comp = composition(pixels)
    print(
        f"[analysis] rows={comp.rows} validated={comp.validated_rows} "
        f"satellites={comp.rows_by_satellite}"
    )

    print("[analysis] aggregating 1-degree cell-days ...")
    cell_frames = []
    for satellite in ("Aqua", "N", "N20", "Terra"):
        frame = build_cell_days(pixels, satellite)
        cell_frames.append(frame)
        print(f"[analysis]   {satellite}: {len(frame)} cell-days")
    cell_days = pd.concat(cell_frames, ignore_index=True)
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    cell_days.to_parquet(CELL_DAYS_PATH, index=False, compression="zstd")

    aqua_days = cell_days[cell_days["satellite"] == "Aqua"]
    snpp_days = cell_days[cell_days["satellite"] == "N"]
    n20_days = cell_days[cell_days["satellite"] == "N20"]
    terra_days = cell_days[cell_days["satellite"] == "Terra"]

    print("[analysis] pairing Aqua-SNPP ...")
    pairs = pair_cell_days(aqua_days, snpp_days, "SNPP")
    pairs["fit_weight"] = region_weights(pairs["y"], pairs["region"]).to_numpy()
    pairs.to_parquet(PAIRS_PATH, index=False, compression="zstd")
    print(f"[analysis] pairs={len(pairs)}")

    terra_pairs = pair_cell_days(terra_days, snpp_days, "SNPP")
    terra_pairs.to_parquet(PAIRS_TERRA_PATH, index=False, compression="zstd")
    n20_pairs = pair_cell_days(n20_days, snpp_days, "SNPP")
    n20_pairs.to_parquet(PAIRS_NOAA20_PATH, index=False, compression="zstd")
    print(f"[analysis] Terra pairs={len(terra_pairs)} NOAA20 pairs={len(n20_pairs)}")

    print("[analysis] leave-one-window-out predictions for all models ...")
    oof = _oof_predictions(pairs)

    grouped_metrics: dict[str, Any] = {}
    for model in MODEL_IDS:
        grouped_metrics[model] = _round_dict(
            residual_metrics(oof["y"].to_numpy(), oof[f"yhat_{model}"].to_numpy())
        )

    print("[analysis] leave-one-region-out ...")
    loyo = _loyo_metrics(pairs)
    print("[analysis] pre-registered year selection ...")
    selection = _year_selection(pairs)

    print("[analysis] conformal calibration and honest coverage ...")
    residual = oof["residual_H"]
    bins = delay_bin(oof["delay_ref"])
    calibration = calibration_table(residual, bins)
    in_sample_coverage = coverage_table(residual, bins, {
        label: calibration["bins"][label]["quantile"] for label in DELAY_BIN_LABELS
    })
    nested = nested_conformal_coverage(residual, bins, oof["block_id"])
    gate = build_gate(calibration, nested, pairs)

    print("[analysis] fitting final model artifact on all pairs ...")
    final_models = fit_models(pairs)
    final_models.selection = {
        "rule": "lowest leave-one-year-out RMSE on 2021 and 2023",
        "winner": selection["winner"],
        "mean_rmse": selection["mean_rmse"],
        "served_model": SERVED_MODEL,
        "served_model_note": (
            "H is served by the product specification; PR/M remain research-only "
            "until owner sign-off. The selection result is reported, not hidden."
        ),
    }

    artifact = final_models.to_artifact()
    artifact.update(
        {
            "conformal": calibration,
            "gate": gate,
            "served_model": SERVED_MODEL,
            "pipeline_version": PIPELINE_VERSION,
            "region_order": list(REGION_ORDER),
            "reference_lst_h": REFERENCE_LST_H,
            "limitations": list(LIMITATIONS),
        }
    )
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    artifact_path = MODEL_DIR / "model_H.pkl"
    with artifact_path.open("wb") as handle:
        pickle.dump(artifact, handle, protocol=pickle.HIGHEST_PROTOCOL)
    artifact_hash = sha256_file(artifact_path)

    # Transform the OOF table into validity and audit views.
    oof = oof.copy()
    oof["delay_bin"] = delay_bin(oof["delay_ref"])
    oof["applicable"] = [
        bool(gate["bins"][str(label)]["applicable"]) if pd.notna(label) else False
        for label in oof["delay_bin"]
    ]

    bias_bins = _bias_by_bin(oof)
    pairing = _pairing_sensitivity(pairs)
    terra = _terra_audit(pairs, terra_pairs)
    trend = _fre_trend(pixels)
    ident = _identifiability(pairs)
    validity = _validity_map(oof, gate)

    # Example inputs from the real pair table, used by the dashboard but labelled
    # as actual observations, never as fabricated demo values.
    sample = pairs.sort_values(["delay_ref"]).iloc[
        [0, len(pairs) // 2, len(pairs) - 1]
    ]
    actual_examples = []
    for _, row in sample.iterrows():
        actual_examples.append(
            {
                "region": row["region"],
                "date": row["acquisition_date"].date().isoformat(),
                "cell": row["cell_id"],
                "frp_aqua_mw": _clean_float(row["frp_sum_aqua"]),
                "detections": int(row["n_aqua"]),
                "lst_aqua_h": _clean_float(row["lst_aqua"]),
                "scan_aqua": _clean_float(row["scan_aqua"]),
                "delay_h": _clean_float(row["delay_ref"]),
                "observed_frp_snpp_mw": _clean_float(row["frp_sum_snpp"]),
            }
        )

    counts_by_region = {
        region: int((pairs["region"].astype(str) == region).sum()) for region in REGION_ORDER
    }
    data_hash = _data_hash()
    config_payload = {
        "reference_lst_h": REFERENCE_LST_H,
        "delay_bins": list(DELAY_BIN_LABELS),
        "alpha": ALPHA,
        "coverage_floor": COVERAGE_FLOOR,
        "min_calibration_pairs": MIN_CALIBRATION_PAIRS,
        "ridge_lambda": artifact["h_params"].get("fit", {}).get("ridge_lambda"),
        "cell_definition": "floor(latitude) x floor(longitude), 1 degree",
        "validation_rule": "type == 0 AND frp > 0 AND daynight == D",
    }
    config_hash = hashlib.sha256(
        json.dumps(config_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    provenance = {
        "data_hash": data_hash,
        "data_hash_begins": data_hash[:12],
        "config_hash": config_hash,
        "pipeline_version": PIPELINE_VERSION,
        "git_commit": "unknown",
        "source_archive_sha256": "09aa2c1da7fbb8d030df5dc6faa0b95ba879a1fffd44374d7fd95aa77d2db0b8",
        "l1_canonical_sha256": sha256_file(L1_CANONICAL),
        "pairs_sha256": sha256_file(PAIRS_PATH),
        "cell_days_sha256": sha256_file(CELL_DAYS_PATH),
        "model_artifact": MODEL_DIR.joinpath("model_H.pkl").as_posix(),
        "model_artifact_sha256": artifact_hash,
        "library_versions": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scipy": scipy.__version__,
            "scikit_learn": sklearn.__version__,
        },
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "runtime_s": _clean_float((datetime.now(timezone.utc) - started).total_seconds(), 3),
    }

    results = {
        "schema_version": "pyroharmonize.results.v1",
        "generated_at_utc": provenance["generated_at_utc"],
        "provenance": provenance,
        "dataset": {
            "rows": comp.rows,
            "validated_rows": comp.validated_rows,
            "rows_by_satellite": comp.rows_by_satellite,
            "rows_by_region": comp.rows_by_region,
            "rows_by_year": comp.rows_by_year,
            "validated_by_satellite": comp.validated_by_satellite,
            "flags": comp.flags,
            "date_min": pixels["acquisition_date"].min().date().isoformat(),
            "date_max": pixels["acquisition_date"].max().date().isoformat(),
            "windows": int(pixels["sample_window_start"].nunique()),
            "window_starts": sorted(
                timestamp.date().isoformat()
                for timestamp in pixels["sample_window_start"].drop_duplicates()
            ),
            "window_days": int(pixels["sample_window_days"].max()),
            "regions": len(comp.rows_by_region),
            "region_bounds": _lat_lon_bounds(pixels),
        },
        "pairs": {
            "count": int(len(pairs)),
            "by_region": counts_by_region,
            "share_by_region": {
                region: _clean_float(count / len(pairs)) for region, count in counts_by_region.items()
            },
            "aqua_cell_days": int(len(aqua_days)),
            "snpp_cell_days": int(len(snpp_days)),
            "terra_pairs": int(len(terra_pairs)),
            "noaa20_snpp_pairs": int(len(n20_pairs)),
            "delay_ref_mean_h": _clean_float(pairs["delay_ref"].mean()),
            "delay_ref_median_h": _clean_float(pairs["delay_ref"].median()),
            "delay_ref_min_h": _clean_float(pairs["delay_ref"].min()),
            "delay_ref_max_h": _clean_float(pairs["delay_ref"].max()),
            "y_mean": _clean_float(pairs["y"].mean()),
            "y_std": _clean_float(pairs["y"].std()),
            "region_summary": _region_summary(pairs),
        },
        "models": {
            "served": SERVED_MODEL,
            "available": list(MODEL_IDS),
            "grouped_cv": grouped_metrics,
            "loyo": loyo,
            "selection": selection,
            "params": {
                "H": {
                    "c": _clean_float(artifact["h_params"]["c"]),
                    "t0": _clean_float(artifact["h_params"]["t0"]),
                    "b": _clean_float(artifact["h_params"]["b"]),
                    "sigma": _clean_float(artifact["h_params"]["sigma"]),
                    "offsets": {k: _clean_float(v) for k, v in artifact["h_params"].get("offsets", {}).items()},
                },
                "P": {
                    "c": _clean_float(artifact["p_params"]["c"]),
                    "t0": _clean_float(artifact["p_params"]["t0"]),
                    "b": _clean_float(artifact["p_params"]["b"]),
                    "sigma": _clean_float(artifact["p_params"]["sigma"]),
                },
            },
            "served_note": (
                "H is a physics-structured correction with regional offsets. "
                "The ML models are research comparisons and cannot be selected "
                "in the operational path until owner sign-off."
            ),
        },
        "uncertainty": {
            "alpha": ALPHA,
            "nominal_coverage": NOMINAL_COVERAGE,
            "overall_coverage": nested["overall_coverage"],
            "in_sample_coverage": in_sample_coverage["overall_coverage"],
            "nested": nested["bins"],
            "in_sample": in_sample_coverage["bins"],
            "calibration": calibration["bins"],
            "bin_order": list(DELAY_BIN_LABELS),
        },
        "gate": gate,
        "validity_map": validity,
        "audit": {
            "bias_by_bin": bias_bins,
            "pairing_sensitivity": pairing,
            "terra_extrapolation": terra,
            "fre_trend": trend,
            "identifiability": ident,
            "not_evaluated": [
                "saturation",
                "plume_scattering",
                "canopy_occlusion",
            ],
            "pending": [
                "independent geostationary reference data",
                "pairing-confound test with scan control",
                "bin-level bootstrap bias intervals",
            ],
        },
        "actual_examples": actual_examples,
        "limitations": list(LIMITATIONS),
    }

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json(RESULTS_PATH, results)
    results_hash = sha256_file(RESULTS_PATH)
    RESULTS_HASH_PATH.write_text(results_hash + "\n", encoding="utf-8")
    write_json(REPORT_PATH, results)
    print(
        f"[analysis] wrote {RESULTS_PATH} ({results_hash[:12]}) "
        f"and {artifact_path} ({artifact_hash[:12]})"
    )
    return results
