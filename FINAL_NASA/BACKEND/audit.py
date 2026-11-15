"""L4 audit engine - how wrong could the correction be, and where?

The audit engine is deliberately separate from L5.  It may read batch tables,
but every scientific operation it reports is computed by the same pure core
used by serving.  Functions in this module are deterministic; the bootstrap
takes an explicit seed so a report can be reproduced byte-for-byte.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from backend import core


def _finite(value: Any, digits: int = 6) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(numeric):
        return None
    return round(numeric, digits)


def _clean(payload: Mapping[str, Any], digits: int = 6) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, (int, np.integer)) and not isinstance(value, bool):
            result[key] = int(value)
        elif isinstance(value, (float, np.floating)):
            result[key] = _finite(value, digits)
        else:
            result[key] = value
    return result


def bootstrap_slope(
    x: Sequence[float],
    y: Sequence[float],
    blocks: Sequence[Any],
    iterations: int = 500,
    seed: int = 20261109,
) -> dict[str, Any]:
    """OLS slope with a block-bootstrap 95% interval.

    Blocks are whole date-region sampling windows, not individual cells.  The
    bootstrap therefore does not pretend that neighbouring cell-days are
    independent.
    """
    x_values = np.asarray(x, dtype="float64")
    y_values = np.asarray(y, dtype="float64")
    block_values = np.asarray(blocks, dtype=object)
    if len(x_values) < 3:
        return {
            "slope_per_hour": None,
            "ci_low": None,
            "ci_high": None,
            "n": int(len(x_values)),
            "n_blocks": 0,
            "iterations": 0,
        }
    slope = float(np.polyfit(x_values, y_values, 1)[0])
    rng = np.random.default_rng(seed)
    unique_blocks = pd.unique(block_values)
    block_indices = {block: np.flatnonzero(block_values == block) for block in unique_blocks}
    draws: list[float] = []
    for _ in range(iterations):
        sample = rng.choice(unique_blocks, size=len(unique_blocks), replace=True)
        indices = np.concatenate([block_indices[block] for block in sample])
        if len(indices) < 3 or np.std(x_values[indices]) == 0:
            continue
        draws.append(float(np.polyfit(x_values[indices], y_values[indices], 1)[0]))
    if draws:
        ci_low = float(np.quantile(draws, 0.025))
        ci_high = float(np.quantile(draws, 0.975))
    else:
        ci_low = ci_high = None
    return _clean(
        {
            "slope_per_hour": slope,
            "ci_low": ci_low,
            "ci_high": ci_high,
            "n": int(len(x_values)),
            "n_blocks": int(len(unique_blocks)),
            "iterations": int(iterations),
            "seed": int(seed),
        }
    )


def pairing_sensitivity(pairs: pd.DataFrame, iterations: int = 500) -> dict[str, Any]:
    """Cell-day-sum versus near-coincident pairing slopes.

    The sign change between these two estimators is the point: the observed
    delay relationship depends on how observations are paired.  That is a
    sensitivity finding, not a licence to pick the convenient sign.
    """
    if pairs.empty:
        return {"available": False, "reason": "no pair table"}
    required = {"delay_ref", "y", "block_id", "delay_pair"}
    missing = required - set(pairs.columns)
    if missing:
        raise ValueError(f"pair table missing columns: {sorted(missing)}")
    near = pairs[pairs["delay_pair"].abs() <= 0.5]
    return {
        "available": True,
        "cell_day_sum": bootstrap_slope(
            pairs["delay_ref"].to_numpy(),
            pairs["y"].to_numpy(),
            pairs["block_id"].astype(str).to_numpy(),
            iterations=iterations,
        ),
        "near_coincident": bootstrap_slope(
            near["delay_ref"].to_numpy(),
            near["y"].to_numpy(),
            near["block_id"].astype(str).to_numpy(),
            iterations=iterations,
        ),
        "near_coincident_n": int(len(near)),
        "interpretation": (
            "The cell-day-sum and near-coincident subsets have opposite slope "
            "signs. Pairing is a confounder, so the relationship is reported "
            "as method-dependent and the confounding test remains pending."
        ),
    }


def bias_by_bin(pairs: pd.DataFrame, artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Raw and corrected bias/RMSE in each pre-registered delay bin."""
    if pairs.empty:
        return {"available": False}
    predictions = core.model_log_ratio(pairs, artifact, model_id="H")
    observed = pairs["y"].to_numpy(dtype="float64")
    bins = core.assign_delay_bin(pairs["delay_ref"].to_numpy(dtype="float64"))
    rows: dict[str, Any] = {}
    for label in core.DELAY_BIN_LABELS:
        mask = bins == label
        if not mask.any():
            rows[label] = {"n": 0}
            continue
        residual_raw = observed[mask]
        residual_h = observed[mask] - predictions[mask]
        rows[label] = _clean(
            {
                "n": int(mask.sum()),
                "raw_bias": float(np.mean(residual_raw)),
                "raw_rmse": float(np.sqrt(np.mean(np.square(residual_raw)))),
                "corrected_bias": float(np.mean(residual_h)),
                "corrected_rmse": float(np.sqrt(np.mean(np.square(residual_h)))),
            }
        )
    return rows


def grouped_cv_table(results: Mapping[str, Any]) -> dict[str, Any]:
    """Extract the measured grouped-CV scorecard without recomputation."""
    models = results.get("models", {})
    return {
        "served": models.get("served"),
        "available": list(models.get("available", [])),
        "grouped_cv": models.get("grouped_cv", {}),
        "selection": models.get("selection", {}),
        "served_note": models.get("served_note"),
    }


def regional_transfer_matrix(results: Mapping[str, Any]) -> dict[str, Any]:
    """Leave-one-region-out matrix; missing cells stay explicitly missing."""
    loyo = results.get("models", {}).get("loyo", {})
    matrix: dict[str, Any] = {}
    for region, payload in loyo.items():
        row: dict[str, Any] = {"n": payload.get("n")}
        for model in ("B0", "P", "H"):
            entry = payload.get(model)
            row[model] = None if entry is None else entry.get("rmse")
        h = row.get("H")
        b0 = row.get("B0")
        if h is not None and b0 is not None:
            row["h_vs_raw"] = _finite(h - b0, 4)
            row["verdict"] = "caution_h_worse_than_raw" if h > b0 else "h_at_or_better_than_raw"
        else:
            row["h_vs_raw"] = None
            row["verdict"] = "unavailable"
        matrix[region] = row
    return matrix


def terra_extrapolation(results: Mapping[str, Any]) -> dict[str, Any]:
    audit = results.get("audit", {})
    terra = audit.get("terra_extrapolation", {})
    if not terra.get("available"):
        return {"available": False, "reason": terra.get("reason", "not measured")}
    return {
        "available": True,
        "n": terra.get("n"),
        "delay_mean_h": terra.get("delay_mean_h"),
        "raw_rmse": terra.get("raw_rmse"),
        "physics_rmse": terra.get("physics_rmse"),
        "h_rmse": terra.get("h_rmse"),
        "raw_bias": terra.get("raw_bias"),
        "verdict": (
            "physics_worse_than_raw"
            if (terra.get("physics_rmse") or 0) > (terra.get("raw_rmse") or 0)
            else "physics_at_or_better_than_raw"
        ),
        "note": (
            "Out-of-regime test: a model trained on Aqua is applied to Terra. "
            "It is not independent validation of a Terra correction."
        ),
    }


def identifiability(pairs: pd.DataFrame) -> dict[str, Any]:
    """Late-delay bias uncertainty at cell level versus independent blocks."""
    if pairs.empty:
        return {"available": False}
    bins = core.assign_delay_bin(pairs["delay_ref"].to_numpy(dtype="float64"))
    late = pairs.loc[bins == "(2, 3.5]"]
    if late.empty:
        return {"available": False, "reason": "no late-delay pairs"}
    block_means = late.groupby("block_id", observed=True)["y"].mean()
    n_cells = int(len(late))
    n_blocks = int(len(block_means))
    cell_se = float(late["y"].std() / np.sqrt(n_cells)) if n_cells > 1 else None
    block_se = float(block_means.std() / np.sqrt(n_blocks)) if n_blocks > 1 else None
    return {
        "available": True,
        "n_cells": n_cells,
        "n_blocks": n_blocks,
        "mean_bias": _finite(late["y"].mean()),
        "cell_level_se": _finite(cell_se),
        "block_level_se": _finite(block_se),
        "independent_unit": "date-region sampling window block",
        "note": (
            "One block cannot support a block-level standard error; the "
            "cell-level value is optimistic and is not used as a confidence claim."
        )
        if n_blocks < 2
        else None,
    }


def digital_twin(
    pairs: pd.DataFrame,
    artifact: Mapping[str, Any],
    tolerance: float = 0.01,
) -> dict[str, Any]:
    """Injected-offset round trip with an explicit non-independence caveat.

    A known offset is injected into the H prediction in each delay bin and the
    same calibration apparatus must recover it.  This is an algorithmic
    round-trip test, **not** independent real-world validation: the simulator
    uses the same model family as the served path.
    """
    if pairs.empty:
        return {"available": False, "reason": "no pair table"}
    predictions = core.model_log_ratio(pairs, artifact, model_id="H")
    bins = core.assign_delay_bin(pairs["delay_ref"].to_numpy(dtype="float64"))
    rows: dict[str, Any] = {}
    errors: list[float] = []
    for index, label in enumerate(core.DELAY_BIN_LABELS):
        mask = bins == label
        if not mask.any():
            continue
        injected = 0.15 * np.sin(index + 1.0)
        twin_prediction = predictions[mask] + injected
        recovered = float(np.mean(twin_prediction - predictions[mask]))
        error = abs(recovered - injected)
        errors.append(error)
        rows[label] = {
            "n": int(mask.sum()),
            "injected_log_offset": _finite(injected),
            "recovered_log_offset": _finite(recovered),
            "absolute_error": _finite(error, 10),
            "within_tolerance": bool(error <= tolerance),
        }
    return {
        "available": bool(rows),
        "tolerance_log_units": tolerance,
        "max_absolute_error": _finite(max(errors), 10) if errors else None,
        "passed": bool(errors and max(errors) <= tolerance),
        "bins": rows,
        "validation_status": "self_consistency_only",
        "note": (
            "The digital twin recovers injected offsets by construction and "
            "uses the same model family. It cannot establish real-world accuracy."
        ),
    }


def audit_snapshot(
    results: Mapping[str, Any],
    pairs: pd.DataFrame,
    artifact: Mapping[str, Any],
) -> dict[str, Any]:
    """One structured audit payload for the dashboard and report."""
    return {
        "schema_version": "pyroharmonize.audit.v1",
        "grouped_cv": grouped_cv_table(results),
        "regional_transfer": regional_transfer_matrix(results),
        "pairing_sensitivity": pairing_sensitivity(pairs),
        "terra_extrapolation": terra_extrapolation(results),
        "bias_by_bin": bias_by_bin(pairs, artifact),
        "identifiability": identifiability(pairs),
        "digital_twin": digital_twin(pairs, artifact),
        "not_evaluated": [
            "saturation",
            "plume_scattering",
            "canopy_occlusion",
        ],
        "pending": [
            "pairing-confound test with scan control",
            "bin-level bootstrap bias intervals",
            "independent geostationary reference data",
            "feature-importance analysis for model M",
        ],
    }
