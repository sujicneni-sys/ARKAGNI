"""L5 core: pure, vectorised harmonization models, conformal intervals, gate.

The module contains no file reads, network calls or clock access.  Fitting is
separate from prediction so the same ``predict_harmonized`` function is used by
batch evaluation, the audit engine and the FastAPI service.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import least_squares
from sklearn.ensemble import GradientBoostingRegressor

from pyroharmonize.l2 import (
    DELAY_BIN_LABELS,
    REFERENCE_LST_H,
    delay_bin,
)

MODEL_IDS: tuple[str, ...] = ("B0", "B1", "B2", "P", "H", "M", "PR")

FEATURES: tuple[str, ...] = (
    "ln_frp_aqua",
    "delay_ref",
    "ln_area_aqua",
    "ln_n_aqua",
    "latitude",
    "longitude",
)

ALPHA = 0.20
NOMINAL_COVERAGE = 1.0 - ALPHA
MIN_CALIBRATION_PAIRS = 40
COVERAGE_FLOOR = 0.70
RIDGE_LAMBDA = 100.0


def _g(t: np.ndarray, t0: np.ndarray | float, b: np.ndarray | float, sigma: np.ndarray | float) -> np.ndarray:
    """Diurnal shape g(t) = ln(b + (1-b) exp(-(t-t0)^2 / (2 sigma^2)))."""
    b = np.clip(b, 1e-6, 1.0 - 1e-6)
    exponent = -np.square(t - t0) / (2.0 * np.square(sigma))
    inside = b + (1.0 - b) * np.exp(exponent)
    return np.log(np.clip(inside, 1e-12, None))


def physics_prediction(
    lst: np.ndarray,
    regions: np.ndarray,
    params: dict[str, Any],
    use_offsets: bool = False,
) -> np.ndarray:
    """P or H prediction: c + g(t) - g(13.6) + optional regional offsets."""
    t = np.asarray(lst, dtype="float64")
    c = float(params["c"])
    t0 = float(params["t0"])
    b = float(params["b"])
    sigma = float(params["sigma"])
    prediction = c + _g(t, t0, b, sigma) - _g(
        np.asarray([REFERENCE_LST_H]), t0, b, sigma
    )[0]
    if use_offsets:
        offsets = params.get("offsets", {})
        prediction = prediction + np.asarray(
            [float(offsets.get(str(region), 0.0)) for region in regions],
            dtype="float64",
        )
    return prediction


def feature_frame(pairs: pd.DataFrame) -> pd.DataFrame:
    """Aqua-side features only; no VIIRS leakage."""
    features = pd.DataFrame(index=pairs.index)
    features["ln_frp_aqua"] = np.log(pairs["frp_sum_aqua"].to_numpy(dtype="float64"))
    features["delay_ref"] = pairs["delay_ref"].to_numpy(dtype="float64")
    features["ln_area_aqua"] = np.log(
        np.clip(pairs["area_ratio_aqua"].to_numpy(dtype="float64"), 1e-6, None)
    )
    features["ln_n_aqua"] = np.log(
        np.clip(pairs["n_aqua"].to_numpy(dtype="float64"), 1.0, None)
    )
    features["latitude"] = pairs["latitude_aqua"].to_numpy(dtype="float64")
    features["longitude"] = pairs["longitude_aqua"].to_numpy(dtype="float64")
    return features


def _fit_physics(
    y: np.ndarray,
    lst: np.ndarray,
    regions: np.ndarray | None,
    ridge_lambda: float = 0.0,
) -> dict[str, Any]:
    """Fit P (regions=None) or H (regional offsets, ridge-penalised)."""
    region_list = sorted(set(regions)) if regions is not None else []
    n_offsets = len(region_list)

    def residual(theta: np.ndarray) -> np.ndarray:
        c, t0, b, sigma = theta[:4]
        base = c + _g(lst, t0, b, sigma) - _g(
            np.asarray([REFERENCE_LST_H]), t0, b, sigma
        )[0]
        if n_offsets:
            offsets = theta[4:]
            index = {region: i for i, region in enumerate(region_list)}
            base = base + np.asarray([offsets[index[r]] for r in regions])
        resid = y - base
        if n_offsets and ridge_lambda:
            resid = np.concatenate(
                [resid, np.sqrt(ridge_lambda) * theta[4:]]
            )
        return resid

    initial = np.concatenate(
        [
            np.asarray([float(np.mean(y)), 14.0, 0.10, 1.5]),
            np.zeros(n_offsets),
        ]
    )
    lower = np.concatenate(
        [
            np.asarray([-3.0, 12.0, 1e-4, 0.2]),
            np.full(n_offsets, -3.0),
        ]
    )
    upper = np.concatenate(
        [
            np.asarray([3.0, 16.0, 0.999, 5.0]),
            np.full(n_offsets, 3.0),
        ]
    )
    solved = least_squares(
        residual,
        initial,
        bounds=(lower, upper),
        loss="soft_l1",
        f_scale=1.0,
        max_nfev=3000,
        xtol=1e-10,
        ftol=1e-10,
        gtol=1e-10,
    )
    params: dict[str, Any] = {
        "c": float(solved.x[0]),
        "t0": float(solved.x[1]),
        "b": float(solved.x[2]),
        "sigma": float(solved.x[3]),
    }
    if n_offsets:
        params["offsets"] = {
            region: float(solved.x[4 + i]) for i, region in enumerate(region_list)
        }
    params["fit"] = {
        "cost": float(solved.cost),
        "optimality": float(solved.optimality),
        "nfev": int(solved.nfev),
        "ridge_lambda": float(ridge_lambda),
    }
    return params


@dataclass
class ModelSet:
    """Fitted parameters for every model plus the pre-registered selection."""

    y_mean: float
    region_means: dict[str, float]
    p_params: dict[str, Any]
    h_params: dict[str, Any]
    m_model: GradientBoostingRegressor | None
    pr_residual_model: GradientBoostingRegressor | None
    region_weights: pd.Series | None = None
    feature_names: tuple[str, ...] = FEATURES
    selection: dict[str, Any] = field(default_factory=dict)

    def to_artifact(self) -> dict[str, Any]:
        return {
            "schema_version": "l5.model_artifact.v1",
            "y_mean": self.y_mean,
            "region_means": self.region_means,
            "p_params": self.p_params,
            "h_params": self.h_params,
            "m_model": self.m_model,
            "pr_residual_model": self.pr_residual_model,
            "feature_names": list(self.feature_names),
            "selection": self.selection,
        }


def _gbm() -> GradientBoostingRegressor:
    return GradientBoostingRegressor(
        n_estimators=220,
        max_depth=3,
        learning_rate=0.05,
        subsample=0.85,
        min_samples_leaf=8,
        random_state=42,
        loss="huber",
        alpha=0.9,
    )


def fit_models(
    pairs: pd.DataFrame,
    use_weights: bool = True,
    feature_names: tuple[str, ...] = FEATURES,
) -> ModelSet:
    """Fit B1/B2/P/H/M/PR on a training pair table.  B0 needs no fit."""
    y = pairs["y"].to_numpy(dtype="float64")
    regions = pairs["region"].astype(str).to_numpy()
    lst = pairs["lst_aqua"].to_numpy(dtype="float64")
    weights = (
        pd.to_numeric(pairs["fit_weight"], errors="coerce").fillna(1.0).to_numpy()
        if use_weights and "fit_weight" in pairs
        else np.ones(len(pairs))
    )

    y_mean = float(np.average(y, weights=weights))
    region_series = pd.Series(y).groupby(pd.Series(regions)).mean()
    region_means = {str(k): float(v) for k, v in region_series.items()}

    p_params = _fit_physics(y, lst, None)
    h_params = _fit_physics(y, lst, regions, ridge_lambda=RIDGE_LAMBDA)

    X = feature_frame(pairs).loc[:, list(feature_names)].to_numpy(dtype="float64")
    m_model = _gbm()
    m_model.fit(X, y, sample_weight=weights)

    p_for_residual = physics_prediction(lst, regions, p_params, use_offsets=False)
    pr_residual_model = _gbm()
    pr_residual_model.fit(X, y - p_for_residual, sample_weight=weights)

    return ModelSet(
        y_mean=y_mean,
        region_means=region_means,
        p_params=p_params,
        h_params=h_params,
        m_model=m_model,
        pr_residual_model=pr_residual_model,
        region_weights=pd.Series(weights, index=pairs.index),
        feature_names=feature_names,
    )


def predict_models(model_set: ModelSet, pairs: pd.DataFrame) -> dict[str, np.ndarray]:
    """Predict all seven models on a pair table.  B0 is the uncorrected y=0."""
    n = len(pairs)
    y = pairs["y"].to_numpy(dtype="float64")
    regions = pairs["region"].astype(str).to_numpy()
    lst = pairs["lst_aqua"].to_numpy(dtype="float64")
    X = feature_frame(pairs).loc[:, list(model_set.feature_names)].to_numpy(dtype="float64")

    b1 = np.full(n, model_set.y_mean)
    b2 = np.asarray(
        [model_set.region_means.get(str(region), model_set.y_mean) for region in regions]
    )
    p = physics_prediction(lst, regions, model_set.p_params, use_offsets=False)
    h = physics_prediction(lst, regions, model_set.h_params, use_offsets=True)
    m = model_set.m_model.predict(X) if model_set.m_model is not None else np.full(n, np.nan)
    pr = (
        p + model_set.pr_residual_model.predict(X)
        if model_set.pr_residual_model is not None
        else np.full(n, np.nan)
    )
    return {
        "B0": np.zeros(n),
        "B1": b1,
        "B2": b2,
        "P": p,
        "H": h,
        "M": m,
        "PR": pr,
    }


def residual_metrics(y: np.ndarray, prediction: np.ndarray) -> dict[str, float]:
    residual = np.asarray(y) - np.asarray(prediction)
    return {
        "rmse": float(np.sqrt(np.mean(np.square(residual)))),
        "bias": float(np.mean(residual)),
        "mae": float(np.mean(np.abs(residual))),
        "n": int(len(residual)),
    }


def conformal_quantile(residuals: np.ndarray, alpha: float = ALPHA) -> float:
    """Split-conformal quantile with the finite-sample correction."""
    residuals = np.sort(np.abs(np.asarray(residuals, dtype="float64")))
    n = len(residuals)
    if n == 0:
        return float("inf")
    rank = math.ceil((n + 1) * (1.0 - alpha))
    rank = min(max(rank, 1), n)
    return float(residuals[rank - 1])


def calibration_table(
    residuals: pd.Series,
    bins: pd.Series,
    alpha: float = ALPHA,
) -> dict[str, Any]:
    """Conformal quantiles by pre-registered delay bin, with pooled fallback."""
    absolute = residuals.abs()
    pooled = conformal_quantile(absolute.to_numpy(), alpha)
    rows: list[dict[str, Any]] = []
    for label in DELAY_BIN_LABELS:
        mask = (bins == label).to_numpy()
        values = absolute.to_numpy()[mask]
        n = int(len(values))
        q = conformal_quantile(values, alpha) if n >= MIN_CALIBRATION_PAIRS else pooled
        rows.append(
            {
                "bin": label,
                "n": n,
                "quantile": q,
                "fallback_pooled": n < MIN_CALIBRATION_PAIRS,
                "width_factor": float(np.exp(q)),
                "median_width_factor": float(np.exp(np.median(np.abs(values)))) if n else None,
            }
        )
    return {
        "alpha": alpha,
        "nominal_coverage": 1.0 - alpha,
        "pooled_quantile": pooled,
        "bins": {row["bin"]: row for row in rows},
        "bin_order": list(DELAY_BIN_LABELS),
    }


def coverage_table(
    residuals: pd.Series,
    bins: pd.Series,
    quantiles: dict[str, float],
    alpha: float = ALPHA,
) -> dict[str, Any]:
    """Empirical coverage of fixed conformal quantiles (in-sample diagnostic)."""
    absolute = residuals.abs().to_numpy()
    rows: list[dict[str, Any]] = []
    covered_total = 0
    n_total = 0
    for label in DELAY_BIN_LABELS:
        mask = (bins == label).to_numpy()
        values = absolute[mask]
        q = quantiles[label]
        covered = int((values <= q).sum())
        n = int(len(values))
        covered_total += covered
        n_total += n
        rows.append(
            {
                "bin": label,
                "n": n,
                "covered": covered,
                "coverage": (covered / n) if n else None,
                "quantile": q,
            }
        )
    return {
        "overall_coverage": (covered_total / n_total) if n_total else None,
        "n": n_total,
        "bins": {row["bin"]: row for row in rows},
    }


def nested_conformal_coverage(
    residuals: pd.Series,
    bins: pd.Series,
    blocks: pd.Series,
    alpha: float = ALPHA,
) -> dict[str, Any]:
    """Honest coverage: quantile fitted without the evaluated block.

    For each block and delay bin, the quantile is calibrated on out-of-fold
    residuals from every *other* block.  This prevents the coverage estimate
    from being evaluated on the same residuals that set the interval width.
    """
    absolute = residuals.abs().to_numpy()
    bin_values = bins.astype("string").to_numpy()
    block_values = blocks.astype("string").to_numpy()
    block_list = list(pd.unique(block_values))
    rows: list[dict[str, Any]] = []
    total_covered = 0
    total_n = 0

    for label in DELAY_BIN_LABELS:
        in_bin = bin_values == label
        covered = 0
        n = 0
        for block in block_list:
            evaluate = in_bin & (block_values == block)
            evaluate_n = int(evaluate.sum())
            if evaluate_n == 0:
                continue
            calibration = in_bin & (block_values != block)
            calibration_values = absolute[calibration]
            if len(calibration_values) < MIN_CALIBRATION_PAIRS:
                calibration_values = absolute[block_values != block]
            if len(calibration_values) == 0:
                continue
            q = conformal_quantile(calibration_values, alpha)
            covered += int((absolute[evaluate] <= q).sum())
            n += evaluate_n
        total_covered += covered
        total_n += n
        rows.append(
            {
                "bin": label,
                "n": n,
                "covered": covered,
                "coverage": (covered / n) if n else None,
            }
        )
    return {
        "overall_coverage": (total_covered / total_n) if total_n else None,
        "n": total_n,
        "bins": {row["bin"]: row for row in rows},
    }


def build_gate(
    calibration: dict[str, Any],
    nested_coverage: dict[str, Any],
    training_pairs: pd.DataFrame,
) -> dict[str, Any]:
    """Pre-registered applicability gate, plus the measured domain bounds."""
    scan_low = float(training_pairs["scan_aqua"].quantile(0.01))
    scan_high = float(training_pairs["scan_aqua"].quantile(0.99))
    delay_low = float(training_pairs["delay_ref"].quantile(0.01))
    delay_high = float(training_pairs["delay_ref"].quantile(0.99))
    regions = sorted(training_pairs["region"].astype(str).unique())
    bins: dict[str, Any] = {}
    for label in DELAY_BIN_LABELS:
        cal = calibration["bins"][label]
        cover = nested_coverage["bins"][label]
        n = int(cal["n"])
        coverage = cover["coverage"]
        applicable = (
            n >= MIN_CALIBRATION_PAIRS
            and coverage is not None
            and coverage >= COVERAGE_FLOOR
        )
        reason = None
        if n < MIN_CALIBRATION_PAIRS:
            reason = "insufficient_calibration_pairs"
        elif coverage is None or coverage < COVERAGE_FLOOR:
            reason = "coverage_below_floor"
        bins[label] = {
            "bin": label,
            "calibration_n": n,
            "coverage": coverage,
            "quantile": float(cal["quantile"]),
            "fallback_pooled": bool(cal["fallback_pooled"]),
            "applicable": bool(applicable),
            "reason": reason,
        }
    return {
        "alpha": ALPHA,
        "nominal_coverage": NOMINAL_COVERAGE,
        "min_calibration_pairs": MIN_CALIBRATION_PAIRS,
        "coverage_floor": COVERAGE_FLOOR,
        "bins": bins,
        "domain": {
            "delay_low": delay_low,
            "delay_high": delay_high,
            "scan_low": scan_low,
            "scan_high": scan_high,
            "regions": regions,
        },
    }


def predict_harmonized(
    cells: pd.DataFrame,
    artifact: dict[str, Any],
    model_id: str = "H",
) -> pd.DataFrame:
    """Apply the served model, interval lookup and gate to cell-days.

    ``cells`` columns: region, lst_aqua, frp_sum_aqua, n_aqua, scan_aqua,
    area_ratio_aqua, latitude, longitude.  Returns one row per input with
    nullable harmonized FRP and a reason when refused.
    """
    n = len(cells)
    regions = cells["region"].astype(str).to_numpy()
    lst = cells["lst_aqua"].to_numpy(dtype="float64")
    y_hat = physics_prediction(
        lst, regions, artifact["h_params"] if model_id == "H" else artifact["p_params"],
        use_offsets=(model_id == "H"),
    )
    bins = delay_bin(pd.Series(cells["delay_ref"].to_numpy(dtype="float64")))
    gate = artifact["gate"]
    calibration = artifact["conformal"]
    domain = gate["domain"]

    harmonized = cells["frp_sum_aqua"].to_numpy(dtype="float64") * np.exp(-y_hat)
    q = np.empty(n, dtype="float64")
    calibrated = np.zeros(n, dtype=bool)
    reasons = np.full(n, None, dtype=object)
    for i, label in enumerate(bins.to_numpy()):
        if label is None or pd.isna(label):
            reasons[i] = "delay_outside_calibrated_range"
            q[i] = calibration["pooled_quantile"]
            continue
        q[i] = calibration["bins"][str(label)]["quantile"]
        calibrated[i] = bool(gate["bins"][str(label)]["applicable"])
    lower = harmonized * np.exp(-q)
    upper = harmonized * np.exp(q)

    scan = cells["scan_aqua"].to_numpy(dtype="float64")
    delay = cells["delay_ref"].to_numpy(dtype="float64")
    known_region = np.isin(regions, domain["regions"])
    delay_in_domain = (delay >= domain["delay_low"]) & (delay <= domain["delay_high"])
    scan_in_domain = (scan >= domain["scan_low"]) & (scan <= domain["scan_high"])

    for i in range(n):
        if reasons[i] is not None:
            continue
        label = str(bins.iloc[i])
        if not known_region[i]:
            reasons[i] = "region_not_in_training"
        elif not delay_in_domain[i]:
            reasons[i] = "delay_outside_calibrated_range"
        elif not scan_in_domain[i]:
            reasons[i] = "scan_out_of_range"
        elif not calibrated[i]:
            reasons[i] = gate["bins"][label]["reason"]
        elif gate["bins"][label]["calibration_n"] < MIN_CALIBRATION_PAIRS:
            reasons[i] = "insufficient_calibration_pairs"

    applicable = np.asarray([reason is None for reason in reasons])
    return pd.DataFrame(
        {
            "region": regions,
            "delay_h": delay,
            "predicted_log_ratio": y_hat,
            "harmonized_frp_mw": np.where(applicable, harmonized, np.nan),
            "interval_lower_mw": np.where(applicable, lower, np.nan),
            "interval_upper_mw": np.where(applicable, upper, np.nan),
            "interval_width_mw": np.where(applicable, upper - lower, np.nan),
            "applicable": applicable,
            "reason": reasons,
            "delay_bin": bins.to_numpy(),
            "scan_in_domain": scan_in_domain,
            "delay_in_domain": delay_in_domain,
        }
    )
