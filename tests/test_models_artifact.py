"""Served-model tests against the real fitted artefact.

The artefact hash is checked against the published results file, so a stale or
hand-edited model cannot silently pass.
"""

from __future__ import annotations

import hashlib
import json
import pickle

import numpy as np
import pandas as pd
import pytest

from pyroharmonize import config
from pyroharmonize.models import (
    DELAY_BIN_LABELS,
    MIN_CALIBRATION_PAIRS,
    conformal_quantile,
    predict_harmonized,
    predict_models,
)

RESULTS_PATH = config.ARTIFACTS_DIR / "results" / "results.json"
PAIRS_PATH = config.PROCESSED_DIR / "pairs_aqua_snpp.parquet"


@pytest.fixture(scope="module")
def results() -> dict:
    if not RESULTS_PATH.is_file():
        pytest.fail(f"missing {RESULTS_PATH}; run scripts\\03_run_analysis.py --force")
    return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def artifact(results: dict) -> dict:
    path = config.PROJECT_ROOT / results["provenance"]["model_artifact"]
    if not path.is_file():
        pytest.fail(f"missing model artefact {path}")
    with path.open("rb") as handle:
        return pickle.load(handle)


@pytest.fixture(scope="module")
def pairs() -> pd.DataFrame:
    return pd.read_parquet(PAIRS_PATH)


def test_artifact_hash_matches_results(results: dict) -> None:
    path = config.PROJECT_ROOT / results["provenance"]["model_artifact"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == results["provenance"]["model_artifact_sha256"]


def test_served_model_and_gate_shape(results: dict, artifact: dict) -> None:
    assert results["models"]["served"] == "H"
    assert artifact["served_model"] == "H"
    assert set(artifact["conformal"]["bins"]) == set(DELAY_BIN_LABELS)
    assert set(artifact["gate"]["bins"]) == set(DELAY_BIN_LABELS)
    assert artifact["gate"]["coverage_floor"] == 0.70
    assert artifact["gate"]["min_calibration_pairs"] == MIN_CALIBRATION_PAIRS


def test_conformal_quantile_finite_sample_rank() -> None:
    values = np.arange(1, 11, dtype="float64")
    # ceil((10 + 1) * 0.8) = 9 -> the 9th order statistic.
    assert conformal_quantile(values, alpha=0.20) == 9.0
    assert conformal_quantile(np.array([]), alpha=0.20) == float("inf")


def test_real_pairs_applicability_counts(artifact: dict, pairs: pd.DataFrame) -> None:
    output = predict_harmonized(pairs, artifact)
    assert int(output["applicable"].sum()) == 6136
    reasons = output["reason"].value_counts(dropna=False).to_dict()
    assert reasons[np.nan] == 6136
    assert reasons["delay_outside_calibrated_range"] == 128
    assert reasons["scan_out_of_range"] == 49


def test_intervals_contain_point_and_are_positive(artifact: dict, pairs: pd.DataFrame) -> None:
    output = predict_harmonized(pairs, artifact)
    valid = output[output["applicable"]]
    assert (valid["interval_lower_mw"] > 0).all()
    assert (valid["interval_upper_mw"] > valid["interval_lower_mw"]).all()
    assert (
        (valid["interval_lower_mw"] <= valid["harmonized_frp_mw"])
        & (valid["harmonized_frp_mw"] <= valid["interval_upper_mw"])
    ).all()


def test_refused_rows_have_no_number(artifact: dict, pairs: pd.DataFrame) -> None:
    output = predict_harmonized(pairs, artifact)
    refused = output[~output["applicable"]]
    assert refused["harmonized_frp_mw"].isna().all()
    assert refused["interval_lower_mw"].isna().all()
    assert refused["reason"].notna().all()


def test_prediction_is_deterministic(artifact: dict, pairs: pd.DataFrame) -> None:
    first = predict_harmonized(pairs.head(250), artifact)
    second = predict_harmonized(pairs.head(250), artifact)
    pd.testing.assert_frame_equal(first, second)


def test_seven_model_predictions(artifact: dict, pairs: pd.DataFrame) -> None:
    # Build a ModelSet-compatible object from the serialized artefact.
    from pyroharmonize.models import ModelSet

    model_set = ModelSet(
        y_mean=artifact["y_mean"],
        region_means=artifact["region_means"],
        p_params=artifact["p_params"],
        h_params=artifact["h_params"],
        m_model=artifact["m_model"],
        pr_residual_model=artifact["pr_residual_model"],
        feature_names=tuple(artifact["feature_names"]),
    )
    predictions = predict_models(model_set, pairs.head(100))
    assert set(predictions) == {"B0", "B1", "B2", "P", "H", "M", "PR"}
    for values in predictions.values():
        assert len(values) == 100
        assert np.isfinite(values).all()


def test_gate_refuses_late_bin_below_coverage_floor(artifact: dict) -> None:
    late = artifact["gate"]["bins"]["(2, 3.5]"]
    assert late["calibration_n"] >= MIN_CALIBRATION_PAIRS
    assert late["coverage"] < artifact["gate"]["coverage_floor"]
    assert late["applicable"] is False
    assert late["reason"] == "coverage_below_floor"
