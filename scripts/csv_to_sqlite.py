"""Convert the cleaned FIRMS CSV files into a single SQLite database.

Usage:
    python scripts/csv_to_sqlite.py
    python scripts/csv_to_sqlite.py --output data.db MODIS_SP_cleaned.csv

The CSV files are read in chunks, so this works on a machine with modest RAM.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = (
    "MODIS_SP_cleaned.csv",
    "VIIRS_SNPP_SP_cleaned.csv",
    "VIIRS_NOAA20_SP_cleaned.csv",
)
TABLE = "observations"
CHUNK_SIZE = 200_000

# Keep the documented HHMM time columns as text so leading zeros survive, and
# keep the 20-digit observation identifiers as text because they overflow int64.
TEXT_COLUMNS = {
    "acq_time": "string",
    "acquisition_time_utc": "string",
    "observation_id": "string",
}


def union_columns(sources: list[Path]) -> list[str]:
    """Collect every header across the inputs, preserving first-seen order."""
    columns: list[str] = []
    for path in sources:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            header = next(csv.reader(handle))
        for name in header:
            if name not in columns:
                columns.append(name)
    return columns


def convert(sources: list[Path], output: Path) -> int:
    if output.exists():
        output.unlink()

    columns = union_columns(sources)
    connection = sqlite3.connect(output)
    connection.execute("PRAGMA journal_mode = OFF")
    connection.execute("PRAGMA synchronous = OFF")

    total = 0
    first_write = True
    for path in sources:
        print(f"reading {path.name}", flush=True)
        reader = pd.read_csv(
            path,
            chunksize=CHUNK_SIZE,
            dtype=TEXT_COLUMNS,
            low_memory=False,
        )
        for chunk in reader:
            # MODIS and VIIRS do not share every column; align to the union.
            chunk = chunk.reindex(columns=columns)
            chunk.to_sql(
                TABLE,
                connection,
                if_exists="replace" if first_write else "append",
                index=False,
            )
            first_write = False
            total += len(chunk)
            print(f"  {total:,} rows", flush=True)

    for column in ("acquisition_date", "satellite", "sampling_region"):
        connection.execute(
            f'CREATE INDEX IF NOT EXISTS "idx_{TABLE}_{column}" ON "{TABLE}" ("{column}")'
        )

    connection.commit()
    connection.close()
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "sources",
        nargs="*",
        type=Path,
        help="CSV files to convert (default: the three cleaned FIRMS CSVs).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data.db",
        help="SQLite file to write (default: ./data.db).",
    )
    args = parser.parse_args()

    sources = [path.resolve() for path in args.sources] or [
        PROJECT_ROOT / name for name in DEFAULT_SOURCES
    ]
    missing = [str(path) for path in sources if not path.is_file()]
    if missing:
        parser.error(f"CSV file(s) not found: {', '.join(missing)}")

    rows = convert(sources, args.output.resolve())
    size_mb = args.output.stat().st_size / (1024 * 1024)
    print(f"wrote {args.output.name}: {rows:,} rows, {size_mb:.1f} MB", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
