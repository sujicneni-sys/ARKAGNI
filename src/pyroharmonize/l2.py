"""L2: pixel contract, flags, local solar time, cell-days and pairing.

All functions here operate on the frozen L1 canonical table and never write to
it.  The cell-day is the unit used by the models: one row per
(region, sampling window, date, 1-degree cell, satellite).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# Flag bits.  Bits 3-7 are reserved for saturation / plume / canopy and stay
# zero until the input data exists.  They are reported as ``not_evaluated``.
FLAG_TYPE = 1 << 0
FLAG_FRP = 1 << 1
FLAG_NIGHT = 1 << 2
EXCLUDE_MASK = FLAG_TYPE | FLAG_FRP | FLAG_NIGHT

FLAG_NAMES: tuple[str, ...] = (
    "type_not_0",
    "frp_not_above_zero",
    "night",
    "saturation_not_evaluated",
    "plume_not_evaluated",
    "canopy_not_evaluated",
)

# Nominal pixel footprints in km (FIRMS scan/track fields are km).
NOMINAL_FOOTPRINT_KM: dict[str, float] = {
    "Aqua": 1.0,
    "Terra": 1.0,
    "N": 0.375,
    "N20": 0.375,
}

CELL_GROUP = (
    "sampling_region",
    "sample_window_start",
    "acquisition_date",
    "cell_lat",
    "cell_lon",
)

PAIR_KEY = (
    "sampling_region",
    "sample_window_start",
    "acquisition_date",
    "cell_lat",
    "cell_lon",
)

REGION_ORDER = ("Southern_Africa", "Amazon", "Australia", "California")
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


def utc_hours(acquisition_time_utc: pd.Series) -> pd.Series:
    """Return decimal UTC hours from the canonical four-digit HHMM string."""
    text = acquisition_time_utc.astype("string").str.zfill(4)
    hour = pd.to_numeric(text.str.slice(0, 2), errors="coerce")
    minute = pd.to_numeric(text.str.slice(2, 4), errors="coerce")
    return hour + minute / 60.0


def local_solar_time(acquisition_time_utc: pd.Series, longitude: pd.Series) -> pd.Series:
    """lst = (UTC hours + longitude / 15) mod 24, with zero-padded HHMM."""
    return (utc_hours(acquisition_time_utc) + longitude / 15.0) % 24.0


def pixel_flags(
    detection_type: pd.Series,
    frp: pd.Series,
    daynight: pd.Series,
) -> pd.Series:
    """Build the uint8 flag bitmask.  No row is deleted."""
    type_bad = detection_type.astype("string").str.strip() != "0"
    frp_numeric = pd.to_numeric(frp, errors="coerce")
    frp_bad = frp_numeric.isna() | (frp_numeric <= 0)
    night = daynight.astype("string").str.strip().str.upper() != "D"
    flags = np.zeros(len(frp_numeric), dtype=np.uint8)
    flags |= type_bad.to_numpy(dtype=bool).astype(np.uint8) * FLAG_TYPE
    flags |= frp_bad.to_numpy(dtype=bool).astype(np.uint8) * FLAG_FRP
    flags |= night.to_numpy(dtype=bool).astype(np.uint8) * FLAG_NIGHT
    return pd.Series(flags, index=frp.index, dtype="uint8")


def flag_counts(flags: pd.Series) -> dict[str, int]:
    """Count how many pixels each rule excluded (a pixel can be counted twice)."""
    return {
        name: int(((flags.to_numpy() & (1 << bit)) != 0).sum())
        for bit, name in enumerate(FLAG_NAMES)
        if bit < 3
    }


def add_pixel_contract(frame: pd.DataFrame) -> pd.DataFrame:
    """Add LST, 1-degree cell indices, flags and the validated mask.

    ``frame`` must be the L1 canonical table with ``acquisition_time_utc``.
    """
    out = frame.copy()
    out["lst"] = local_solar_time(out["acquisition_time_utc"], out["longitude"])
    out["cell_lat"] = np.floor(out["latitude"].to_numpy()).astype(np.int32)
    out["cell_lon"] = np.floor(out["longitude"].to_numpy()).astype(np.int32)
    footprint = out["satellite"].map(NOMINAL_FOOTPRINT_KM).astype("float64")
    area_km2 = pd.to_numeric(out["scan"], errors="coerce") * pd.to_numeric(
        out["track"], errors="coerce"
    )
    out["area_ratio"] = area_km2 / (footprint * footprint)
    out["flags"] = pixel_flags(out["type"], out["frp"], out["daynight"])
    out["validated"] = (out["flags"].to_numpy() & EXCLUDE_MASK) == 0
    out["year"] = out["acquisition_date"].dt.year.astype("int16")
    return out


def cell_label(cell_lat: pd.Series, cell_lon: pd.Series) -> pd.Series:
    """Human-readable 1-degree cell label, e.g. ``S13E025``."""
    lat = cell_lat.astype(int)
    lon = cell_lon.astype(int)
    lat_part = np.where(lat >= 0, "N", "S") + pd.Series(np.abs(lat)).astype(str).str.zfill(2)
    lon_part = np.where(lon >= 0, "E", "W") + pd.Series(np.abs(lon)).astype(str).str.zfill(3)
    return pd.Series(lat_part + lon_part, index=cell_lat.index, dtype="string")


def build_cell_days(pixels: pd.DataFrame, satellite: str) -> pd.DataFrame:
    """Aggregate validated pixels to 1-degree cell-days for one satellite.

    Returns one row per (region, sampling window, date, cell).  FRP is summed;
    pixel count, mean LST, mean scan, mean area ratio and centroid are kept.
    """
    selected = pixels[(pixels["satellite"] == satellite) & pixels["validated"]]
    if selected.empty:
        return pd.DataFrame(columns=list(CELL_GROUP) + ["frp_sum", "n", "lst", "scan"])
    grouped = (
        selected.groupby(list(CELL_GROUP), observed=True, sort=False)
        .agg(
            frp_sum=("frp", "sum"),
            n=("frp", "size"),
            lst=("lst", "mean"),
            scan=("scan", "mean"),
            area_ratio=("area_ratio", "mean"),
            latitude=("latitude", "mean"),
            longitude=("longitude", "mean"),
        )
        .reset_index()
    )
    grouped["satellite"] = satellite
    grouped["cell_id"] = cell_label(grouped["cell_lat"], grouped["cell_lon"])
    return grouped


def filter_container_cells(cell_days: pd.DataFrame) -> pd.DataFrame:
    """Apply the documented service input range (pixel-area ratio 0.9 to 12)."""
    return cell_days[
        cell_days["area_ratio"].between(0.9, 12.0, inclusive="both")
        & (cell_days["frp_sum"] > 0)
        & (cell_days["n"] > 0)
    ].copy()


def pair_cell_days(
    aqua: pd.DataFrame,
    reference: pd.DataFrame,
    reference_name: str = "SNPP",
) -> pd.DataFrame:
    """Inner-join two cell-day tables on the documented key.

    The join is on region, sampling window, date and 1-degree cell.  The
    returned table carries both sides, the log ratio ``y``, and the two delay
    definitions used by the audit:
    ``delay_ref = lst_aqua - 13.6`` and ``delay_pair = lst_aqua - lst_ref``.
    """
    suffixes = ("_aqua", f"_{reference_name.lower()}")
    paired = aqua.merge(reference, on=list(PAIR_KEY), how="inner", suffixes=suffixes)
    if paired.empty:
        return paired
    a = paired["frp_sum_aqua"]
    r = paired[f"frp_sum_{reference_name.lower()}"]
    paired["y"] = np.log(a / r)
    paired["delay_ref"] = paired["lst_aqua"] - REFERENCE_LST_H
    paired["delay_pair"] = paired["lst_aqua"] - paired[f"lst_{reference_name.lower()}"]
    paired["block_id"] = (
        paired["sampling_region"].astype(str)
        + "|"
        + paired["sample_window_start"].dt.strftime("%Y-%m-%d")
    )
    paired["year"] = paired["acquisition_date"].dt.year.astype("int16")
    paired["region"] = paired["sampling_region"].astype(str)
    paired["cell_id"] = cell_label(paired["cell_lat"], paired["cell_lon"])
    return paired


def delay_bin(delay: pd.Series) -> pd.Series:
    """Assign the pre-registered delay bins; outside values are NaN."""
    return pd.cut(
        delay,
        bins=DELAY_BIN_EDGES,
        labels=DELAY_BIN_LABELS,
        include_lowest=True,
        right=True,
        ordered=True,
    ).astype("string")


def region_weights(y: pd.Series, region: pd.Series) -> pd.Series:
    """Capped inverse-frequency weights w_r = min(3, N / (K * n_r))."""
    counts = region.value_counts()
    n_total = int(counts.sum())
    k = int(counts.size)
    weight = region.map(lambda value: min(3.0, n_total / (k * counts[value])))
    return weight.astype("float64")


@dataclass(frozen=True)
class Composition:
    rows_by_satellite: dict[str, int]
    rows_by_region: dict[str, int]
    rows_by_year: dict[str, int]
    validated_by_satellite: dict[str, int]
    flags: dict[str, int]
    rows: int
    validated_rows: int


def composition(pixels: pd.DataFrame) -> Composition:
    """Measured dataset composition, used by the dashboard and report."""
    return Composition(
        rows=int(len(pixels)),
        validated_rows=int(pixels["validated"].sum()),
        rows_by_satellite={
            str(key): int(value)
            for key, value in pixels["satellite"].value_counts().items()
        },
        rows_by_region={
            str(key): int(value)
            for key, value in pixels["sampling_region"].value_counts().items()
        },
        rows_by_year={
            str(key): int(value)
            for key, value in pixels["year"].value_counts().sort_index().items()
        },
        validated_by_satellite={
            str(key): int(value)
            for key, value in pixels.loc[pixels["validated"], "satellite"]
            .value_counts()
            .items()
        },
        flags=flag_counts(pixels["flags"]),
    )
