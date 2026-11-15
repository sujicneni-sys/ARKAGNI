"""Phase 0: freeze the supplied archive and generate a provenance manifest.

This script never modifies the source archive. It extracts the archive exactly
once into ``data/raw`` and then marks every extracted file read-only. Re-runs
verify the existing tree against the archive instead of overwriting it.

Outputs
-------
artifacts/manifests/phase0_manifest.json
artifacts/reports/csv_jsonl_comparison.json

Run with:
    .venv\\Scripts\\python.exe scripts\\00_freeze_inputs.py
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import re
import shutil
import sys
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pyroharmonize import config  # noqa: E402
from pyroharmonize.provenance import (  # noqa: E402
    compute_data_hash,
    count_jsonl_lines,
    first_jsonl_record,
    is_read_only,
    read_zip_manifest,
    safe_zip_target,
    set_read_only,
    sha256_file,
    verify_manifest,
    write_json,
)

PADDED_TIME = re.compile(r"^\d{4}$")

SPEC_DOCUMENTS = (
    "final system architecture.docx",
    "FireSync_MODIS_VIIRS Harmonization System.docx",
    "Implication Architecture.docx",
    "layoutnew.docx",
    "NASA SPACE APPS CHALLENGE 2026 Problem Statement.docx",
)


def extract_archive(archive: Path, raw_root: Path) -> bool:
    """Extract the archive into ``raw_root``. Returns True if extraction ran.

    Refuses to overwrite an existing non-empty target.
    """
    existing = [p for p in raw_root.rglob("*") if p.is_file()] if raw_root.exists() else []
    if existing:
        return False

    raw_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            target = safe_zip_target(raw_root, info.filename)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as source, open(target, "wb") as sink:
                shutil.copyfileobj(source, sink, length=8 * 1024 * 1024)
    return True


def verify_against_archive(archive_entries: list[dict], raw_root: Path) -> list[str]:
    """Verify extracted files byte-for-byte against archive entries."""
    problems: list[str] = []
    expected = {entry["path"]: entry for entry in archive_entries}
    on_disk = {
        p.relative_to(raw_root).as_posix(): p
        for p in raw_root.rglob("*")
        if p.is_file()
    }

    for name, entry in expected.items():
        path = on_disk.get(name)
        if path is None:
            problems.append(f"missing after extraction: {name}")
            continue
        if path.stat().st_size != entry["bytes"]:
            problems.append(f"size mismatch after extraction: {name}")
            continue
        if sha256_file(path) != entry["sha256"]:
            problems.append(f"sha256 mismatch after extraction: {name}")

    for extra in sorted(set(on_disk) - set(expected)):
        problems.append(f"unexpected file after extraction: {extra}")

    return problems


def inspect_csv(path: Path, group_columns: tuple[str, ...], time_column: str | None) -> dict:
    """Single pass over a CSV returning row count, header, groupings, time stats."""
    groups: dict[str, Counter] = {column: Counter() for column in group_columns}
    time_stats = Counter()
    time_examples: dict[str, list[str]] = {}
    header: list[str] = []
    rows = 0

    with open(path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            return {"rows": 0, "columns": [], "groups": {}, "time_format": None}

        index = {name: position for position, name in enumerate(header)}
        group_indices = {
            column: index[column] for column in group_columns if column in index
        }
        time_index = index.get(time_column) if time_column else None

        for row in reader:
            rows += 1
            for column, position in group_indices.items():
                value = row[position] if position < len(row) else ""
                groups[column][value] += 1

            if time_index is None:
                continue
            value = row[time_index] if time_index < len(row) else ""
            if value == "":
                category = "empty"
            elif PADDED_TIME.match(value):
                category = "padded_4_digit"
            elif value.isdigit() and len(value) in (1, 2, 3):
                category = f"unpadded_{len(value)}_digit"
            else:
                category = "other"
            time_stats[category] += 1
            time_examples.setdefault(category, [])
            if len(time_examples[category]) < 5 and value not in time_examples[category]:
                time_examples[category].append(value)

    return {
        "rows": rows,
        "columns": header,
        "column_count": len(header),
        "groups": {
            column: dict(counter.most_common()) for column, counter in groups.items()
        },
        "time_format": {
            "column": time_column,
            "counts": dict(time_stats),
            "total": sum(time_stats.values()),
            "examples": time_examples,
        }
        if time_index is not None
        else None,
    }


def inspect_jsonl(path: Path, sample_size: int = 1000) -> dict:
    """Count lines and inspect the first records for field names and types."""
    lines = count_jsonl_lines(path)
    keys: list[str] = []
    type_counts: Counter = Counter()
    time_values: list[object] = []

    with open(path, "r", encoding="utf-8") as handle:
        for position, line in enumerate(handle):
            if position >= sample_size:
                break
            record = json.loads(line)
            if not keys:
                keys = list(record.keys())
            if "acquisition_time_utc" in record:
                value = record["acquisition_time_utc"]
                type_counts[type(value).__name__] += 1
                if len(time_values) < 5:
                    time_values.append(value)

    return {
        "lines": lines,
        "columns": keys,
        "column_count": len(keys),
        "sample_size": sample_size,
        "acquisition_time_utc_types": dict(type_counts),
        "acquisition_time_utc_examples": time_values,
    }


def archive_prefix(entries: list[dict]) -> str:
    """Return the single top-level directory shared by every archive entry."""
    if not entries:
        raise ValueError("archive contains no file entries")
    top_level = entries[0]["path"].split("/", 1)[0]
    prefix = f"{top_level}/"
    if not all(entry["path"].startswith(prefix) for entry in entries):
        raise ValueError("archive entries do not share one top-level directory")
    return prefix


def build_manifest(archive: Path, raw_root: Path, archive_entries: list[dict], extraction_ran: bool) -> dict:
    prefix = archive_prefix(archive_entries)
    normalized = [
        {**entry, "path": entry["path"][len(prefix):]} for entry in archive_entries
    ]
    relative_files = [entry["path"] for entry in normalized]

    master_csv_rel = config.MASTER_CSV
    master_jsonl_rel = config.MASTER_JSONL
    raw_tree = raw_root / prefix.rstrip("/")

    csv_stats: dict[str, dict] = {}
    for rel_path in relative_files:
        if not rel_path.endswith(".csv"):
            continue
        is_master = rel_path == master_csv_rel
        csv_stats[rel_path] = inspect_csv(
            raw_tree / rel_path,
            group_columns=("satellite", "sampling_region") if is_master else (),
            time_column="acquisition_time_utc" if is_master else None,
        )

    jsonl_stats: dict[str, dict] = {}
    for rel_path in relative_files:
        if rel_path.endswith(".jsonl"):
            jsonl_stats[rel_path] = inspect_jsonl(raw_tree / rel_path)

    file_entries = []
    for entry in normalized:
        rel_path = entry["path"]
        path = raw_tree / rel_path
        record = {
            "path": rel_path,
            "bytes": entry["bytes"],
            "compressed_bytes": entry["compressed_bytes"],
            "crc32": entry["crc32"],
            "sha256": entry["sha256"],
            "read_only": is_read_only(path),
        }
        if rel_path in csv_stats:
            record["kind"] = "csv"
            record["rows"] = csv_stats[rel_path]["rows"]
            record["column_count"] = csv_stats[rel_path]["column_count"]
        elif rel_path in jsonl_stats:
            record["kind"] = "jsonl"
            record["rows"] = jsonl_stats[rel_path]["lines"]
            record["column_count"] = jsonl_stats[rel_path]["column_count"]
        else:
            record["kind"] = "other"
        file_entries.append(record)

    digests = {entry["path"]: entry["sha256"] for entry in normalized}

    def data_hash_for(mapping: dict[str, str]) -> str:
        return compute_data_hash(
            {sensor: digests[mapping[sensor]] for sensor in config.SENSOR_ORDER},
            config.SENSOR_ORDER,
        )

    cleaned_hash = data_hash_for({s: config.CLEANED_FILES[s] for s in config.SENSOR_ORDER})
    raw_hash = data_hash_for({s: config.RAW_FILES[s] for s in config.SENSOR_ORDER})
    candidates = {
        "cleaned_csv_in_sensor_order": cleaned_hash,
        "raw_csv_in_sensor_order": raw_hash,
    }
    matched = [name for name, value in candidates.items() if value == config.DOCUMENTED_DATA_HASH]

    master_stats = csv_stats[master_csv_rel]
    satellite_counts = master_stats["groups"].get("satellite", {})
    region_counts = master_stats["groups"].get("sampling_region", {})

    expected_sensor_counts = {
        "Terra": 39_029,
        "Aqua": 127_704,
        "N": 545_196,
        "N20": 670_823,
    }

    manifest = {
        "schema_version": config.MANIFEST_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "source_archive": {
            "path": archive.name,
            "bytes": archive.stat().st_size,
            "sha256": sha256_file(archive),
            "file_entries": len(archive_entries),
        },
        "source_documents": [
            {
                "path": name,
                "bytes": (PROJECT_ROOT / name).stat().st_size,
                "sha256": sha256_file(PROJECT_ROOT / name),
                "preserved": True,
            }
            for name in SPEC_DOCUMENTS
            if (PROJECT_ROOT / name).is_file()
        ],
        "raw_root": raw_tree.as_posix(),
        "extraction_ran": extraction_ran,
        "immutable": all(entry["read_only"] for entry in file_entries),
        "files": file_entries,
        "stats": {
            "csv": csv_stats,
            "jsonl": jsonl_stats,
        },
        "verification": {
            "master_rows": master_stats["rows"],
            "master_columns": master_stats["column_count"],
            "master_rows_expected": config.EXPECTED_MASTER_ROWS,
            "master_rows_match": master_stats["rows"] == config.EXPECTED_MASTER_ROWS,
            "jsonl_rows": jsonl_stats[master_jsonl_rel]["lines"],
            "csv_jsonl_row_count_equal": master_stats["rows"] == jsonl_stats[master_jsonl_rel]["lines"],
            "satellite_counts": satellite_counts,
            "satellite_counts_expected": expected_sensor_counts,
            "satellite_counts_match": {
                name: satellite_counts.get(name) == count
                for name, count in expected_sensor_counts.items()
            },
            "region_counts": region_counts,
            "master_time_format": master_stats["time_format"],
        },
        "data_hash": {
            "definition": "sha256(concat(per-file sha256 hex in order MODIS, VIIRS_SNPP, VIIRS_NOAA20))",
            "expected_documented": config.DOCUMENTED_DATA_HASH,
            "candidates": candidates,
            "matched_candidates": matched,
            "verified": len(matched) == 1,
            "canonical_source": matched[0] if len(matched) == 1 else None,
        },
    }
    return manifest


def build_comparison_report(manifest: dict) -> dict:
    """Record structural CSV/JSONL differences without choosing a canonical form."""
    master_csv = manifest["stats"]["csv"][config.MASTER_CSV]
    master_jsonl = manifest["stats"]["jsonl"][config.MASTER_JSONL]

    csv_columns = set(master_csv["columns"])
    jsonl_columns = set(master_jsonl["columns"])
    time_counts = master_csv["time_format"]["counts"]

    return {
        "schema_version": "phase0.csv_jsonl_comparison.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_archive_sha256": manifest["source_archive"]["sha256"],
        "row_counts": {
            "csv": master_csv["rows"],
            "jsonl": master_jsonl["lines"],
            "equal": master_csv["rows"] == master_jsonl["lines"],
        },
        "columns": {
            "csv_count": len(csv_columns),
            "jsonl_count": len(jsonl_columns),
            "sets_equal": csv_columns == jsonl_columns,
            "only_csv": sorted(csv_columns - jsonl_columns),
            "only_jsonl": sorted(jsonl_columns - csv_columns),
        },
        "acquisition_time_utc": {
            "csv_storage_type": "string",
            "csv_format_counts": time_counts,
            "csv_non_padded_or_empty": sum(
                count for key, count in time_counts.items() if key != "padded_4_digit"
            ),
            "jsonl_storage_type_sample": master_jsonl["acquisition_time_utc_types"],
            "jsonl_examples": master_jsonl["acquisition_time_utc_examples"],
            "semantics_documented": "Time is HHMM UTC; '118' means 01:18 and must be zero-padded to '0118' before parsing.",
            "differences": [
                "CSV preserves the zero-padded string form; JSONL stores the same field as a JSON number.",
                "A numeric 118 cannot be distinguished from HHMM 11:08 without the documented padding rule.",
            ],
        },
        "canonical_dataset_declared": False,
        "reason_not_declared": "Phase 0 freezes inputs only. Reconciliation and canonicalization are Phase 1 work.",
        "required_canonicalization": [
            "Normalize acquisition_time_utc to a validated HHMM value (00:00-23:59) with explicit leading zeros.",
            "Prove row-level equivalence between CSV and JSONL before selecting one as authoritative.",
            "Record the chosen authority and the equivalence evidence in the Phase 1 data contract.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=config.SOURCE_ARCHIVE)
    parser.add_argument("--raw-root", type=Path, default=config.RAW_DIR)
    parser.add_argument("--manifest", type=Path, default=config.MANIFEST_PATH)
    parser.add_argument("--comparison", type=Path, default=config.CSV_JSONL_REPORT_PATH)
    parser.add_argument(
        "--skip-hash",
        action="store_true",
        help="Skip re-hashing every extracted file (manifest still records archive hashes).",
    )
    args = parser.parse_args()

    if not args.archive.is_file():
        raise SystemExit(f"source archive not found: {args.archive}")

    print(f"[phase0] archive: {args.archive}")
    print("[phase0] hashing archive entries ...")
    archive_entries = read_zip_manifest(args.archive)
    print(f"[phase0] archive entries hashed: {len(archive_entries)}")

    extraction_ran = extract_archive(args.archive, args.raw_root)
    print(f"[phase0] extraction ran: {extraction_ran}")

    print("[phase0] verifying extracted tree against archive ...")
    problems = verify_against_archive(archive_entries, args.raw_root)
    if problems:
        for problem in problems:
            print(f"[phase0] ERROR {problem}")
        raise SystemExit("extracted tree does not match archive; refusing to continue")

    print("[phase0] setting extracted files read-only ...")
    for entry in archive_entries:
        set_read_only(args.raw_root / entry["path"])

    print("[phase0] building manifest (CSV/JSONL scans) ...")
    manifest = build_manifest(args.archive, args.raw_root, archive_entries, extraction_ran)

    if not args.skip_hash:
        print("[phase0] verifying manifest against read-only tree ...")
        problems = verify_manifest(manifest, Path(manifest["raw_root"]))
        if problems:
            for problem in problems:
                print(f"[phase0] ERROR {problem}")
            raise SystemExit("manifest verification failed")
        print("[phase0] manifest verification passed")

    if not manifest["data_hash"]["verified"]:
        print("[phase0] WARNING: documented data_hash not reproduced by known candidates")
        print(json.dumps(manifest["data_hash"], indent=2))

    write_json(args.manifest, manifest)
    print(f"[phase0] wrote {args.manifest}")

    comparison = build_comparison_report(manifest)
    write_json(args.comparison, comparison)
    print(f"[phase0] wrote {args.comparison}")

    print(
        "[phase0] summary: "
        f"master_rows={manifest['verification']['master_rows']} "
        f"satellite_match={manifest['verification']['satellite_counts_match']} "
        f"data_hash_match={manifest['data_hash']['matched_candidates']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
