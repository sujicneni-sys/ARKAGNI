"""Read-only SQLite serving layer.

The 275 MB of cleaned CSV is converted once, offline, into ``data.db``.  At
runtime the service opens that file read-only and answers every explorer query
with SQL, so resident memory stays flat regardless of dataset size.
"""

from __future__ import annotations

import gzip
import json
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from backend import core

SATELLITE_ALIASES: dict[str, tuple[str, ...]] = {
    "modis": ("Aqua", "Terra"),
    "aqua": ("Aqua",),
    "terra": ("Terra",),
    "snpp": ("N",),
    "suomi-npp": ("N",),
    "noaa-20": ("N20",),
    "noaa20": ("N20",),
}

SORT_COLUMNS: dict[str, str] = {
    "observation_id": "observation_id",
    "satellite": "satellite",
    "region": "sampling_region",
    "latitude": "latitude",
    "longitude": "longitude",
    "date": "acquisition_date",
    "utc": "acquisition_time",
    "lst": "lst",
    "frp": "frp",
    "scan": "scan",
    "status": "status",
}

OBSERVATION_SELECT = """
SELECT observation_id, satellite, sampling_region, window_start,
       acquisition_date, acquisition_time, latitude, longitude, frp,
       scan, track, lst, cell_lat, cell_lon, cell_id, flags, daynight,
       time_was_padded, quality_status, status
FROM observations
"""


def _iso_date(value: int | None) -> str | None:
    if value is None:
        return None
    text = f"{int(value):08d}"
    return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"


def _utc_display(value: int | None) -> str | None:
    if value is None:
        return None
    text = f"{int(value):04d}"
    return f"{text[0:2]}:{text[2:4]}"


def _finite(value: Any, digits: int) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric != numeric or numeric in (float("inf"), float("-inf")):
        return None
    return round(numeric, digits)


def ensure_database(path: Path, archive: Path | None = None) -> Path:
    """Return a readable database path, expanding ``data.db.gz`` if needed."""
    if path.is_file():
        return path
    if archive is not None and archive.is_file():
        target = Path(tempfile.gettempdir()) / "arkagni-data.db"
        with gzip.open(archive, "rb") as source, target.open("wb") as sink:
            shutil.copyfileobj(source, sink, length=1024 * 1024)
        return target
    raise FileNotFoundError(
        f"{path.name} is missing. Build it with `python scripts/05_build_database.py`."
    )


class DataStore:
    """Thin read-only wrapper around ``data.db``."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(f"database not found: {self.path}")
        self._uri = f"file:{self.path.as_posix()}?mode=ro&immutable=1"
        with self._connect() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        missing = {"meta", "payloads", "observations", "pairs"} - tables
        if missing:
            raise RuntimeError(f"{self.path.name} is missing tables: {sorted(missing)}")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._uri, uri=True, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # -- metadata ---------------------------------------------------------

    def meta(self, key: str, default: str | None = None) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def meta_json(self, key: str) -> Any:
        raw = self.meta(key)
        return json.loads(raw) if raw is not None else None

    def payload(self, name: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT json FROM payloads WHERE name = ?", (name,)
            ).fetchone()
        if row is None:
            raise KeyError(f"payload not found in data.db: {name}")
        return json.loads(row["json"])

    # -- public payloads --------------------------------------------------

    def ingestion_report(self) -> dict[str, Any]:
        return self.payload("ingestion_report")

    def summary_payload(self) -> dict[str, Any]:
        return self.payload("observations_summary")

    def data_hash(self) -> str:
        return str(self.meta("data_hash"))

    def row_count(self) -> int:
        return int(self.meta("observation_rows") or 0)

    # -- paired cell-days -------------------------------------------------

    def pairs_frame(self) -> pd.DataFrame:
        """Load the small (region x window x cell) paired table into pandas."""
        schema = self.meta_json("pairs_schema") or []
        with self._connect() as conn:
            frame = pd.read_sql_query("SELECT * FROM pairs", conn)
        for column in schema:
            name = column["name"]
            kind = column["kind"]
            if name not in frame.columns:
                continue
            if kind == "datetime":
                frame[name] = pd.to_datetime(frame[name])
            elif kind == "int":
                frame[name] = frame[name].astype("int64")
            elif kind == "float":
                frame[name] = frame[name].astype("float64")
            elif kind == "str":
                frame[name] = frame[name].astype("string")
        return frame

    # -- observation explorer ---------------------------------------------

    def _filters(
        self,
        *,
        region: str | None,
        satellite: str | None,
        year: int | None,
        status: str | None,
        daynight: str | None,
        search: str | None,
    ) -> tuple[list[str], list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        if region:
            clauses.append("lower(sampling_region) = lower(?)")
            params.append(region)
        if satellite:
            values = SATELLITE_ALIASES.get(satellite.lower(), (satellite,))
            placeholders = ",".join("?" for _ in values)
            clauses.append(f"satellite IN ({placeholders})")
            params.extend(values)
        if year:
            clauses.append("year = ?")
            params.append(int(year))
        if status:
            clauses.append("status = ?")
            params.append(status.lower())
        if daynight:
            clauses.append("daynight = ?")
            params.append(daynight.upper())
        if search:
            needle = search.strip().lower()
            if needle:
                clauses.append(
                    "(lower(observation_id) LIKE ? OR lower(cell_id) LIKE ?)"
                )
                params.extend([f"%{needle}%", f"%{needle}%"])

        return clauses, params

    def observations(
        self,
        *,
        region: str | None = None,
        satellite: str | None = None,
        year: int | None = None,
        status: str | None = None,
        daynight: str | None = None,
        search: str | None = None,
        sort_by: str = "date",
        sort_dir: str = "desc",
        page: int = 1,
        page_size: int = 25,
    ) -> dict[str, Any]:
        """Run one filtered, sorted, paginated observation query."""
        clauses, params = self._filters(
            region=region,
            satellite=satellite,
            year=year,
            status=status,
            daynight=daynight,
            search=search,
        )
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        column = SORT_COLUMNS.get(sort_by, "acquisition_date")
        direction = "ASC" if sort_dir == "asc" else "DESC"
        offset = (page - 1) * page_size

        with self._connect() as conn:
            total = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM observations{where}", params
                ).fetchone()[0]
            )
            cursor = conn.execute(
                f"{OBSERVATION_SELECT}{where} "
                f"ORDER BY {column} {direction}, rowid ASC LIMIT ? OFFSET ?",
                [*params, page_size, offset],
            )
            records = cursor.fetchall()

        rows = []
        for record in records:
            lst = _finite(record["lst"], 4)
            rows.append(
                {
                    "observation_id": str(record["observation_id"]),
                    "satellite": str(record["satellite"]),
                    "region": str(record["sampling_region"]),
                    "latitude": _finite(record["latitude"], 5),
                    "longitude": _finite(record["longitude"], 5),
                    "cell": str(record["cell_id"]),
                    "date": _iso_date(record["acquisition_date"]),
                    "window_start": _iso_date(record["window_start"]),
                    "utc": _utc_display(record["acquisition_time"]),
                    "lst": lst,
                    "lst_display": (
                        core.format_lst([lst])[0] if lst is not None else None
                    ),
                    "lst_derivation": "lst = (UTC hours + longitude / 15) mod 24",
                    "frp_mw": _finite(record["frp"], 4),
                    "scan_km": _finite(record["scan"], 4),
                    "track_km": _finite(record["track"], 4),
                    "status": str(record["status"]),
                    "flags_uint8": int(record["flags"]),
                    "time_was_padded": bool(record["time_was_padded"]),
                }
            )

        pages = max(1, -(-total // page_size))
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
            "has_more": offset + page_size < total,
            "sort_by": sort_by,
            "sort_dir": sort_dir,
            "rows": rows,
        }
