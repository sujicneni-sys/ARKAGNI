"""L1/L2 data adapters: frozen CSV/Parquet -> validated cell-days.

These adapters are intentionally outside the L5 core.  File I/O belongs here or
in batch scripts, never in the science functions called by the API.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from backend import core

PIXEL_COLUMNS = [
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
    "observation_id",
]

CELL_GROUP = (
    "sampling_region",
    "sample_window_start",
    "acquisition_date",
    "cell_lat",
    "cell_lon",
)
PAIR_KEY = CELL_GROUP


def load_cleaned_csv(path: str | Path, usecols: list[str] | None = None) -> pd.DataFrame:
    """Read a frozen FIRMS cleaned CSV without coercing padded HHMM to int."""
    frame = pd.read_csv(
        path,
        usecols=usecols,
        dtype={"acquisition_time_utc": "string", "acq_time": "string"},
        low_memory=False,
    )
    if "acquisition_date" in frame:
        frame["acquisition_date"] = pd.to_datetime(frame["acquisition_date"], errors="coerce")
    if "sample_window_start" in frame:
        frame["sample_window_start"] = pd.to_datetime(frame["sample_window_start"], errors="coerce")
    return frame


def load_l1_canonical(path: str | Path, columns: list[str] | None = None) -> pd.DataFrame:
    return pd.read_parquet(path, columns=columns)


def load_pairs(path: str | Path) -> pd.DataFrame:
    return pd.read_parquet(path)


def apply_pixel_contract(frame: pd.DataFrame) -> pd.DataFrame:
    """Add LST, 1-degree cell indices, uint8 flags and the validated mask."""
    out = frame.copy()
    out["lst"] = core.local_solar_time(
        core.utc_hours_from_hhmm(out["acquisition_time_utc"]), out["longitude"]
    )
    out["cell_lat"] = core.snap_coordinate(out["latitude"], "latitude")
    out["cell_lon"] = core.snap_coordinate(out["longitude"], "longitude")
    out["flags"] = core.pixel_flags(out["type"], out["frp"], out["daynight"])
    out["validated"] = core.validated_mask(out["flags"])
    footprint = out["satellite"].map(
        {"Aqua": 1.0, "Terra": 1.0, "N": 0.375, "N20": 0.375}
    ).astype("float64")
    area_km2 = pd.to_numeric(out["scan"], errors="coerce") * pd.to_numeric(
        out["track"], errors="coerce"
    )
    out["area_ratio"] = area_km2 / np.square(footprint)
    out["year"] = out["acquisition_date"].dt.year.astype("int16")
    return out


def build_cell_days(pixels: pd.DataFrame, satellite: str) -> pd.DataFrame:
    """Aggregate validated pixels to one row per 1-degree cell-day."""
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
    grouped["cell_id"] = core.cell_label(grouped["cell_lat"], grouped["cell_lon"])
    return grouped


def pair_cell_days(
    aqua: pd.DataFrame,
    reference: pd.DataFrame,
    reference_name: str = "SNPP",
) -> pd.DataFrame:
    """Inner-join cell-days on the documented key; compute y and delays."""
    suffix = reference_name.lower()
    paired = aqua.merge(
        reference, on=list(PAIR_KEY), how="inner", suffixes=("_aqua", f"_{suffix}")
    )
    if paired.empty:
        return paired
    a = paired["frp_sum_aqua"]
    r = paired[f"frp_sum_{suffix}"]
    paired["y"] = np.log(a / r)
    paired["delay_ref"] = paired["lst_aqua"] - core.REFERENCE_LST_H
    paired["delay_pair"] = paired["lst_aqua"] - paired[f"lst_{suffix}"]
    paired["block_id"] = (
        paired["sampling_region"].astype(str)
        + "|"
        + paired["sample_window_start"].dt.strftime("%Y-%m-%d")
    )
    paired["year"] = paired["acquisition_date"].dt.year.astype("int16")
    paired["region"] = paired["sampling_region"].astype(str)
    paired["cell_id"] = core.cell_label(paired["cell_lat"], paired["cell_lon"])
    return paired


def write_cell_day_fixture(frame: pd.DataFrame, path: str | Path, limit: int = 50) -> None:
    """Persist a small, real (not synthetic) fixture for tests and demos."""
    keep = [
        column
        for column in (
            "cell_id",
            "region",
            "acquisition_date",
            "lst_aqua",
            "frp_sum_aqua",
            "n_aqua",
            "scan_aqua",
            "area_ratio_aqua",
            "y",
            "delay_ref",
        )
        if column in frame.columns
    ]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    frame.loc[:, keep].head(limit).to_csv(path, index=False)
