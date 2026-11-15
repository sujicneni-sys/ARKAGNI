"""L5 core - pure, array-vectorised FRP harmonization science.

Hard contract
-------------
This module performs **no file reads, no network calls, no clock access and no
mutable global state**.  The identical functions are used by batch fitting,
the L4 audit engine and the L6 FastAPI service.  All operations are vectorised
over cell-day arrays; there is no per-row Python in ``harmonize``.

Scientific unit
---------------
One element is one 1-degree cell-day for one satellite.  The response is a
log-ratio correction::

    y = ln(FRP_Aqua / FRP_SNPP)
    y_hat = c + g(t_Aqua) - g(13.6) + regional_offset      (model H)
    FRP_harmonized = FRP_Aqua * exp(-y_hat)

The 80% interval is split-conformal by pre-registered delay bin.  The
applicability gate refuses a cell when calibration support or out-of-fold
coverage is insufficient, or when the input lies outside the measured domain.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Frozen constants (the config hash covers the scientific values)
# ---------------------------------------------------------------------------

MODEL_IDS: tuple[str, ...] = ("B0", "B1", "B2", "P", "H", "M", "PR")

MODEL_LABELS: dict[str, str] = {
    "B0": "Raw baseline",
    "B1": "Global mean correction",
    "B2": "Regional mean correction",
    "P": "Physics diurnal model",
    "H": "Physics + regional offsets (served)",
    "M": "Gradient boosting",
    "PR": "Physics + boosted residual",
}

FEATURES: tuple[str, ...] = (
    "ln_frp_aqua",
    "delay_ref",
    "ln_area_aqua",
    "ln_n_aqua",
    "latitude",
    "longitude",
)

REFERENCE_LST_H = 13.6
DELAY_BIN_EDGES: tuple[float, ...] = (-3.0, 0.0, 0.5, 1.0, 1.5, 2.0, 3.5)
DELAY_BIN_LABELS: tuple[str, ...] = (
    "(-3, 0]",
    "(0, 0.5]",
    "(0.5, 1]",
    "(1, 1.5]",
    "(1.5, 2]",
    "(2, 3.5]",
)

ALPHA = 0.20
NOMINAL_COVERAGE = 1.0 - ALPHA
MIN_CALIBRATION_PAIRS = 40
COVERAGE_FLOOR = 0.70
MAX_CELLS = 100_000

# Pixel flag contract.  A pixel is never deleted; the bitmask preserves the
# count of every rule that fired.  Bits 3-7 are reserved for saturation,
# plume scattering and canopy occlusion and remain zero until metadata exists.
FLAG_TYPE_NOT_0 = 1 << 0
FLAG_FRP_NOT_POSITIVE = 1 << 1
FLAG_NIGHT = 1 << 2
EXCLUDE_MASK = FLAG_TYPE_NOT_0 | FLAG_FRP_NOT_POSITIVE | FLAG_NIGHT
FLAG_NAMES: tuple[str, ...] = (
    "type_not_0",
    "frp_not_above_zero",
    "night",
    "saturation_not_evaluated",
    "plume_not_evaluated",
    "canopy_not_evaluated",
)

SUPPORTED_REFUSALS: tuple[str, ...] = (
    "insufficient_calibration_pairs",
    "coverage_below_floor",
    "delay_outside_calibrated_range",
    "scan_out_of_range",
    "region_not_in_training",
)


# ---------------------------------------------------------------------------
# Small vector helpers
# ---------------------------------------------------------------------------


def _array(value: Any, dtype: str = "float64", name: str = "value") -> np.ndarray:
    array = np.asarray(value, dtype=dtype)
    if array.ndim == 0:
        array = array.reshape(1)
    if array.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    return array


def _get(cells: Mapping[str, Any] | pd.DataFrame, key: str, default: Any = None) -> Any:
    if isinstance(cells, pd.DataFrame):
        if key in cells.columns:
            return cells[key].to_numpy()
        if default is None:
            raise KeyError(key)
        return default
    if key in cells:
        return cells[key]
    if default is None:
        raise KeyError(key)
    return default


def utc_hours_from_hhmm(values: Any) -> np.ndarray:
    """Parse zero-padded HHMM values without ever reading ``118`` as 11:08.

    Strings are left-zero-padded to four characters.  Numeric values are
    converted through their decimal representation and zero-padded identically.
    """
    series = pd.Series(values, dtype="object")
    text = series.astype("string").str.replace(r"\.0$", "", regex=True).str.zfill(4)
    hour = pd.to_numeric(text.str.slice(0, 2), errors="coerce")
    minute = pd.to_numeric(text.str.slice(2, 4), errors="coerce")
    result = (hour + minute / 60.0).to_numpy(dtype="float64")
    return result


def lst_to_hhmm_int(hours: Any) -> np.ndarray:
    """Store Local Solar Time as a zero-padded integer, e.g. 01:18 -> 118."""
    values = _array(hours, "float64", "hours")
    wrapped = np.mod(values, 24.0)
    rounded = np.rint(wrapped * 60.0).astype(np.int64) % (24 * 60)
    return (rounded // 60) * 100 + (rounded % 60)


def format_lst(hours: Any) -> list[str]:
    """Render Local Solar Time as ``HH:MM``; never show the padded integer."""
    values = _array(hours, "float64", "hours")
    stored = lst_to_hhmm_int(values)
    return [f"{int(value) // 100:02d}:{int(value) % 100:02d}" for value in stored]


def local_solar_time(utc_hours: Any, longitude: Any) -> np.ndarray:
    """``lst = (UTC hours + longitude / 15) mod 24``."""
    utc = _array(utc_hours, "float64", "utc_hours")
    lon = _array(longitude, "float64", "longitude")
    if utc.shape != lon.shape:
        utc, lon = np.broadcast_arrays(utc, lon)
    return np.mod(utc + lon / 15.0, 24.0)


def snap_coordinate(value: Any, axis: str = "latitude") -> np.ndarray:
    """Snap coordinates to the 1-degree cell index used by the models."""
    values = _array(value, "float64", axis)
    if axis == "latitude":
        lower, upper = -90.0, 90.0
    elif axis == "longitude":
        lower, upper = -180.0, 180.0
    else:  # pragma: no cover - defensive
        raise ValueError("axis must be 'latitude' or 'longitude'")
    if np.any(~np.isfinite(values)):
        raise ValueError(f"{axis} contains non-finite values")
    if np.any((values < lower) | (values > upper)):
        raise ValueError(f"{axis} must lie in [{lower:g}, {upper:g}]")
    return np.floor(values).astype(np.int32)


def cell_label(cell_lat: Any, cell_lon: Any) -> list[str]:
    """Human-readable 1-degree label, e.g. ``S13E025``.

    Vectorised so the 1.38M-row explorer never pays a Python loop.
    """
    lat = _array(cell_lat, "int64", "cell_lat")
    lon = _array(cell_lon, "int64", "cell_lon")
    if lat.shape != lon.shape:
        lat, lon = np.broadcast_arrays(lat, lon)
    lat_sign = np.where(lat >= 0, "N", "S").astype(object)
    lon_sign = np.where(lon >= 0, "E", "W").astype(object)
    lat_digits = pd.Series(np.abs(lat)).astype("string").str.zfill(2).to_numpy(dtype=object)
    lon_digits = pd.Series(np.abs(lon)).astype("string").str.zfill(3).to_numpy(dtype=object)
    return (lat_sign + lat_digits + lon_sign + lon_digits).tolist()


def pixel_flags(
    detection_type: Any,
    frp: Any,
    daynight: Any,
) -> np.ndarray:
    """Build the uint8 pixel flag bitmask.  No row is deleted."""
    types = pd.Series(detection_type, dtype="object").astype("string").str.strip()
    frp_values = pd.to_numeric(pd.Series(frp), errors="coerce").to_numpy(dtype="float64")
    night_values = pd.Series(daynight, dtype="object").astype("string").str.strip().str.upper()
    type_bad = (types != "0").to_numpy(dtype=bool)
    frp_bad = ~np.isfinite(frp_values) | (frp_values <= 0.0)
    night = (night_values != "D").to_numpy(dtype=bool)
    flags = np.zeros(len(frp_values), dtype=np.uint8)
    flags |= type_bad.astype(np.uint8) * FLAG_TYPE_NOT_0
    flags |= frp_bad.astype(np.uint8) * FLAG_FRP_NOT_POSITIVE
    flags |= night.astype(np.uint8) * FLAG_NIGHT
    return flags


def flag_counts(flags: Any) -> dict[str, int]:
    values = _array(flags, "uint8", "flags")
    return {
        name: int(((values & (1 << bit)) != 0).sum())
        for bit, name in enumerate(FLAG_NAMES[:3])
    }


def validated_mask(flags: Any) -> np.ndarray:
    return (_array(flags, "uint8", "flags") & EXCLUDE_MASK) == 0


# ---------------------------------------------------------------------------
# Delay binning
# ---------------------------------------------------------------------------


def assign_delay_bin(delay_h: Any) -> np.ndarray:
    """Assign pre-registered delay bins using ``pd.cut`` semantics.

    Bins are right-closed, the lowest edge is inclusive, and values outside
    ``[-3.0, 3.5]`` receive ``None``.  The result is an object array so JSON
    serialisation is unambiguous.
    """
    values = _array(delay_h, "float64", "delay_h")
    n = len(values)
    labels = np.full(n, None, dtype=object)
    valid = np.isfinite(values) & (values >= DELAY_BIN_EDGES[0]) & (values <= DELAY_BIN_EDGES[-1])
    if not valid.any():
        return labels
    index = np.searchsorted(np.asarray(DELAY_BIN_EDGES), values[valid], side="left") - 1
    # include_lowest=True: the exact lower edge belongs to the first bin.
    index = np.where(values[valid] == DELAY_BIN_EDGES[0], 0, index)
    index = np.clip(index, 0, len(DELAY_BIN_LABELS) - 1)
    labels[valid] = np.asarray(DELAY_BIN_LABELS, dtype=object)[index]
    return labels


def delay_bin_series(delay_h: Any) -> pd.Series:
    """Pandas-shaped wrapper for audit and reporting code."""
    return pd.Series(assign_delay_bin(delay_h), dtype="string")


# ---------------------------------------------------------------------------
# Model evaluators B0..PR
# ---------------------------------------------------------------------------


def _diurnal_shape(
    t: Any,
    t0: float,
    b: float,
    sigma: float,
) -> np.ndarray:
    values = _array(t, "float64", "lst")
    b_clipped = float(np.clip(b, 1e-6, 1.0 - 1e-6))
    sigma_safe = max(float(sigma), 1e-6)
    exponent = -np.square(values - float(t0)) / (2.0 * sigma_safe * sigma_safe)
    inside = b_clipped + (1.0 - b_clipped) * np.exp(exponent)
    return np.log(np.clip(inside, 1e-12, None))


def physics_prediction(
    lst: Any,
    regions: Any,
    params: Mapping[str, Any],
    use_offsets: bool = False,
    reference_lst_h: float = REFERENCE_LST_H,
) -> np.ndarray:
    """P or H prediction: ``c + g(t) - g(13.6) + optional regional offsets``."""
    t = _array(lst, "float64", "lst")
    region_values = pd.Series(regions, dtype="object").astype(str).to_numpy()
    prediction = (
        float(params["c"])
        + _diurnal_shape(t, float(params["t0"]), float(params["b"]), float(params["sigma"]))
        - _diurnal_shape(
            np.asarray([reference_lst_h]),
            float(params["t0"]),
            float(params["b"]),
            float(params["sigma"]),
        )[0]
    )
    if use_offsets:
        offsets = params.get("offsets", {}) or {}
        adjustment = pd.Series(region_values).map(offsets).fillna(0.0).to_numpy(dtype="float64")
        prediction = prediction + adjustment
    return prediction


def feature_matrix(cells: Mapping[str, Any] | pd.DataFrame, feature_names: Sequence[str] = FEATURES) -> np.ndarray:
    """Aqua-side feature matrix.  No reference-sensor value is used."""
    frp = pd.to_numeric(pd.Series(_get(cells, "frp_sum_aqua")), errors="coerce").to_numpy(dtype="float64")
    lst = pd.to_numeric(pd.Series(_get(cells, "lst_aqua")), errors="coerce").to_numpy(dtype="float64")
    scan = pd.to_numeric(pd.Series(_get(cells, "scan_aqua", np.ones(len(frp)))), errors="coerce").to_numpy(dtype="float64")
    area = pd.to_numeric(
        pd.Series(_get(cells, "area_ratio_aqua", scan)), errors="coerce"
    ).to_numpy(dtype="float64")
    count = pd.to_numeric(
        pd.Series(_get(cells, "n_aqua", np.ones(len(frp)))), errors="coerce"
    ).to_numpy(dtype="float64")
    latitude = pd.to_numeric(
        pd.Series(_get(cells, "latitude_aqua", np.zeros(len(frp)))), errors="coerce"
    ).to_numpy(dtype="float64")
    longitude = pd.to_numeric(
        pd.Series(_get(cells, "longitude_aqua", np.zeros(len(frp)))), errors="coerce"
    ).to_numpy(dtype="float64")
    delay = lst - REFERENCE_LST_H
    computed = {
        "ln_frp_aqua": np.log(np.clip(frp, 1e-12, None)),
        "delay_ref": delay,
        "ln_area_aqua": np.log(np.clip(area, 1e-12, None)),
        "ln_n_aqua": np.log(np.clip(count, 1.0, None)),
        "latitude": latitude,
        "longitude": longitude,
    }
    missing = [name for name in feature_names if name not in computed]
    if missing:
        raise ValueError(f"artifact requests unsupported features: {missing}")
    return np.column_stack([computed[name] for name in feature_names])


def predict_models(
    cells: Mapping[str, Any] | pd.DataFrame,
    artifact: Mapping[str, Any],
) -> dict[str, np.ndarray]:
    """Evaluate all seven model families on the same cell-day inputs."""
    n = len(_array(_get(cells, "frp_sum_aqua"), "float64", "frp_sum_aqua"))
    regions = pd.Series(_get(cells, "region"), dtype="object").astype(str).to_numpy()
    lst = pd.to_numeric(pd.Series(_get(cells, "lst_aqua")), errors="coerce").to_numpy(dtype="float64")
    features = feature_matrix(cells, tuple(artifact.get("feature_names", FEATURES)))

    b0 = np.zeros(n, dtype="float64")
    b1 = np.full(n, float(artifact["y_mean"]), dtype="float64")
    region_means = artifact.get("region_means", {}) or {}
    b2 = pd.Series(regions).map(region_means).fillna(float(artifact["y_mean"])).to_numpy(dtype="float64")
    p = physics_prediction(lst, regions, artifact["p_params"], use_offsets=False)
    h = physics_prediction(lst, regions, artifact["h_params"], use_offsets=True)

    m_model = artifact.get("m_model")
    if m_model is None:
        m = np.full(n, np.nan, dtype="float64")
    else:
        m = np.asarray(m_model.predict(features), dtype="float64")

    pr_model = artifact.get("pr_residual_model")
    if pr_model is None:
        pr = np.full(n, np.nan, dtype="float64")
    else:
        pr = p + np.asarray(pr_model.predict(features), dtype="float64")

    return {"B0": b0, "B1": b1, "B2": b2, "P": p, "H": h, "M": m, "PR": pr}


def model_log_ratio(
    cells: Mapping[str, Any] | pd.DataFrame,
    artifact: Mapping[str, Any],
    model_id: str = "H",
) -> np.ndarray:
    if model_id not in MODEL_IDS:
        raise ValueError(f"unknown model_id={model_id!r}; expected one of {MODEL_IDS}")
    return predict_models(cells, artifact)[model_id]


# ---------------------------------------------------------------------------
# Conformal calibration and applicability gate
# ---------------------------------------------------------------------------


def conformal_quantile(residuals: Any, alpha: float = ALPHA) -> float:
    """Split-conformal quantile with the finite-sample rank correction."""
    absolute = np.sort(np.abs(_array(residuals, "float64", "residuals")))
    n = len(absolute)
    if n == 0:
        return float("inf")
    rank = math.ceil((n + 1) * (1.0 - alpha))
    rank = min(max(rank, 1), n)
    return float(absolute[rank - 1])


def calibration_table(
    residuals: Any,
    bins: Any,
    alpha: float = ALPHA,
    min_pairs: int = MIN_CALIBRATION_PAIRS,
) -> dict[str, Any]:
    """Conformal quantile per delay bin, with pooled fallback for thin bins."""
    absolute = np.abs(_array(residuals, "float64", "residuals"))
    labels = np.asarray(bins, dtype=object)
    pooled = conformal_quantile(absolute, alpha)
    rows: dict[str, Any] = {}
    for label in DELAY_BIN_LABELS:
        mask = labels == label
        values = absolute[mask]
        n = int(len(values))
        quantile = conformal_quantile(values, alpha) if n >= min_pairs else pooled
        rows[label] = {
            "bin": label,
            "n": n,
            "quantile": quantile,
            "fallback_pooled": n < min_pairs,
            "width_factor": float(np.exp(quantile)),
            "median_width_factor": float(np.exp(np.median(values))) if n else None,
        }
    return {
        "alpha": alpha,
        "nominal_coverage": 1.0 - alpha,
        "pooled_quantile": pooled,
        "bins": rows,
        "bin_order": list(DELAY_BIN_LABELS),
    }


def coverage_table(
    residuals: Any,
    bins: Any,
    quantiles: Mapping[str, float],
    alpha: float = ALPHA,
) -> dict[str, Any]:
    absolute = np.abs(_array(residuals, "float64", "residuals"))
    labels = np.asarray(bins, dtype=object)
    rows: dict[str, Any] = {}
    covered_total = 0
    n_total = 0
    for label in DELAY_BIN_LABELS:
        mask = labels == label
        values = absolute[mask]
        quantile = float(quantiles[label])
        covered = int((values <= quantile).sum())
        n = int(len(values))
        covered_total += covered
        n_total += n
        rows[label] = {
            "bin": label,
            "n": n,
            "covered": covered,
            "coverage": (covered / n) if n else None,
            "quantile": quantile,
        }
    return {
        "alpha": alpha,
        "nominal_coverage": 1.0 - alpha,
        "overall_coverage": (covered_total / n_total) if n_total else None,
        "n": n_total,
        "bins": rows,
    }


def build_gate(
    calibration: Mapping[str, Any],
    nested_coverage: Mapping[str, Any],
    domain: Mapping[str, Any],
    min_pairs: int = MIN_CALIBRATION_PAIRS,
    coverage_floor: float = COVERAGE_FLOOR,
) -> dict[str, Any]:
    """Pre-registered gate: >=40 pairs and >=0.70 honest coverage per bin."""
    bins: dict[str, Any] = {}
    for label in DELAY_BIN_LABELS:
        cal = calibration["bins"][label]
        cover = nested_coverage["bins"][label]
        n = int(cal["n"])
        coverage = cover["coverage"]
        applicable = bool(
            n >= min_pairs
            and coverage is not None
            and coverage >= coverage_floor
        )
        reason = None
        if n < min_pairs:
            reason = "insufficient_calibration_pairs"
        elif coverage is None or coverage < coverage_floor:
            reason = "coverage_below_floor"
        bins[label] = {
            "bin": label,
            "calibration_n": n,
            "coverage": coverage,
            "quantile": float(cal["quantile"]),
            "fallback_pooled": bool(cal["fallback_pooled"]),
            "applicable": applicable,
            "reason": reason,
        }
    return {
        "alpha": float(calibration["alpha"]),
        "nominal_coverage": float(calibration["nominal_coverage"]),
        "min_calibration_pairs": int(min_pairs),
        "coverage_floor": float(coverage_floor),
        "bins": bins,
        "domain": dict(domain),
    }


def interval_from_quantile(point_mw: Any, quantile: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    point = _array(point_mw, "float64", "point_mw")
    q = _array(quantile, "float64", "quantile")
    if point.shape != q.shape:
        point, q = np.broadcast_arrays(point, q)
    lower = point * np.exp(-q)
    upper = point * np.exp(q)
    return lower, upper, upper - lower


# ---------------------------------------------------------------------------
# Primary harmonization surface
# ---------------------------------------------------------------------------


def harmonize(
    frp_aqua_mw: Any,
    lst_aqua_h: Any,
    region: Any,
    scan_aqua: Any,
    artifact: Mapping[str, Any],
    model_id: str = "H",
    detections: Any | None = None,
    area_ratio: Any | None = None,
    latitude: Any | None = None,
    longitude: Any | None = None,
) -> dict[str, np.ndarray]:
    """Vectorised harmonization: arrays in, arrays out.

    Parameters are one-dimensional arrays of equal length.  The returned
    dictionary contains the point estimate, the 80% conformal interval, the
    applicability verdict and a machine-readable refusal code.  Refused cells
    carry ``NaN`` in all predictive fields - never an imputed number.
    """
    frp = _array(frp_aqua_mw, "float64", "frp_aqua_mw")
    n = len(frp)
    lst = _array(lst_aqua_h, "float64", "lst_aqua_h")
    regions = pd.Series(region, dtype="object").astype(str).to_numpy()
    scan = _array(scan_aqua, "float64", "scan_aqua")
    if not (len(lst) == len(regions) == len(scan) == n):
        raise ValueError("all input arrays must have the same length")
    if n == 0:
        raise ValueError("at least one cell is required")
    if n > MAX_CELLS:
        raise ValueError(f"request exceeds the {MAX_CELLS:,}-cell cap")

    count = np.ones(n, dtype="float64") if detections is None else _array(detections, "float64", "detections")
    area = scan.copy() if area_ratio is None else _array(area_ratio, "float64", "area_ratio")
    lat = np.zeros(n, dtype="float64") if latitude is None else _array(latitude, "float64", "latitude")
    lon = np.zeros(n, dtype="float64") if longitude is None else _array(longitude, "float64", "longitude")

    cells: dict[str, Any] = {
        "frp_sum_aqua": frp,
        "lst_aqua": lst,
        "region": regions,
        "scan_aqua": scan,
        "area_ratio_aqua": area,
        "n_aqua": count,
        "latitude_aqua": lat,
        "longitude_aqua": lon,
        "delay_ref": lst - REFERENCE_LST_H,
    }

    y_hat = model_log_ratio(cells, artifact, model_id=model_id)
    delay = cells["delay_ref"]
    bins = assign_delay_bin(delay)
    gate = artifact["gate"]
    calibration = artifact["conformal"]
    domain = gate["domain"]

    quantile = np.full(n, float(calibration["pooled_quantile"]), dtype="float64")
    calibration_n = np.zeros(n, dtype="int64")
    coverage = np.full(n, np.nan, dtype="float64")
    bin_applicable = np.zeros(n, dtype=bool)
    bin_reason = np.full(n, None, dtype=object)

    for label in DELAY_BIN_LABELS:
        mask = bins == label
        if not mask.any():
            continue
        quantile[mask] = float(calibration["bins"][label]["quantile"])
        calibration_n[mask] = int(gate["bins"][label]["calibration_n"])
        cov = gate["bins"][label]["coverage"]
        coverage[mask] = np.nan if cov is None else float(cov)
        bin_applicable[mask] = bool(gate["bins"][label]["applicable"])
        bin_reason[mask] = gate["bins"][label]["reason"]

    known_region = np.isin(regions, np.asarray(domain["regions"], dtype=object))
    delay_in_domain = (delay >= float(domain["delay_low"])) & (delay <= float(domain["delay_high"]))
    scan_in_domain = (scan >= float(domain["scan_low"])) & (scan <= float(domain["scan_high"]))
    valid_bin = bins != None  # noqa: E711 - object array membership

    reasons = np.full(n, None, dtype=object)
    reasons[~valid_bin] = "delay_outside_calibrated_range"

    open_mask = reasons == None  # noqa: E711 - object array membership
    mask = open_mask & ~known_region
    reasons[mask] = "region_not_in_training"

    open_mask = reasons == None  # noqa: E711
    mask = open_mask & ~delay_in_domain
    reasons[mask] = "delay_outside_calibrated_range"

    open_mask = reasons == None  # noqa: E711
    mask = open_mask & ~scan_in_domain
    reasons[mask] = "scan_out_of_range"

    open_mask = reasons == None  # noqa: E711
    mask = open_mask & ~bin_applicable
    reasons[mask] = bin_reason[mask]

    open_mask = reasons == None  # noqa: E711
    mask = open_mask & (calibration_n < MIN_CALIBRATION_PAIRS)
    reasons[mask] = "insufficient_calibration_pairs"

    applicable = reasons == None  # noqa: E711
    harmonized = frp * np.exp(-y_hat)
    lower, upper, width = interval_from_quantile(harmonized, quantile)

    return {
        "region": regions,
        "delay_h": delay,
        "delay_bin": bins,
        "predicted_log_ratio": y_hat,
        "harmonized_frp_mw": np.where(applicable, harmonized, np.nan),
        "interval_lower_mw": np.where(applicable, lower, np.nan),
        "interval_upper_mw": np.where(applicable, upper, np.nan),
        "interval_width_mw": np.where(applicable, width, np.nan),
        "quantile": np.where(applicable, quantile, np.nan),
        "calibration_n": calibration_n,
        "coverage": coverage,
        "applicable": applicable,
        "reason": reasons,
        "scan_in_domain": scan_in_domain,
        "delay_in_domain": delay_in_domain,
        "region_in_domain": known_region,
        "refusal_codes": np.asarray(SUPPORTED_REFUSALS, dtype=object),
    }


def harmonize_frame(
    cells: pd.DataFrame,
    artifact: Mapping[str, Any],
    model_id: str = "H",
) -> pd.DataFrame:
    """DataFrame adapter around :func:`harmonize` for batch and audit paths."""
    output = harmonize(
        frp_aqua_mw=cells["frp_sum_aqua"].to_numpy(),
        lst_aqua_h=cells["lst_aqua"].to_numpy(),
        region=cells["region"].astype(str).to_numpy(),
        scan_aqua=cells["scan_aqua"].to_numpy(),
        artifact=artifact,
        model_id=model_id,
        detections=cells["n_aqua"].to_numpy() if "n_aqua" in cells else None,
        area_ratio=cells["area_ratio_aqua"].to_numpy() if "area_ratio_aqua" in cells else None,
        latitude=cells["latitude_aqua"].to_numpy() if "latitude_aqua" in cells else None,
        longitude=cells["longitude_aqua"].to_numpy() if "longitude_aqua" in cells else None,
    )
    frame = cells.reset_index(drop=True).copy()
    for key in (
        "delay_h",
        "delay_bin",
        "predicted_log_ratio",
        "harmonized_frp_mw",
        "interval_lower_mw",
        "interval_upper_mw",
        "interval_width_mw",
        "quantile",
        "calibration_n",
        "coverage",
        "applicable",
        "reason",
        "scan_in_domain",
        "delay_in_domain",
        "region_in_domain",
    ):
        frame[key] = output[key]
    return frame


# Backward-compatible name used by the analysis and audit modules.
def predict_harmonized(
    cells: pd.DataFrame,
    artifact: Mapping[str, Any],
    model_id: str = "H",
) -> pd.DataFrame:
    return harmonize_frame(cells, artifact, model_id=model_id)


def residual_metrics(y: Any, prediction: Any) -> dict[str, float]:
    observed = _array(y, "float64", "y")
    predicted = _array(prediction, "float64", "prediction")
    residual = observed - predicted
    return {
        "rmse": float(np.sqrt(np.mean(np.square(residual)))),
        "bias": float(np.mean(residual)),
        "mae": float(np.mean(np.abs(residual))),
        "n": int(len(residual)),
    }
