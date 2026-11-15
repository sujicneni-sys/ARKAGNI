"""Project paths and frozen constants.

Only values that are externally specified (documented data hash, sensor file
order) live here. Everything else is derived at runtime.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

SOURCE_ARCHIVE = PROJECT_ROOT / "NASA_SpaceApps_Task2_Completed.zip"

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
RAW_TREE = RAW_DIR / "NASA_Fire_Data_Engine"
INTERIM_DIR = DATA_DIR / "interim"
PROCESSED_DIR = DATA_DIR / "processed"
QUARANTINE_DIR = DATA_DIR / "quarantine"

ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
MANIFEST_DIR = ARTIFACTS_DIR / "manifests"
REPORT_DIR = ARTIFACTS_DIR / "reports"
DOCS_DIR = PROJECT_ROOT / "docs"

MANIFEST_SCHEMA_VERSION = "phase0.manifest.v1"

# Documented in `final system architecture.docx`: SHA-256 of the three
# per-file digests concatenated in order MODIS, SNPP, NOAA-20.
DOCUMENTED_DATA_HASH = (
    "37423f49d2235a911caaebbdc660388ed7e775333ae7f224672342720adf8290"
)
DOCUMENTED_DATA_HASH_PREFIX = "37423f49d223"

# Sensor order is part of the documented hash definition. Do not reorder.
SENSOR_ORDER = ("MODIS", "VIIRS_SNPP", "VIIRS_NOAA20")

CLEANED_FILES = {
    "MODIS": "data/cleaned/MODIS_SP_cleaned.csv",
    "VIIRS_SNPP": "data/cleaned/VIIRS_SNPP_SP_cleaned.csv",
    "VIIRS_NOAA20": "data/cleaned/VIIRS_NOAA20_SP_cleaned.csv",
}

RAW_FILES = {
    "MODIS": "data/raw/MODIS_SP_raw.csv",
    "VIIRS_SNPP": "data/raw/VIIRS_SNPP_SP_raw.csv",
    "VIIRS_NOAA20": "data/raw/VIIRS_NOAA20_SP_raw.csv",
}

MASTER_CSV = "data/processed/NASA_Fire_Harmonized_Master.csv"
MASTER_JSONL = "data/processed/NASA_Fire_Harmonized_Master.jsonl"

# Headline counts the rebuild must reproduce. These are assertions about the
# supplied data, not inputs to any computation.
EXPECTED_MASTER_ROWS = 1_382_752
EXPECTED_TOTAL_RAW_ROWS = 1_382_752

MANIFEST_PATH = MANIFEST_DIR / "phase0_manifest.json"
CSV_JSONL_REPORT_PATH = REPORT_DIR / "csv_jsonl_comparison.json"
