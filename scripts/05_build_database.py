"""Convert the 275 MB of cleaned FIRMS CSV into a lightweight ``data.db``.

The service never loads the raw CSV.  It opens this SQLite file read-only and
answers every explorer query with SQL, which keeps resident memory far below
Render's 512 MB free-tier limit.

Usage:
    python scripts/05_build_database.py [--output data.db]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for candidate in (PROJECT_ROOT, PROJECT_ROOT / "src"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from backend import config, ingestion, summary  # noqa: E402

CHUNK = 50_000

OBSERVATION_TABLE = """
CREATE TABLE observations (
    observation_id      TEXT    NOT NULL,
    satellite           TEXT    NOT NULL,
    sampling_region     TEXT    NOT NULL,
    window_start        INTEGER NOT NULL,
    acquisition_date    INTEGER NOT NULL,
    acquisition_time    INTEGER NOT NULL,
    latitude            REAL    NOT NULL,
    longitude           REAL    NOT NULL,
    frp                 REAL    NOT NULL,
    scan                REAL,
    track               REAL,
    lst                 REAL,
    cell_lat            INTEGER NOT NULL,
    cell_lon            INTEGER NOT NULL,
    cell_id             TEXT    NOT NULL,
    flags               INTEGER NOT NULL,
    daynight            TEXT    NOT NULL,
    time_was_padded     INTEGER NOT NULL,
    quality_status      TEXT    NOT NULL,
    status              TEXT    NOT NULL,
    year                INTEGER NOT NULL
)
"""

OBSERVATION_INDEXES = (
    "CREATE INDEX idx_obs_date ON observations(acquisition_date)",
    "CREATE INDEX idx_obs_year ON observations(year)",
    "CREATE INDEX idx_obs_satellite ON observations(satellite)",
    "CREATE INDEX idx_obs_region ON observations(sampling_region)",
    "CREATE INDEX idx_obs_cell ON observations(cell_id)",
)


def _date_int(series: pd.Series) -> pd.Series:
    return series.dt.strftime("%Y%m%d").astype("int32")


def _native(value: Any) -> Any:
    """Convert numpy scalars and NaN into values sqlite3 can bind."""
    if value is None:
        return None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        numeric = float(value)
        return None if numeric != numeric else numeric
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, float) and value != value:
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            return value.item()
        except (ValueError, AttributeError):
            return str(value)
    return value


def _observation_rows(frame: pd.DataFrame) -> Iterable[Sequence[Any]]:
    """Yield the compact observation rows without materialising a second frame."""
    columns = [
        "observation_id",
        "satellite",
        "sampling_region",
        "window_start",
        "acquisition_date",
        "acquisition_time",
        "latitude",
        "longitude",
        "frp",
        "scan",
        "track",
        "lst",
        "cell_lat",
        "cell_lon",
        "cell_id",
        "flags",
        "daynight",
        "time_was_padded",
        "quality_status",
        "status",
        "year",
    ]
    total = len(frame)
    for start in range(0, total, CHUNK):
        block = frame.iloc[start : start + CHUNK]
        for row in block[columns].itertuples(index=False, name=None):
            yield tuple(_native(value) for value in row)
        print(f"  observations {min(start + CHUNK, total):,}/{total:,}", flush=True)


def _pairs_schema(frame: pd.DataFrame) -> list[dict[str, str]]:
    schema: list[dict[str, str]] = []
    for name in frame.columns:
        series = frame[name]
        if pd.api.types.is_datetime64_any_dtype(series):
            kind = "datetime"
        elif pd.api.types.is_bool_dtype(series):
            kind = "int"
        elif pd.api.types.is_integer_dtype(series):
            kind = "int"
        elif pd.api.types.is_float_dtype(series):
            kind = "float"
        else:
            kind = "str"
        schema.append({"name": str(name), "kind": kind})
    return schema


def _sqlite_type(kind: str) -> str:
    return {"datetime": "TEXT", "int": "INTEGER", "float": "REAL"}.get(kind, "TEXT")


def _write_pairs(
    conn: sqlite3.Connection,
    frame: pd.DataFrame,
    schema: list[dict[str, str]],
) -> None:
    """Persist the small paired table generically, preserving dtypes."""
    columns = ", ".join(
        '"' + column["name"] + '" ' + _sqlite_type(column["kind"])
        for column in schema
    )
    conn.execute(f"CREATE TABLE pairs ({columns})")

    names = [column["name"] for column in schema]
    kinds = [column["kind"] for column in schema]
    quoted = ", ".join('"' + name + '"' for name in names)
    placeholders = ", ".join("?" for _ in names)
    statement = f"INSERT INTO pairs ({quoted}) VALUES ({placeholders})"

    records: list[tuple[Any, ...]] = []
    for row in frame[names].itertuples(index=False, name=None):
        values = []
        for value, kind in zip(row, kinds):
            value = _native(value)
            if value is None:
                values.append(None)
            elif kind == "datetime":
                values.append(pd.Timestamp(value).isoformat())
            else:
                values.append(value)
        records.append(tuple(values))
    conn.executemany(statement, records)
    print(f"  pairs {len(records):,}", flush=True)


def build(output: Path) -> Path:
    started = time.time()
    results = json.loads(
        (config.ARTIFACTS_DIR / "results.json").read_text(encoding="utf-8")
    )

    print("Reading and verifying the three cleaned CSVs ...", flush=True)
    snapshot = ingestion.load_snapshot(results)
    print(
        f"  verified data_hash {snapshot.data_hash[:12]}… "
        f"({len(snapshot.observations):,} observations, {len(snapshot.pairs):,} pairs)",
        flush=True,
    )

    frame = snapshot.observations.copy()
    frame["window_start"] = _date_int(frame["sample_window_start"])
    frame["acquisition_date"] = _date_int(frame["acquisition_date"])
    frame["acquisition_time"] = frame["acquisition_time_utc"].astype("int32")
    frame["time_was_padded"] = frame["l1_time_was_padded"].astype("int8")
    frame["quality_status"] = frame["l1_quality_status"].astype(str)
    frame["year"] = frame["year"].astype("int16")

    print("Computing the observations summary ...", flush=True)
    summary_payload = summary.build_summary(snapshot.observations, snapshot.pairs, results)

    if output.exists():
        output.unlink()

    conn = sqlite3.connect(output)
    try:
        conn.execute("PRAGMA journal_mode = OFF")
        conn.execute("PRAGMA synchronous = OFF")
        conn.execute("PRAGMA page_size = 4096")
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("CREATE TABLE payloads (name TEXT PRIMARY KEY, json TEXT NOT NULL)")
        conn.execute(OBSERVATION_TABLE)

        print("Writing observations ...", flush=True)
        conn.executemany(
            "INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            _observation_rows(frame),
        )
        for statement in OBSERVATION_INDEXES:
            conn.execute(statement)

        pairs_schema = _pairs_schema(snapshot.pairs)
        print("Writing pairs ...", flush=True)
        _write_pairs(conn, snapshot.pairs, pairs_schema)

        report = dict(snapshot.report)
        report["source_policy"] = (
            "Built offline from the three cleaned CSVs into data.db; the serving "
            "process reads data.db read-only and never loads the raw CSV."
        )
        meta = {
            "schema_version": "pyroharmonize.database.v1",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "data_hash": snapshot.data_hash,
            "observation_rows": str(len(frame)),
            "pair_rows": str(len(snapshot.pairs)),
            "verification_passed": str(bool(report["verification"]["passed"])).lower(),
        }
        conn.executemany(
            "INSERT INTO meta(key, value) VALUES (?, ?)", list(meta.items())
        )
        conn.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?)",
            ("pairs_schema", json.dumps(pairs_schema)),
        )
        conn.executemany(
            "INSERT INTO payloads(name, json) VALUES (?, ?)",
            [
                ("ingestion_report", json.dumps(report)),
                ("observations_summary", json.dumps(summary_payload)),
            ],
        )
        conn.commit()
        conn.execute("VACUUM")
        conn.commit()
    finally:
        conn.close()

    size_mb = output.stat().st_size / (1024 * 1024)
    print(
        f"Wrote {output} ({size_mb:.1f} MB) in {time.time() - started:.1f}s",
        flush=True,
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data.db",
        help="Destination SQLite file (default: ./data.db)",
    )
    args = parser.parse_args()
    build(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
