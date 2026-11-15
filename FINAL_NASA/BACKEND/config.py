"""Project configuration and hash-verified artifact registry.

The scientific block in ``config.yaml`` is canonical.  Its sorted-key JSON
serialisation is the value published as ``aggregator_config_hash``; the service
refuses requests whose hash does not match.  This module performs file reads
only at process start-up.  The L5 core never imports it.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
BACKEND_DIR = Path(__file__).resolve().parent
ARTIFACTS_DIR = BACKEND_DIR / "artifacts"
REGISTRY_PATH = ARTIFACTS_DIR / "registry.json"
DATA_DIR = PROJECT_ROOT / "data"
PROCESSED_DIR = DATA_DIR / "processed"
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"

# Only these keys participate in the scientific hash.  Keep this list stable:
# adding an operational key must not silently change every historical result.
SCIENCE_KEYS: tuple[str, ...] = (
    "reference_lst_h",
    "delay_bins",
    "alpha",
    "coverage_floor",
    "min_calibration_pairs",
    "ridge_lambda",
    "cell_definition",
    "validation_rule",
)


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise RuntimeError("config.yaml must contain a mapping")
    missing = [key for key in SCIENCE_KEYS if key not in payload]
    if missing:
        raise RuntimeError(f"config.yaml is missing science keys: {missing}")
    return payload


def science_payload(config: dict[str, Any] | None = None) -> dict[str, Any]:
    source = config or load_config()
    return {key: source[key] for key in SCIENCE_KEYS}


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def config_hash(config: dict[str, Any] | None = None) -> str:
    """SHA-256 of the sorted science block.

    The published pipeline used ``json.dumps(..., sort_keys=True)`` without
    separators.  To remain byte-compatible with the frozen artifact, use the
    same serialisation here and verify the result against results.json.
    """
    source = config or load_config()
    encoded = json.dumps(science_payload(source), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@lru_cache(maxsize=1)
def load_registry() -> dict[str, Any]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
