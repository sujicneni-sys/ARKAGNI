"""Build the canonical L1 dataset from the frozen cleaned baseline.

The supplied cleaned CSVs are the L1 authority (owner decision U-02/C-15).
This script:

1. re-verifies every frozen input hash;
2. types the baseline and adds explicit timestamp/FRP/validity fields;
3. writes ``data/processed/l1_canonical.parquet``;
4. compares master CSV and JSONL semantically;
5. records a manifest with input and output hashes.

No raw or frozen file is written.

Run with:
    .venv\\Scripts\\python.exe scripts\\02_l1_build_canonical.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pyroharmonize import config  # noqa: E402
from pyroharmonize.equivalence import compare_master  # noqa: E402
from pyroharmonize.l1 import (  # noqa: E402
    L1_DERIVED_COLUMNS,
    L1_DUPLICATE_ID,
    L1_FRP_STATUS,
    L1_QUALITY_STATUS,
    L1_SENSOR_KEY,
    L1_TIME_HHMM,
    L1_TIME_STATUS,
    L1_TIME_WAS_PADDED,
    L1_TIMESTAMP,
    L1_ZERO_FRP,
    SENSOR_SPECS,
    apply_duplicate_flags,
    build_canonical_frame,
)
from pyroharmonize.provenance import (  # noqa: E402
    sha256_file,
    verify_manifest,
    write_json,
)

CANONICAL_PATH = config.PROCESSED_DIR / "l1_canonical.parquet"
MANIFEST_PATH = config.MANIFEST_DIR / "l1_manifest.json"
QC_PATH = config.REPORT_DIR / "l1_qc.json"
EQUIVALENCE_PATH = config.REPORT_DIR / "l1_csv_jsonl_equivalence.json"

RULES_VERSION = "l1-rules-v1"


def _counts(series: pd.Series) -> dict[str, int]:
    counts = series.value_counts(dropna=False)
    return {str(key): int(value) for key, value in counts.items()}


def main() -> int:
    phase0 = json.loads(config.MANIFEST_PATH.read_text(encoding="utf-8"))
    hash_by_path = {entry["path"]: entry["sha256"] for entry in phase0["files"]}

    print("[l1-build] verifying frozen tree against Phase 0 manifest ...")
    problems = verify_manifest(phase0, Path(phase0["raw_root"]))
    if problems:
        for problem in problems:
            print(f"[l1-build] ERROR {problem}")
        raise SystemExit("frozen inputs changed; refusing to build canonical data")

    frames = []
    input_records: dict[str, dict] = {}
    row_offset = 0

    for sensor_key, spec in SENSOR_SPECS.items():
        cleaned_path = config.RAW_TREE / spec["cleaned"]
        recorded_hash = hash_by_path[spec["cleaned"]]
        actual_hash = sha256_file(cleaned_path)
        if actual_hash != recorded_hash:
            raise SystemExit(f"cleaned input hash changed: {cleaned_path}")

        print(f"[l1-build] {sensor_key}: typing cleaned baseline ...")
        cleaned = pd.read_csv(cleaned_path, dtype=str, keep_default_na=False)
        frame = build_canonical_frame(
            cleaned,
            sensor_key=sensor_key,
            source_file=Path(spec["cleaned"]).name,
            row_offset=row_offset,
        )
        frames.append(frame)
        row_offset += len(frame)
        input_records[sensor_key] = {
            "path": spec["cleaned"],
            "sha256": actual_hash,
            "bytes": cleaned_path.stat().st_size,
            "rows": int(len(frame)),
        }

    print("[l1-build] concatenating and checking duplicate IDs ...")
    canonical = pd.concat(frames, ignore_index=True)
    canonical = apply_duplicate_flags(canonical)

    CANONICAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    canonical.to_parquet(CANONICAL_PATH, index=False, compression="zstd")

    print("[l1-build] computing QC metrics ...")
    duplicate_ids = int(canonical[L1_DUPLICATE_ID].sum())
    time_status = _counts(canonical[L1_TIME_STATUS])
    frp_status = _counts(canonical[L1_FRP_STATUS])
    quality_status = _counts(canonical[L1_QUALITY_STATUS])
    invalid_frp_with_zero = int(
        (
            (canonical[L1_QUALITY_STATUS] == "invalid_frp")
            & (canonical[L1_ZERO_FRP])
        ).sum()
    )

    qc = {
        "schema_version": "l1.qc.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "rows": int(len(canonical)),
        "columns": int(len(canonical.columns)),
        "duplicate_observation_ids": duplicate_ids,
        "unique_observation_ids": int(canonical["observation_id"].nunique()),
        "rows_by_sensor": _counts(canonical[L1_SENSOR_KEY]),
        "rows_by_platform": _counts(canonical["satellite"]),
        "rows_by_region": _counts(canonical["sampling_region"]),
        "date_range": {
            "min": canonical["acquisition_date"].min().date().isoformat(),
            "max": canonical["acquisition_date"].max().date().isoformat(),
        },
        "time": {
            "status_counts": time_status,
            "was_padded_count": int(canonical[L1_TIME_WAS_PADDED].sum()),
            "normalized_all_valid": set(time_status) == {"valid"},
        },
        "frp": {
            "status_counts": frp_status,
            "zero_frp_rows": int(canonical[L1_ZERO_FRP].sum()),
            "zero_frp_treated_as_invalid": invalid_frp_with_zero,
        },
        "quality_status_counts": quality_status,
        "invalid_coordinates": int(
            canonical["l1_validity_invalid_coords"].sum()
        ),
        "invalid_scan_track": int(
            canonical["l1_validity_invalid_scan_track"].sum()
        ),
        "null_counts": {
            column: int(value) for column, value in canonical.isna().sum().items()
        },
        "dtypes": {
            column: str(dtype) for column, dtype in canonical.dtypes.items()
        },
        "timestamp_nulls": int(canonical[L1_TIMESTAMP].isna().sum()),
        "time_hhmm_nulls": int(canonical[L1_TIME_HHMM].isna().sum()),
    }

    print("[l1-build] comparing master CSV and JSONL semantically ...")
    master_csv_path = config.RAW_TREE / config.MASTER_CSV
    master_jsonl_path = config.RAW_TREE / config.MASTER_JSONL
    master_columns = pd.read_csv(master_csv_path, nrows=0).columns.tolist()
    comparison = compare_master(
        str(master_csv_path), str(master_jsonl_path), master_columns
    )
    equivalence = {
        "schema_version": "l1.csv_jsonl_equivalence.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "csv": {
            "path": config.MASTER_CSV,
            "sha256": sha256_file(master_csv_path),
        },
        "jsonl": {
            "path": config.MASTER_JSONL,
            "sha256": sha256_file(master_jsonl_path),
        },
        "comparison": comparison,
        "note": (
            "Master acquisition_time_utc equals master acq_time for every row; the "
            "master lost the cleaned file's four-digit normalization. Both encodings "
            "normalize to the same HHMM value, so this is a storage defect, not a "
            "semantic difference. The canonical L1 dataset uses the cleaned "
            "acquisition_time_utc, which is fully four-digit."
        ),
        "conclusion": (
            "CSV and JSONL are semantically equivalent after explicit time "
            "normalization."
            if comparison["semantically_equivalent"]
            else "Semantic differences exist; see mismatched_columns."
        ),
    }

    write_json(QC_PATH, qc)
    write_json(EQUIVALENCE_PATH, equivalence)

    manifest = {
        "schema_version": "l1.manifest.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "phase0": {
            "archive_sha256": phase0["source_archive"]["sha256"],
            "manifest": config.MANIFEST_PATH.relative_to(PROJECT_ROOT).as_posix(),
            "manifest_sha256": sha256_file(config.MANIFEST_PATH),
        },
        "rules": {
            "version": RULES_VERSION,
            "module": "src/pyroharmonize/l1.py",
            "module_sha256": sha256_file(
                PROJECT_ROOT / "src" / "pyroharmonize" / "l1.py"
            ),
            "equivalence_module_sha256": sha256_file(
                PROJECT_ROOT / "src" / "pyroharmonize" / "equivalence.py"
            ),
            "build_script_sha256": sha256_file(Path(__file__)),
        },
        "inputs": input_records,
        "output": {
            "path": CANONICAL_PATH.relative_to(PROJECT_ROOT).as_posix(),
            "bytes": CANONICAL_PATH.stat().st_size,
            "sha256": sha256_file(CANONICAL_PATH),
            "rows": int(len(canonical)),
            "columns": int(len(canonical.columns)),
            "column_order": list(canonical.columns),
            "derived_columns": list(L1_DERIVED_COLUMNS),
        },
        "checks": {
            "frozen_inputs_unchanged": True,
            "unique_observation_ids": duplicate_ids == 0,
            "all_times_valid": set(time_status) == {"valid"},
            "zero_frp_not_invalid": invalid_frp_with_zero == 0,
            "canonical_rows_match_baseline": int(len(canonical))
            == config.EXPECTED_MASTER_ROWS,
        },
        "qc_report": QC_PATH.relative_to(PROJECT_ROOT).as_posix(),
        "equivalence_report": EQUIVALENCE_PATH.relative_to(PROJECT_ROOT).as_posix(),
    }
    write_json(MANIFEST_PATH, manifest)

    print(f"[l1-build] wrote {CANONICAL_PATH}")
    print(f"[l1-build] wrote {QC_PATH}")
    print(f"[l1-build] wrote {EQUIVALENCE_PATH}")
    print(f"[l1-build] wrote {MANIFEST_PATH}")
    print(
        "[l1-build] summary: "
        f"rows={len(canonical)} zero_frp={qc['frp']['zero_frp_rows']} "
        f"time_padded={qc['time']['was_padded_count']} "
        f"dup_ids={duplicate_ids} "
        f"csv_jsonl_equivalent={comparison['semantically_equivalent']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
