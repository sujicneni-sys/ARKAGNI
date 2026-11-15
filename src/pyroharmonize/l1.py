"""L1: canonicalization rules and independent cleaning reproduction.

Two separate operations live here:

1. ``reproduce_cleaning`` re-derives the supplied cleaned files from the raw
   FIRMS files using documented, explicit rules. It is a cross-check, not the
   authority.
2. ``build_canonical_frame`` types the frozen cleaned baseline and adds
   explicit validity fields. The cleaned files remain the L1 authority.

No function in this module writes to disk or modifies input data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Column contracts (measured from the frozen baseline, 2026-11-09)
# ---------------------------------------------------------------------------

# The three cleaned files share 19 raw columns and 10 derived columns, but the
# raw brightness column names differ by sensor. These tuples are the exact
# column order of each frozen cleaned file.
CLEANED_COLUMNS: dict[str, tuple[str, ...]] = {
    "MODIS": (
        "latitude",
        "longitude",
        "brightness",
        "scan",
        "track",
        "acq_date",
        "acq_time",
        "satellite",
        "instrument",
        "confidence",
        "version",
        "bright_t31",
        "frp",
        "daynight",
        "type",
        "source_product",
        "sampling_region",
        "sample_window_start",
        "sample_window_days",
        "confidence_raw",
        "quality_flag_invalid_frp",
        "quality_flag_invalid_scan_track",
        "brightness_temperature_primary_k",
        "brightness_temperature_secondary_k",
        "brightness_primary_source",
        "confidence_encoding",
        "acquisition_date",
        "acquisition_time_utc",
        "observation_id",
    ),
    "VIIRS_SNPP": (
        "latitude",
        "longitude",
        "bright_ti4",
        "scan",
        "track",
        "acq_date",
        "acq_time",
        "satellite",
        "instrument",
        "confidence",
        "version",
        "bright_ti5",
        "frp",
        "daynight",
        "type",
        "source_product",
        "sampling_region",
        "sample_window_start",
        "sample_window_days",
        "confidence_raw",
        "quality_flag_invalid_frp",
        "quality_flag_invalid_scan_track",
        "brightness_temperature_primary_k",
        "brightness_temperature_secondary_k",
        "brightness_primary_source",
        "confidence_encoding",
        "acquisition_date",
        "acquisition_time_utc",
        "observation_id",
    ),
    "VIIRS_NOAA20": (
        "latitude",
        "longitude",
        "bright_ti4",
        "scan",
        "track",
        "acq_date",
        "acq_time",
        "satellite",
        "instrument",
        "confidence",
        "version",
        "bright_ti5",
        "frp",
        "daynight",
        "type",
        "source_product",
        "sampling_region",
        "sample_window_start",
        "sample_window_days",
        "confidence_raw",
        "quality_flag_invalid_frp",
        "quality_flag_invalid_scan_track",
        "brightness_temperature_primary_k",
        "brightness_temperature_secondary_k",
        "brightness_primary_source",
        "confidence_encoding",
        "acquisition_date",
        "acquisition_time_utc",
        "observation_id",
    ),
}


def cleaned_columns(sensor_key: str) -> tuple[str, ...]:
    return CLEANED_COLUMNS[sensor_key]


def reproduced_columns(sensor_key: str) -> tuple[str, ...]:
    return tuple(
        column
        for column in CLEANED_COLUMNS[sensor_key]
        if column != "observation_id"
    )


FLOAT_COLUMNS: tuple[str, ...] = (
    "latitude",
    "longitude",
    "brightness",
    "scan",
    "track",
    "bright_t31",
    "frp",
    "brightness_temperature_primary_k",
    "brightness_temperature_secondary_k",
    "bright_ti4",
    "bright_ti5",
)

INT_COLUMNS: tuple[str, ...] = ("sample_window_days",)

BOOL_COLUMNS: tuple[str, ...] = (
    "quality_flag_invalid_frp",
    "quality_flag_invalid_scan_track",
)

DATE_COLUMNS: tuple[str, ...] = ("acquisition_date", "sample_window_start")

SENSOR_SPECS: dict[str, dict[str, str]] = {
    "MODIS": {
        "raw": "data/raw/MODIS_SP_raw.csv",
        "cleaned": "data/cleaned/MODIS_SP_cleaned.csv",
        "primary": "brightness",
        "secondary": "bright_t31",
        "encoding": "numeric",
    },
    "VIIRS_SNPP": {
        "raw": "data/raw/VIIRS_SNPP_SP_raw.csv",
        "cleaned": "data/cleaned/VIIRS_SNPP_SP_cleaned.csv",
        "primary": "bright_ti4",
        "secondary": "bright_ti5",
        "encoding": "categorical",
    },
    "VIIRS_NOAA20": {
        "raw": "data/raw/VIIRS_NOAA20_SP_raw.csv",
        "cleaned": "data/cleaned/VIIRS_NOAA20_SP_cleaned.csv",
        "primary": "bright_ti4",
        "secondary": "bright_ti5",
        "encoding": "categorical",
    },
}

PLATFORM_BY_SATELLITE: dict[str, str] = {
    "Terra": "Terra",
    "Aqua": "Aqua",
    "N": "SNPP",
    "N20": "NOAA-20",
}

L1_TIME_RAW = "l1_time_raw"
L1_TIME_HHMM = "l1_time_utc_hhmm"
L1_TIME_WAS_PADDED = "l1_time_was_padded"
L1_TIME_STATUS = "l1_time_status"
L1_FRP_STATUS = "l1_frp_status"
L1_ZERO_FRP = "l1_validity_zero_frp"
L1_NEGATIVE_FRP = "l1_validity_negative_frp"
L1_MISSING_FRP = "l1_validity_missing_frp"
L1_INVALID_COORDS = "l1_validity_invalid_coords"
L1_INVALID_SCAN_TRACK = "l1_validity_invalid_scan_track"
L1_DUPLICATE_ID = "l1_validity_duplicate_id"
L1_QUALITY_STATUS = "l1_quality_status"
L1_TIMESTAMP = "acquisition_timestamp_utc"
L1_ROW_ID = "l1_row_id"
L1_SOURCE_FILE = "l1_source_file"
L1_SENSOR_KEY = "l1_sensor_key"
L1_PLATFORM = "l1_platform"

L1_DERIVED_COLUMNS: tuple[str, ...] = (
    L1_ROW_ID,
    L1_SOURCE_FILE,
    L1_SENSOR_KEY,
    L1_PLATFORM,
    L1_TIME_RAW,
    L1_TIME_HHMM,
    L1_TIME_WAS_PADDED,
    L1_TIME_STATUS,
    L1_FRP_STATUS,
    L1_ZERO_FRP,
    L1_NEGATIVE_FRP,
    L1_MISSING_FRP,
    L1_INVALID_COORDS,
    L1_INVALID_SCAN_TRACK,
    L1_DUPLICATE_ID,
    L1_QUALITY_STATUS,
    L1_TIMESTAMP,
)

QUALITY_STATUSES = (
    "valid",
    "valid_flagged_zero_frp",
    "invalid_coordinates",
    "invalid_time",
    "invalid_frp",
    "invalid_duplicate_id",
)


# ---------------------------------------------------------------------------
# Scalar rules
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TimeNormalization:
    normalized: str | None
    was_padded: bool
    status: str  # valid | invalid | missing


def normalize_hhmm(value: object) -> TimeNormalization:
    """Normalize an HHMM value with explicit leading-zero handling.

    Rules:
    - ``None``, empty, or non-finite -> missing.
    - Integral numbers and digit strings with 1-4 digits are accepted.
    - Fewer than four digits are left-padded with zero; ``was_padded`` is True.
    - More than four digits, non-digits, or hour/minute out of range -> invalid.
    - No invalid value is repaired or imputed.
    """
    if value is None:
        return TimeNormalization(None, False, "missing")
    if isinstance(value, float):
        if not np.isfinite(value):
            return TimeNormalization(None, False, "missing")
        if not value.is_integer():
            return TimeNormalization(None, False, "invalid")
        text = str(int(value))
    elif isinstance(value, (int, np.integer)):
        text = str(int(value))
    else:
        text = str(value).strip()
        if text == "" or text.lower() in {"nan", "none", "nat"}:
            return TimeNormalization(None, False, "missing")

    if not text.isdigit() or len(text) > 4:
        return TimeNormalization(None, False, "invalid")

    padded = text.zfill(4)
    hour = int(padded[:2])
    minute = int(padded[2:])
    if hour > 23 or minute > 59:
        return TimeNormalization(None, False, "invalid")

    return TimeNormalization(padded, len(text) < 4, "valid")


def classify_frp(value: object) -> str:
    """Return ``valid``, ``flagged_zero``, ``invalid_negative`` or ``invalid_missing``.

    Zero is a measured value and is flagged, never treated as invalid or
    silently changed.
    """
    if value is None:
        return "invalid_missing"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "invalid_missing"
    if not np.isfinite(numeric):
        return "invalid_missing"
    if numeric < 0:
        return "invalid_negative"
    if numeric == 0:
        return "flagged_zero"
    return "valid"


def invalid_scan_track(scan: object, track: object) -> bool:
    """True when scan or track is missing, non-finite, or non-positive."""
    try:
        scan_value = float(scan)
        track_value = float(track)
    except (TypeError, ValueError):
        return True
    if not np.isfinite(scan_value) or not np.isfinite(track_value):
        return True
    return scan_value <= 0 or track_value <= 0


def invalid_coordinates(latitude: object, longitude: object) -> bool:
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        return True
    if not np.isfinite(lat) or not np.isfinite(lon):
        return True
    return not (-90 <= lat <= 90) or not (-180 <= lon <= 180)


# ---------------------------------------------------------------------------
# Vectorised series rules
# ---------------------------------------------------------------------------


def normalize_hhmm_series(series: pd.Series) -> pd.DataFrame:
    """Vectorised form of :func:`normalize_hhmm`.

    Returns columns ``normalized``, ``was_padded`` and ``status``.
    """
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

    return pd.DataFrame(
        {"normalized": normalized, "was_padded": was_padded, "status": status},
        index=series.index,
    )


def frp_status_series(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series.replace("", pd.NA), errors="coerce")
    status = pd.Series("valid", index=series.index, dtype="string")
    status[numeric.isna()] = "invalid_missing"
    status[numeric < 0] = "invalid_negative"
    status[numeric == 0] = "flagged_zero"
    return status


# ---------------------------------------------------------------------------
# Independent cleaning reproduction
# ---------------------------------------------------------------------------


def reproduce_cleaning(raw: pd.DataFrame, sensor_key: str) -> pd.DataFrame:
    """Derive the 28 observable cleaned columns from a raw sensor table.

    The supplied observation IDs are opaque and are not re-derived; they are
    excluded from the returned frame and are documented as a known difference.
    All other columns are reproduced exactly by the rules below:

    - original sensor columns are carried through unchanged;
    - ``confidence_raw`` copies ``confidence``;
    - ``confidence_encoding`` is numeric for MODIS, categorical for VIIRS;
    - primary/secondary brightness map to ``brightness``/``bright_t31`` for
      MODIS and ``bright_ti4``/``bright_ti5`` for VIIRS;
    - ``acquisition_date`` copies ``acq_date``;
    - ``acquisition_time_utc`` is ``acq_time`` zero-padded to four digits;
    - ``quality_flag_invalid_frp`` is True only for missing or negative FRP;
      zero FRP is deliberately not invalid;
    - ``quality_flag_invalid_scan_track`` is True for missing, non-finite or
      non-positive scan/track.
    """
    spec = SENSOR_SPECS[sensor_key]
    out = raw.copy()
    out["confidence_raw"] = raw["confidence"]
    out["confidence_encoding"] = spec["encoding"]
    out["brightness_temperature_primary_k"] = raw[spec["primary"]]
    out["brightness_temperature_secondary_k"] = raw[spec["secondary"]]
    out["brightness_primary_source"] = spec["primary"]
    out["acquisition_date"] = raw["acq_date"]
    out["acquisition_time_utc"] = raw["acq_time"].astype(str).str.zfill(4)

    frp = pd.to_numeric(raw["frp"].replace("", pd.NA), errors="coerce")
    scan = pd.to_numeric(raw["scan"].replace("", pd.NA), errors="coerce")
    track = pd.to_numeric(raw["track"].replace("", pd.NA), errors="coerce")

    out["quality_flag_invalid_frp"] = (frp.isna() | (frp < 0)).map(
        {True: "True", False: "False"}
    )
    out["quality_flag_invalid_scan_track"] = (
        scan.isna() | track.isna() | (scan <= 0) | (track <= 0)
    ).map({True: "True", False: "False"})

    return out.loc[:, list(reproduced_columns(sensor_key))].copy()


# ---------------------------------------------------------------------------
# Canonical frame
# ---------------------------------------------------------------------------


def _to_float(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.replace("", pd.NA), errors="coerce").astype("float64")


def _to_nullable_int(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series.replace("", pd.NA), errors="coerce")
    integral = numeric.notna() & (numeric % 1 == 0)
    return numeric.where(integral).astype("Int64")


def _to_bool(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip().str.lower()
    return text.isin(["true", "1", "yes"]).fillna(False).astype(bool)


def _assign_quality_status(frame: pd.DataFrame) -> pd.Series:
    """Vectorised quality status with one explicit priority order.

    Zero FRP is a flag, not an invalidity. Duplicate IDs outrank the zero-FRP
    flag but never override a coordinate, time or FRP invalidity.
    """
    status = np.select(
        [
            frame[L1_INVALID_COORDS],
            frame[L1_TIME_STATUS] != "valid",
            frame[L1_FRP_STATUS].isin(["invalid_missing", "invalid_negative"]),
            frame[L1_DUPLICATE_ID],
            frame[L1_FRP_STATUS] == "flagged_zero",
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


def build_canonical_frame(
    cleaned: pd.DataFrame,
    sensor_key: str,
    source_file: str,
    row_offset: int = 0,
) -> pd.DataFrame:
    """Type a frozen cleaned table and add explicit L1 validity fields.

    Input columns are preserved by name. Values are typed, never imputed:
    missing sensor-specific brightness stays null, and invalid FRP/time values
    keep their original text while receiving an explicit status.
    """
    expected_columns = cleaned_columns(sensor_key)
    missing = [column for column in expected_columns if column not in cleaned.columns]
    if missing:
        raise ValueError(f"{sensor_key}: missing baseline columns {missing}")

    frame = cleaned.loc[:, list(expected_columns)].copy()

    # Preserve the raw time text before typing anything else.
    time_raw = frame["acq_time"].astype("string")

    for column in FLOAT_COLUMNS:
        if column in frame.columns:
            frame[column] = _to_float(frame[column])
    for column in INT_COLUMNS:
        frame[column] = _to_nullable_int(frame[column])
    for column in BOOL_COLUMNS:
        frame[column] = _to_bool(frame[column])
    for column in DATE_COLUMNS:
        frame[column] = pd.to_datetime(frame[column], format="%Y-%m-%d", errors="coerce")

    frame["observation_id"] = frame["observation_id"].astype("string")

    time_parts = normalize_hhmm_series(frame["acquisition_time_utc"])
    frp_parts = frp_status_series(frame["frp"])
    frp_numeric = pd.to_numeric(frame["frp"], errors="coerce")

    frame[L1_ROW_ID] = pd.Series(
        range(row_offset, row_offset + len(frame)), index=frame.index, dtype="int64"
    )
    frame[L1_SOURCE_FILE] = source_file
    frame[L1_SENSOR_KEY] = sensor_key
    frame[L1_PLATFORM] = frame["satellite"].map(PLATFORM_BY_SATELLITE).astype("string")
    frame[L1_TIME_RAW] = time_raw
    frame[L1_TIME_HHMM] = time_parts["normalized"]
    frame[L1_TIME_WAS_PADDED] = time_parts["was_padded"]
    frame[L1_TIME_STATUS] = time_parts["status"]
    frame[L1_FRP_STATUS] = frp_parts
    frame[L1_ZERO_FRP] = (frp_numeric == 0).fillna(False).astype(bool)
    frame[L1_NEGATIVE_FRP] = (frp_numeric < 0).fillna(False).astype(bool)
    frame[L1_MISSING_FRP] = frp_numeric.isna()
    frame[L1_INVALID_COORDS] = ~(
        frame["latitude"].between(-90, 90) & frame["longitude"].between(-180, 180)
    )
    frame[L1_INVALID_SCAN_TRACK] = (
        frame["scan"].isna()
        | frame["track"].isna()
        | (frame["scan"] <= 0)
        | (frame["track"] <= 0)
    )
    # Filled globally after concatenation; default False here.
    frame[L1_DUPLICATE_ID] = False

    date_text = frame["acquisition_date"].dt.strftime("%Y-%m-%d")
    timestamp_text = date_text + " " + frame[L1_TIME_HHMM].astype("string")
    frame[L1_TIMESTAMP] = pd.to_datetime(
        timestamp_text, format="%Y-%m-%d %H%M", errors="coerce"
    )

    frame[L1_QUALITY_STATUS] = _assign_quality_status(frame)

    ordered = list(expected_columns) + list(L1_DERIVED_COLUMNS)
    return frame.loc[:, ordered]


def apply_duplicate_flags(frame: pd.DataFrame) -> pd.DataFrame:
    """Flag every occurrence of a duplicated observation ID and rebuild status."""
    duplicates = frame["observation_id"].duplicated(keep=False)
    frame[L1_DUPLICATE_ID] = duplicates.fillna(False).astype(bool)
    frame[L1_QUALITY_STATUS] = _assign_quality_status(frame)
    return frame


def canonical_dtypes(frame: pd.DataFrame) -> dict[str, str]:
    """Expected parquet dtype family for each canonical column."""
    dtypes: dict[str, str] = {}
    for column in frame.columns:
        if column in FLOAT_COLUMNS:
            dtypes[column] = "float64"
        elif column in INT_COLUMNS:
            dtypes[column] = "Int64"
        elif column in BOOL_COLUMNS:
            dtypes[column] = "bool"
        elif column in DATE_COLUMNS:
            dtypes[column] = "datetime64[ns]"
        elif column == L1_ROW_ID:
            dtypes[column] = "int64"
        elif column in {
            L1_TIME_WAS_PADDED,
            L1_ZERO_FRP,
            L1_NEGATIVE_FRP,
            L1_MISSING_FRP,
            L1_INVALID_COORDS,
            L1_INVALID_SCAN_TRACK,
            L1_DUPLICATE_ID,
        }:
            dtypes[column] = "bool"
        elif column == L1_TIMESTAMP:
            dtypes[column] = "datetime64[ns]"
        else:
            dtypes[column] = "string"
    return dtypes
