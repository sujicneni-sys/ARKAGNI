"""Integration tests for the Phase 0 frozen-input manifest.

These tests read the real archive and the real extracted files. They fail if
the manifest is missing or if any byte recorded in it has changed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pyroharmonize import config
from pyroharmonize.provenance import sha256_file, verify_manifest


@pytest.fixture(scope="module")
def manifest() -> dict:
    if not config.MANIFEST_PATH.is_file():
        pytest.fail(
            f"missing {config.MANIFEST_PATH}; run scripts\\00_freeze_inputs.py first"
        )
    return json.loads(config.MANIFEST_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def comparison() -> dict:
    if not config.CSV_JSONL_REPORT_PATH.is_file():
        pytest.fail(
            f"missing {config.CSV_JSONL_REPORT_PATH}; run scripts\\00_freeze_inputs.py first"
        )
    return json.loads(config.CSV_JSONL_REPORT_PATH.read_text(encoding="utf-8"))


def test_manifest_schema(manifest: dict) -> None:
    assert manifest["schema_version"] == config.MANIFEST_SCHEMA_VERSION
    assert manifest["files"], "manifest records no files"
    assert manifest["immutable"] is True


def test_source_archive_unchanged(manifest: dict) -> None:
    archive = config.SOURCE_ARCHIVE
    if not archive.is_file():
        pytest.skip(
            f"source archive {archive.name} is not present in this checkout; "
            "the extracted and hashed raw tree is still verified below"
        )
    recorded = manifest["source_archive"]
    assert archive.stat().st_size == recorded["bytes"]
    assert sha256_file(archive) == recorded["sha256"]


def test_source_documents_preserved(manifest: dict) -> None:
    documents = manifest["source_documents"]
    assert len(documents) == 5
    for entry in documents:
        path = config.PROJECT_ROOT / entry["path"]
        assert path.is_file(), entry["path"]
        assert path.stat().st_size == entry["bytes"]
        assert sha256_file(path) == entry["sha256"]


def test_every_raw_file_matches_manifest(manifest: dict) -> None:
    problems = verify_manifest(manifest, config.RAW_TREE)
    assert problems == []


def test_all_raw_files_are_read_only(manifest: dict) -> None:
    assert all(entry["read_only"] for entry in manifest["files"])


def test_master_row_and_column_counts(manifest: dict) -> None:
    verification = manifest["verification"]
    assert verification["master_rows"] == config.EXPECTED_MASTER_ROWS
    assert verification["master_rows_match"] is True
    assert verification["master_columns"] == 33
    assert verification["csv_jsonl_row_count_equal"] is True
    assert verification["jsonl_rows"] == config.EXPECTED_MASTER_ROWS


def test_per_sensor_source_counts_sum_to_master(manifest: dict) -> None:
    stats = manifest["stats"]["csv"]

    raw_rows = sum(stats[path]["rows"] for path in config.RAW_FILES.values())
    cleaned_rows = sum(stats[path]["rows"] for path in config.CLEANED_FILES.values())

    assert raw_rows == config.EXPECTED_TOTAL_RAW_ROWS
    assert cleaned_rows == config.EXPECTED_MASTER_ROWS
    assert stats[config.MASTER_CSV]["rows"] == config.EXPECTED_MASTER_ROWS


def test_master_satellite_counts(manifest: dict) -> None:
    verification = manifest["verification"]
    assert verification["satellite_counts"] == {
        "Terra": 39_029,
        "Aqua": 127_704,
        "N": 545_196,
        "N20": 670_823,
    }
    assert all(verification["satellite_counts_match"].values())


def test_region_counts_cover_all_rows(manifest: dict) -> None:
    verification = manifest["verification"]
    regions = verification["region_counts"]
    assert set(regions) == {"Amazon", "Australia", "California", "Southern_Africa"}
    assert sum(regions.values()) == config.EXPECTED_MASTER_ROWS


def test_documented_data_hash_is_reproduced(manifest: dict) -> None:
    data_hash = manifest["data_hash"]
    assert data_hash["verified"] is True
    assert data_hash["canonical_source"] == "cleaned_csv_in_sensor_order"
    assert data_hash["candidates"]["cleaned_csv_in_sensor_order"] == config.DOCUMENTED_DATA_HASH
    assert data_hash["candidates"]["cleaned_csv_in_sensor_order"].startswith(
        config.DOCUMENTED_DATA_HASH_PREFIX
    )


def test_master_time_format_is_measured(manifest: dict) -> None:
    time_format = manifest["verification"]["master_time_format"]
    assert time_format["column"] == "acquisition_time_utc"
    assert time_format["total"] == config.EXPECTED_MASTER_ROWS
    assert sum(time_format["counts"].values()) == config.EXPECTED_MASTER_ROWS
    # The documented invariant is full zero-padding; record the real violation.
    assert time_format["counts"].get("padded_4_digit", 0) > 0
    non_padded = sum(
        count
        for key, count in time_format["counts"].items()
        if key != "padded_4_digit"
    )
    assert non_padded > 0


def test_csv_jsonl_comparison_report(comparison: dict) -> None:
    assert comparison["row_counts"]["equal"] is True
    assert comparison["row_counts"]["csv"] == config.EXPECTED_MASTER_ROWS
    assert comparison["columns"]["sets_equal"] is True
    assert comparison["columns"]["only_csv"] == []
    assert comparison["columns"]["only_jsonl"] == []
    assert comparison["acquisition_time_utc"]["csv_non_padded_or_empty"] > 0
    assert comparison["canonical_dataset_declared"] is False
    assert len(comparison["required_canonicalization"]) >= 1


def test_comparison_time_counts_agree_with_manifest(manifest: dict, comparison: dict) -> None:
    manifest_counts = manifest["verification"]["master_time_format"]["counts"]
    report_counts = comparison["acquisition_time_utc"]["csv_format_counts"]
    assert manifest_counts == report_counts
    assert sum(report_counts.values()) == config.EXPECTED_MASTER_ROWS


def test_manifests_written_as_valid_json(manifest: dict, comparison: dict) -> None:
    # Guards against accidental non-serializable values in generated reports.
    json.dumps(manifest)
    json.dumps(comparison)
    assert Path(config.MANIFEST_PATH).is_file()
