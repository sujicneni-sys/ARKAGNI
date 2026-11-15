"""Semantic equivalence between the master CSV and master JSONL.

The two files store the same table with different physical encodings (CSV text
versus JSON scalars). This module compares typed values, not bytes, and reports
every field-level difference. It never writes either input.

The comparison is streaming: one CSV chunk and one JSONL chunk at a time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

import numpy as np
import pandas as pd

from pyroharmonize.l1 import normalize_hhmm_series

NUMERIC_COLUMNS: tuple[str, ...] = (
    "latitude",
    "longitude",
    "frp_mw",
    "brightness_temperature_primary_k",
    "brightness_temperature_secondary_k",
    "scan",
    "track",
    "brightness",
    "bright_t31",
    "bright_ti4",
    "bright_ti5",
    "frp",
)

INTEGER_COLUMNS: tuple[str, ...] = ("sample_window_days",)

BOOLEAN_COLUMNS: tuple[str, ...] = (
    "quality_flag_invalid_frp",
    "quality_flag_invalid_scan_track",
)

TIME_COLUMN = "acquisition_time_utc"

ID_COLUMN = "observation_id"


@dataclass
class ColumnResult:
    mismatches: int = 0
    examples: list[dict[str, str | int]] = field(default_factory=list)

    def add_example(self, row: int, csv_value: str, json_value: str) -> None:
        if len(self.examples) < 5:
            self.examples.append(
                {"row": row, "csv": csv_value, "jsonl": json_value}
            )


def _as_string(series: pd.Series) -> pd.Series:
    return series.astype("string").fillna("")


def _normalize_numeric(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series.replace("", pd.NA), errors="coerce")

    def render(value: float) -> str:
        if pd.isna(value):
            return ""
        return repr(float(value))

    return numeric.map(render).astype("string")


def _normalize_integer(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series.replace("", pd.NA), errors="coerce")
    return numeric.map(lambda value: "" if pd.isna(value) else str(int(value))).astype(
        "string"
    )


def _normalize_boolean(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip().str.lower()
    return text.isin(["true", "1", "yes"]).map({True: "True", False: "False"}).astype(
        "string"
    )


def _normalize_time(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    parts = normalize_hhmm_series(series)
    invalid = parts["status"] != "valid"
    normalized = parts["normalized"].astype("string")
    # Keep invalid raw values visible so two different invalid values cannot
    # compare equal by accident.
    normalized[invalid] = "INVALID:" + _as_string(series)[invalid]
    return normalized.fillna(""), parts


def normalize_chunk(frame: pd.DataFrame, columns: list[str]) -> tuple[pd.DataFrame, dict]:
    """Return a chunk with every column rendered to a canonical comparison form."""
    time_meta: dict = {}
    normalized = pd.DataFrame(index=frame.index)
    for column in columns:
        if column == TIME_COLUMN:
            normalized[column], parts = _normalize_time(frame[column])
            time_meta[column] = {
                "status_counts": parts["status"].value_counts().to_dict(),
                "was_padded": int(parts["was_padded"].sum()),
            }
        elif column in NUMERIC_COLUMNS:
            normalized[column] = _normalize_numeric(frame[column])
        elif column in INTEGER_COLUMNS:
            normalized[column] = _normalize_integer(frame[column])
        elif column in BOOLEAN_COLUMNS:
            normalized[column] = _normalize_boolean(frame[column])
        else:
            normalized[column] = _as_string(frame[column])
    return normalized, time_meta


def _chunks_csv(path: str, columns: list[str], chunk_size: int) -> Iterator[pd.DataFrame]:
    yield from pd.read_csv(
        path,
        usecols=columns,
        dtype=str,
        keep_default_na=False,
        chunksize=chunk_size,
    )


def _chunks_jsonl(path: str, columns: list[str], chunk_size: int) -> Iterator[pd.DataFrame]:
    reader = pd.read_json(
        path, lines=True, chunksize=chunk_size, dtype=False, convert_dates=False
    )
    for chunk in reader:
        missing = [column for column in columns if column not in chunk.columns]
        if missing:
            raise ValueError(f"JSONL chunk missing columns: {missing}")
        yield chunk.loc[:, columns]


def compare_master(
    csv_path: str,
    jsonl_path: str,
    columns: list[str],
    chunk_size: int = 100_000,
) -> dict:
    """Stream both master files and return a field-level comparison report."""
    column_results = {column: ColumnResult() for column in columns}
    row_index = 0
    order_mismatches = 0
    csv_ids: set[str] = set()
    json_ids: set[str] = set()
    time_totals = {
        "csv": {"valid": 0, "invalid": 0, "missing": 0, "was_padded": 0},
        "jsonl": {"valid": 0, "invalid": 0, "missing": 0, "was_padded": 0},
    }

    csv_chunks = _chunks_csv(csv_path, columns, chunk_size)
    json_chunks = _chunks_jsonl(jsonl_path, columns, chunk_size)

    while True:
        try:
            csv_chunk = next(csv_chunks)
        except StopIteration:
            csv_chunk = None
        try:
            json_chunk = next(json_chunks)
        except StopIteration:
            json_chunk = None

        if csv_chunk is None and json_chunk is None:
            break
        if csv_chunk is None or json_chunk is None:
            raise ValueError("CSV and JSONL chunk counts differ")

        if len(csv_chunk) != len(json_chunk):
            raise ValueError(
                f"chunk length differs at row {row_index}: "
                f"{len(csv_chunk)} vs {len(json_chunk)}"
            )

        csv_norm, csv_time = normalize_chunk(csv_chunk, columns)
        json_norm, json_time = normalize_chunk(json_chunk, columns)

        for source, meta in (("csv", csv_time), ("jsonl", json_time)):
            stats = meta[TIME_COLUMN]
            for status, count in stats["status_counts"].items():
                time_totals[source][status] += int(count)
            time_totals[source]["was_padded"] += stats["was_padded"]

        if not csv_norm[ID_COLUMN].equals(json_norm[ID_COLUMN]):
            order_mismatches += int(
                (csv_norm[ID_COLUMN].to_numpy() != json_norm[ID_COLUMN].to_numpy()).sum()
            )
        csv_ids.update(csv_norm[ID_COLUMN].tolist())
        json_ids.update(json_norm[ID_COLUMN].tolist())

        for column in columns:
            different = (
                csv_norm[column].to_numpy() != json_norm[column].to_numpy()
            )
            count = int(different.sum())
            if count == 0:
                continue
            column_results[column].mismatches += count
            for position in np.flatnonzero(different)[: 5 - len(column_results[column].examples)]:
                column_results[column].add_example(
                    row_index + int(position),
                    str(csv_norm[column].iloc[position]),
                    str(json_norm[column].iloc[position]),
                )

        row_index += len(csv_chunk)

    mismatched_columns = {
        column: {
            "mismatches": result.mismatches,
            "examples": result.examples,
        }
        for column, result in column_results.items()
        if result.mismatches
    }

    return {
        "rows_csv": row_index,
        "rows_compared": row_index,
        "row_order_mismatches": order_mismatches,
        "ids_only_in_csv": len(csv_ids - json_ids),
        "ids_only_in_jsonl": len(json_ids - csv_ids),
        "column_mismatch_total": int(
            sum(result.mismatches for result in column_results.values())
        ),
        "mismatched_columns": mismatched_columns,
        "time_normalization": time_totals,
        "semantically_equivalent": (
            order_mismatches == 0
            and not (csv_ids - json_ids)
            and not (json_ids - csv_ids)
            and sum(result.mismatches for result in column_results.values()) == 0
        ),
    }
