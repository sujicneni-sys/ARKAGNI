"""Pre-computed observations summary.

The summary is a pure function of the observation table, the paired cell-days
and the frozen results artifact.  It is computed once when ``data.db`` is built
so the serving process never holds the full observation frame in memory.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from backend import core


def _json_safe(value: Any) -> Any:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return value
    if numeric != numeric or numeric in (float("inf"), float("-inf")):
        return None
    return numeric


def build_summary(
    frame: pd.DataFrame,
    pairs: pd.DataFrame,
    results: dict[str, Any],
) -> dict[str, Any]:
    """Return the ``/observations/summary`` payload for the given tables."""
    satellite_year = []
    grouped = frame.groupby(["satellite", "year"], observed=True)["lst"]
    for (satellite, year), values in grouped:
        satellite_year.append(
            {
                "satellite": str(satellite),
                "year": int(year),
                "n": int(values.size),
                "lst_median_h": _json_safe(round(float(values.median()), 4)),
                "lst_p05_h": _json_safe(round(float(values.quantile(0.05)), 4)),
                "lst_p95_h": _json_safe(round(float(values.quantile(0.95)), 4)),
                "lst_median_display": core.format_lst([float(values.median())])[0],
            }
        )

    frp_by_satellite = []
    for satellite, values in frame.groupby("satellite", observed=True)["frp"]:
        frp_by_satellite.append(
            {
                "satellite": str(satellite),
                "n": int(values.size),
                "median_mw": _json_safe(round(float(values.median()), 4)),
                "p95_mw": _json_safe(round(float(values.quantile(0.95)), 4)),
                "max_mw": _json_safe(round(float(values.max()), 4)),
            }
        )

    status_counts = {
        str(key): int(value) for key, value in frame["status"].value_counts().items()
    }
    daynight_counts = {
        str(key): int(value) for key, value in frame["daynight"].value_counts().items()
    }

    pairs_by_year_region: dict[str, dict[str, int]] = {}
    for (year, region), count in pairs.groupby(["year", "region"], observed=True).size().items():
        pairs_by_year_region.setdefault(str(int(year)), {})[str(region)] = int(count)

    sparse_notes = []
    for year in sorted(frame["year"].unique()):
        year_rows = int((frame["year"] == year).sum())
        for region in sorted(frame["sampling_region"].unique()):
            region_rows = int(
                ((frame["year"] == year) & (frame["sampling_region"] == region)).sum()
            )
            matched = int(pairs_by_year_region.get(str(int(year)), {}).get(str(region), 0))
            if region_rows > 0 and matched == 0:
                sparse_notes.append(
                    {
                        "year": int(year),
                        "region": str(region),
                        "raw_rows": region_rows,
                        "matched_pairs": 0,
                        "message": (
                            f"Calibration interrupt: {int(year)} has 0 matched pairs for "
                            f"{region} while {region_rows:,} raw observations exist. "
                            "Zero matched pairs is not zero raw observations."
                        ),
                    }
                )

    windows = results["dataset"]["window_starts"]
    window_days = int(results["dataset"]["window_days"])
    active_dates = sorted(
        {
            (pd.Timestamp(start) + pd.Timedelta(days=offset)).date().isoformat()
            for start in windows
            for offset in range(window_days)
        }
    )

    return {
        "satellite_year_lst": satellite_year,
        "frp_by_satellite": frp_by_satellite,
        "status_counts": status_counts,
        "daynight_counts": daynight_counts,
        "pairs_by_year_region": pairs_by_year_region,
        "sparse_notes": sparse_notes,
        "windows": windows,
        "window_days": window_days,
        "active_dates": active_dates,
        "status_definition": {
            "validated": "type == 0 AND FRP > 0 AND daynight == D",
            "flagged": "zero FRP or night; retained with a flag",
            "excluded": "type != 0 or negative FRP; retained with a flag",
        },
    }
