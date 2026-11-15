"""Independently reproduce the supplied cleaning output and compare it.

Reads frozen raw and cleaned CSVs, applies the explicit rules in
``pyroharmonize.l1``, compares all 28 observable columns cell by cell, and
writes the reproduced tables to ``data/interim`` plus a difference report.

The supplied observation IDs are opaque; they are counted and checked for
uniqueness but are not re-derived. This is reported as a known limitation.

Run with:
    .venv\\Scripts\\python.exe scripts\\01_l1_reproduce_cleaning.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pyroharmonize import config  # noqa: E402
from pyroharmonize.l1 import (  # noqa: E402
    SENSOR_SPECS,
    reproduce_cleaning,
    reproduced_columns,
)
from pyroharmonize.provenance import sha256_file, verify_manifest, write_json  # noqa: E402

REPORT_PATH = config.REPORT_DIR / "l1_cleaning_reproduction.json"


def compare_columns(
    reproduced: pd.DataFrame, baseline: pd.DataFrame, columns: tuple[str, ...]
) -> dict:
    result: dict[str, object] = {
        "columns_compared": len(columns),
        "mismatch_counts": {},
        "examples": {},
        "mismatched_rows": 0,
    }
    any_different = np.zeros(len(baseline), dtype=bool)
    mismatch_counts: dict[str, int] = {}
    examples: dict[str, list[dict]] = {}

    for column in columns:
        left = reproduced[column].astype(str).to_numpy()
        right = baseline[column].astype(str).to_numpy()
        different = left != right
        count = int(different.sum())
        if count:
            mismatch_counts[column] = count
            any_different |= different
            rows = np.flatnonzero(different)[:5]
            examples[column] = [
                {
                    "row": int(row),
                    "baseline": str(right[row]),
                    "reproduced": str(left[row]),
                }
                for row in rows
            ]

    result["mismatch_counts"] = mismatch_counts
    result["examples"] = examples
    result["mismatched_rows"] = int(any_different.sum())
    result["exact_match"] = not mismatch_counts
    return result


def main() -> int:
    phase0 = json.loads(config.MANIFEST_PATH.read_text(encoding="utf-8"))
    hash_by_path = {entry["path"]: entry["sha256"] for entry in phase0["files"]}

    print("[l1-repro] verifying frozen inputs against Phase 0 manifest ...")
    problems = verify_manifest(phase0, Path(phase0["raw_root"]))
    if problems:
        for problem in problems:
            print(f"[l1-repro] ERROR {problem}")
        raise SystemExit("frozen inputs changed; refusing to reproduce cleaning")

    report: dict[str, object] = {
        "schema_version": "l1.cleaning_reproduction.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "phase0_archive_sha256": phase0["source_archive"]["sha256"],
        "rules_module": "src/pyroharmonize/l1.py",
        "rules_sha256": sha256_file(PROJECT_ROOT / "src" / "pyroharmonize" / "l1.py"),
        "per_sensor": {},
    }

    total_rows = 0
    total_mismatch_cells = 0
    total_mismatch_rows = 0
    all_exact = True

    for sensor_key, spec in SENSOR_SPECS.items():
        raw_path = config.RAW_TREE / spec["raw"]
        cleaned_path = config.RAW_TREE / spec["cleaned"]
        for path in (raw_path, cleaned_path):
            expected = hash_by_path[path.relative_to(config.RAW_TREE).as_posix()]
            if sha256_file(path) != expected:
                raise SystemExit(f"input hash changed: {path}")

        print(f"[l1-repro] {sensor_key}: reading raw and cleaned ...")
        raw = pd.read_csv(raw_path, dtype=str, keep_default_na=False)
        baseline = pd.read_csv(cleaned_path, dtype=str, keep_default_na=False)

        reproduced = reproduce_cleaning(raw, sensor_key)
        expected_columns = reproduced_columns(sensor_key)
        if list(reproduced.columns) != list(expected_columns):
            raise SystemExit(f"{sensor_key}: reproduced column order differs")
        if len(reproduced) != len(baseline):
            raise SystemExit(
                f"{sensor_key}: row count differs: {len(reproduced)} vs {len(baseline)}"
            )

        comparison = compare_columns(reproduced, baseline, expected_columns)

        output_path = config.INTERIM_DIR / f"l1_reproduced_{sensor_key}.parquet"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        reproduced.to_parquet(output_path, index=False, compression="zstd")

        observation_ids = baseline["observation_id"]
        sensor_report = {
            "raw_path": spec["raw"],
            "cleaned_path": spec["cleaned"],
            "raw_sha256": hash_by_path[spec["raw"]],
            "cleaned_sha256": hash_by_path[spec["cleaned"]],
            "rows_raw": int(len(raw)),
            "rows_baseline": int(len(baseline)),
            "rows_reproduced": int(len(reproduced)),
            **comparison,
            "observation_id": {
                "reproduced": False,
                "count": int(len(observation_ids)),
                "unique": int(observation_ids.nunique()),
                "all_unique": bool(observation_ids.is_unique),
                "note": (
                    "Observation IDs are an opaque supplied identifier. No documented "
                    "algorithm defines them, so they are not re-derived; they are "
                    "preserved unchanged in the canonical baseline."
                ),
            },
            "reproduced_parquet": {
                "path": output_path.relative_to(PROJECT_ROOT).as_posix(),
                "bytes": output_path.stat().st_size,
                "sha256": sha256_file(output_path),
            },
        }
        report["per_sensor"][sensor_key] = sensor_report

        total_rows += len(baseline)
        total_mismatch_cells += int(sum(comparison["mismatch_counts"].values()))
        total_mismatch_rows += int(comparison["mismatched_rows"])
        all_exact = all_exact and bool(comparison["exact_match"])

        print(
            f"[l1-repro] {sensor_key}: rows={len(baseline)} "
            f"columns={comparison['columns_compared']} "
            f"mismatched_cells={sum(comparison['mismatch_counts'].values())}"
        )

    report["overall"] = {
        "rows": total_rows,
        "columns_compared": len(reproduced_columns(next(iter(SENSOR_SPECS)))),
        "mismatch_cells": total_mismatch_cells,
        "mismatched_rows": total_mismatch_rows,
        "exact_match_all_sensors": all_exact,
        "observation_ids_reproduced": False,
        "conclusion": (
            "All 28 observable cleaned columns reproduce exactly for all three "
            "sensors. Observation IDs are supplied and preserved, not regenerated."
            if all_exact
            else "Differences exist; see per-sensor mismatch counts and examples."
        ),
    }

    write_json(REPORT_PATH, report)
    print(f"[l1-repro] wrote {REPORT_PATH}")
    print(f"[l1-repro] exact_match_all_sensors={all_exact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
