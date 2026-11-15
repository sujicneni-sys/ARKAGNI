"""Production-boundary tests for the reviewed L5/L6 implementation.

These tests exercise the real served artifact and the real FastAPI lifespan.
Nothing is mocked: a stale hash, an unverified pickle, or a science regression
must fail the suite.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend import config, core, main

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE = json.loads((PROJECT_ROOT / "data" / "fixtures" / "sample_request.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def config_payload(client: TestClient) -> dict:
    response = client.get("/config")
    assert response.status_code == 200
    return response.json()


@pytest.fixture(scope="module")
def artifact(client: TestClient) -> dict:
    return main.state.artifact


@pytest.fixture(scope="module")
def pairs() -> pd.DataFrame:
    return pd.read_parquet(config.PROCESSED_DIR / "pairs_aqua_snpp.parquet")


# ---------------------------------------------------------------------------
# Provenance and pure-core parity
# ---------------------------------------------------------------------------


def test_startup_verifies_every_artifact_hash(client: TestClient) -> None:
    registry = config.load_registry()
    assert main.state.model_sha256 == registry["model"]["sha256"]
    assert main.state.results_sha256 == registry["results"]["sha256"]
    assert config.sha256_file(config.ARTIFACTS_DIR / "conformal.json") == registry["conformal"]["sha256"]
    assert main.state.config_hash == config.config_hash()
    assert main.state.results["provenance"]["model_artifact_sha256"] == main.state.model_sha256
    assert main.state.results["provenance"]["config_hash"] == main.state.config_hash


def test_unverified_conformal_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    real_sha = config.sha256_file

    def fake_sha(path: Path) -> str:
        return "0" * 64 if Path(path).name == "conformal.json" else real_sha(path)

    monkeypatch.setattr(config, "sha256_file", fake_sha)
    with pytest.raises(RuntimeError, match="conformal.json hash mismatch"):
        main._load_state()


def test_pure_core_reproduces_documented_applicability(pairs: pd.DataFrame, artifact: dict) -> None:
    output = core.predict_harmonized(pairs, artifact)
    counts = output["reason"].value_counts(dropna=False).to_dict()
    assert len(output) == 6313
    assert int(output["applicable"].sum()) == 6136
    assert int(counts.get("delay_outside_calibrated_range", 0)) == 128
    assert int(counts.get("scan_out_of_range", 0)) == 49
    refused = output.loc[~output["applicable"]]
    assert refused["harmonized_frp_mw"].isna().all()
    assert refused["interval_lower_mw"].isna().all()
    assert refused["reason"].notna().all()


def test_core_is_deterministic(pairs: pd.DataFrame, artifact: dict) -> None:
    first = core.predict_harmonized(pairs.head(250), artifact)
    second = core.predict_harmonized(pairs.head(250), artifact)
    pd.testing.assert_frame_equal(first, second)


def test_lst_storage_and_rendering_contract() -> None:
    # 01:18 LST is stored as 118 but rendered as 01:18, never 11:08.
    assert core.lst_to_hhmm_int([1.3]).tolist() == [118]
    assert core.format_lst([1.3]) == ["01:18"]
    assert core.utc_hours_from_hhmm(["118", "0000", "2359"]).tolist() == pytest.approx(
        [1.3, 0.0, 23.983333333333334]
    )
    # lst = (UTC hours + longitude / 15) mod 24
    assert core.local_solar_time([12.0], [25.7])[0] == pytest.approx((12.0 + 25.7 / 15.0) % 24.0)


def test_pixel_flags_are_a_bitmask_not_a_filter() -> None:
    flags = core.pixel_flags(["0", "1", "0", "0"], [10.0, 10.0, 0.0, 10.0], ["D", "D", "D", "N"])
    assert flags.dtype == np.uint8
    assert flags.tolist() == [
        0,
        core.FLAG_TYPE_NOT_0,
        core.FLAG_FRP_NOT_POSITIVE,
        core.FLAG_NIGHT,
    ]
    assert core.validated_mask(flags).tolist() == [True, False, False, False]
    # Reserved bits remain unevaluated zeros.
    assert sorted(core.flag_counts(flags)) == ["frp_not_above_zero", "night", "type_not_0"]


def test_conformal_quantile_uses_finite_sample_rank() -> None:
    values = np.arange(1, 11, dtype="float64")
    assert core.conformal_quantile(values, alpha=0.20) == 9.0
    assert core.conformal_quantile([], alpha=0.20) == float("inf")


def test_gate_pre_registers_refusals(artifact: dict) -> None:
    gate = artifact["gate"]
    assert gate["min_calibration_pairs"] == 40
    assert gate["coverage_floor"] == 0.70
    late = gate["bins"]["(2, 3.5]"]
    assert late["calibration_n"] == 53
    assert late["coverage"] < 0.70
    assert late["applicable"] is False
    assert late["reason"] == "coverage_below_floor"
    assert core.SUPPORTED_REFUSALS == (
        "insufficient_calibration_pairs",
        "coverage_below_floor",
        "delay_outside_calibrated_range",
        "scan_out_of_range",
        "region_not_in_training",
    )


# ---------------------------------------------------------------------------
# Strict request validation and refusal mapping
# ---------------------------------------------------------------------------


def _payload(config_payload: dict, **overrides: object) -> dict:
    payload = {
        "aggregator_config_hash": config_payload["aggregator_config_hash"],
        "region": ["Southern_Africa"],
        "date": ["2021-08-01"],
        "latitude": [-12.3],
        "longitude": [25.7],
        "cell_lat": [-13],
        "cell_lon": [25],
        "frp_aqua_mw": [180.0],
        "detections": [12],
        "lst_aqua_h": [14.9],
        "scan_aqua": [1.1],
        "area_ratio": [1.2],
    }
    payload.update(overrides)
    return payload


def test_harmonize_accepts_the_published_example(client: TestClient, config_payload: dict) -> None:
    response = client.post("/harmonize", json=SAMPLE)
    assert response.status_code == 200
    body = response.json()
    cell = body["cells"][0]
    assert body["count"] == 1
    assert body["model"] == "H"
    assert cell["applicable"] is True
    assert cell["reason"] is None
    assert cell["region"] == "Southern_Africa"
    assert cell["cell"] == "S13E025"
    assert cell["cell_bounds"] == {"lat": [-13, -12], "lon": [25, 26]}
    assert cell["lst_display"] == "14:54"
    assert cell["delay_bin"] == "(1, 1.5]"
    assert cell["harmonized_frp_mw"] == pytest.approx(246.81056539023928)
    assert cell["interval_lower_mw"] == pytest.approx(71.78872940578282)
    assert cell["interval_upper_mw"] == pytest.approx(848.5378651003488)
    assert cell["interval_lower_mw"] < cell["harmonized_frp_mw"] < cell["interval_upper_mw"]
    assert body["provenance"]["model_artifact_sha256"] == main.state.model_sha256


def test_missing_lst_is_a_structured_422(client: TestClient, config_payload: dict) -> None:
    payload = _payload(config_payload)
    payload.pop("lst_aqua_h")
    response = client.post("/harmonize", json=payload)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "validation_error"
    assert any("lst_aqua_h" in field["message"] for field in detail["fields"])


def test_extra_fields_are_forbidden(client: TestClient, config_payload: dict) -> None:
    response = client.post("/harmonize", json=_payload(config_payload, pixel_level=["nope"]))
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "validation_error"
    assert any("pixel_level" in field["field"] for field in detail["fields"])


def test_bad_config_hash_is_refused(client: TestClient) -> None:
    payload = _payload({"aggregator_config_hash": "a" * 64})
    response = client.post("/harmonize", json=payload)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "config_hash_mismatch"
    assert detail["expected_prefix"] == main.state.config_hash[:12]


def test_coordinate_snap_mismatch_is_refused(client: TestClient, config_payload: dict) -> None:
    response = client.post("/harmonize", json=_payload(config_payload, cell_lat=[-12]))
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "cell_coordinate_mismatch"
    assert detail["expected_cell_lat"] == [-13]


def test_date_outside_sampling_windows_is_refused(client: TestClient, config_payload: dict) -> None:
    response = client.post("/harmonize", json=_payload(config_payload, date=["2022-03-15"]))
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "date_outside_sampling_windows"
    assert "2021-08-01" in detail["verified_windows"]


def test_late_delay_returns_refusal_not_a_number(client: TestClient, config_payload: dict) -> None:
    payload = _payload(config_payload, lst_aqua_h=[16.5], cell_lat=None, cell_lon=None)
    response = client.post("/harmonize", json=payload)
    assert response.status_code == 200
    cell = response.json()["cells"][0]
    assert cell["applicable"] is False
    assert cell["reason"] == "delay_outside_calibrated_range"
    assert cell["harmonized_frp_mw"] is None
    assert cell["interval_lower_mw"] is None
    assert cell["refusal_message"]


def test_unknown_region_is_rejected(client: TestClient, config_payload: dict) -> None:
    response = client.post("/harmonize", json=_payload(config_payload, region=["Europe"]))
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "validation_error"
    assert any("region" in field["field"] for field in detail["fields"])


def test_length_mismatch_is_rejected(client: TestClient, config_payload: dict) -> None:
    response = client.post(
        "/harmonize",
        json=_payload(config_payload, region=["Southern_Africa", "Amazon"]),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "validation_error"


def test_utc_without_longitude_is_rejected(client: TestClient, config_payload: dict) -> None:
    payload = _payload(config_payload)
    payload.pop("lst_aqua_h")
    payload["acquisition_time_utc"] = ["1200"]
    payload.pop("longitude")
    payload.pop("cell_lon")
    response = client.post("/harmonize", json=payload)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "validation_error"
    assert any("longitude" in field["message"] for field in detail["fields"])


def test_utc_and_lst_disagreement_is_refused(client: TestClient, config_payload: dict) -> None:
    payload = _payload(
        config_payload,
        acquisition_time_utc=["1200"],
        lst_aqua_h=[14.9],
    )
    response = client.post("/harmonize", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "lst_utc_mismatch"


def test_numeric_bounds_are_enforced(client: TestClient, config_payload: dict) -> None:
    for override in ({"frp_aqua_mw": [0.0]}, {"latitude": [91.0]}, {"scan_aqua": [0.0]}):
        response = client.post("/harmonize", json=_payload(config_payload, **override))
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Read-only endpoints
# ---------------------------------------------------------------------------


def test_health_version_and_alias_endpoints(client: TestClient) -> None:
    health = client.get("/health")
    assert health.status_code == 200
    health_body = health.json()
    assert health_body["status"] == "ok"
    assert health_body["model_loaded"] is True
    assert health_body["model"] == "H"
    assert health_body["data_hash_begins"] == "37423f49d223"
    assert health_body["pairs"] == 6313
    assert health_body["dataset_rows"] == 1_382_752

    version = client.get("/version").json()
    assert version["name"] == "Arkagni"
    assert version["served_model"] == "H"
    assert version["pipeline_version"] == "l2-l5-v1"
    assert version["model_artifact_sha256"] == main.state.model_sha256

    validity = client.get("/validity")
    audit = client.get("/audit")
    assert validity.status_code == 200
    assert validity.json() == audit.json()
    assert validity.json()["gate"]["coverage_floor"] == 0.70


def test_results_and_config_are_measured(client: TestClient) -> None:
    results = client.get("/results").json()
    assert results["pairs"]["count"] == 6313
    assert results["dataset"]["rows"] == 1_382_752
    assert results["models"]["served"] == "H"
    assert results["uncertainty"]["overall_coverage"] > 0.70

    config_body = client.get("/config").json()
    assert config_body["aggregator_config_hash"] == main.state.config_hash
    assert config_body["nominal_coverage"] == 0.8
    assert config_body["max_cells"] == 100_000
    assert "Southern_Africa" in config_body["regions"]
    assert config_body["grid"]["snap_rule"] == "floor"
    assert "coverage_below_floor" in config_body["refusal_codes"]


def test_observations_explorer_and_summary(client: TestClient) -> None:
    page = client.get("/observations", params={"page": 1, "page_size": 3})
    assert page.status_code == 200
    body = page.json()
    assert body["total"] == 1_382_752
    assert len(body["rows"]) == 3
    row = body["rows"][0]
    assert row["observation_id"]
    assert ":" in row["utc"]
    assert ":" in row["lst_display"]
    assert row["lst_derivation"] == "lst = (UTC hours + longitude / 15) mod 24"
    assert 0 <= row["flags_uint8"] <= 255

    filtered = client.get(
        "/observations",
        params={"region": "Amazon", "satellite": "N20", "year": 2024, "page_size": 2},
    ).json()
    assert filtered["total"] > 0
    assert all(item["region"] == "Amazon" for item in filtered["rows"])
    assert all(item["satellite"] == "N20" for item in filtered["rows"])

    summary = client.get("/observations/summary")
    assert summary.status_code == 200
    summary_body = summary.json()
    assert summary_body["status_counts"]["validated"] == 1_153_531
    assert summary_body["status_counts"]["excluded"] > 0
    assert summary_body["status_counts"]["flagged"] > 0
    sparse = {
        (note["year"], note["region"])
        for note in summary_body["sparse_notes"]
        if note["matched_pairs"] == 0
    }
    assert (2022, "Amazon") in sparse
    assert (2022, "Southern_Africa") in sparse


def test_real_cleaned_csvs_are_the_serving_source(client: TestClient) -> None:
    body = client.get("/ingestion").json()
    assert body["status"] == "ok"
    assert body["source_policy"].startswith("Read directly from the three cleaned CSVs")
    assert body["verification"]["passed"] is True
    assert body["data_hash"] == "37423f49d2235a911caaebbdc660388ed7e775333ae7f224672342720adf8290"
    assert body["data_hash"] == body["data_hash_expected"]
    assert body["dataset"]["rows"] == 1_382_752
    assert body["dataset"]["validated_rows"] == 1_153_531
    assert body["dataset"]["flags"] == {
        "type_not_0": 9084,
        "frp_not_above_zero": 267,
        "night": 227_329,
    }
    assert body["pairs"]["count"] == 6_313
    assert {source["filename"] for source in body["sources"]} == {
        "MODIS_SP_cleaned.csv",
        "VIIRS_SNPP_SP_cleaned.csv",
        "VIIRS_NOAA20_SP_cleaned.csv",
    }
    assert all(source["rows"] > 0 and len(source["sha256"]) == 64 for source in body["sources"])


def test_live_harmonization_is_computed_from_real_pairs(client: TestClient) -> None:
    body = client.get("/ingestion/harmonization").json()
    assert body["n_pairs"] == 6_313
    assert body["n_applicable"] == 6_136
    assert body["n_refused"] == 177
    assert body["refusals"] == {
        "delay_outside_calibrated_range": 128,
        "scan_out_of_range": 49,
    }
    assert body["coverage"] is not None and body["coverage"] > 0.70
    assert body["harmonized_rmse"] < body["raw_rmse"]
    assert len(body["examples"]) > 0
    assert all("observed_frp_snpp_mw" in row for row in body["examples"])


def test_results_expose_live_ingestion_metadata(client: TestClient) -> None:
    body = client.get("/results").json()
    assert body["live_ingestion"]["verification"]["passed"] is True
    assert body["live_ingestion"]["data_hash"] == body["provenance"]["data_hash"]


def test_audit_digital_twin_and_snapshot(client: TestClient) -> None:
    twin = client.get("/audit/digital-twin")
    assert twin.status_code == 200
    twin_body = twin.json()["digital_twin"]
    assert twin_body["available"] is True
    assert twin_body["passed"] is True
    assert twin_body["validation_status"] == "self_consistency_only"
    assert twin_body["max_absolute_error"] <= twin_body["tolerance_log_units"]

    snapshot = client.get("/audit/snapshot")
    assert snapshot.status_code == 200
    snapshot_body = snapshot.json()
    assert snapshot_body["schema_version"] == "pyroharmonize.audit.v1"
    assert snapshot_body["grouped_cv"]["served"] == "H"
    assert snapshot_body["regional_transfer"]["Amazon"]["verdict"] == "caution_h_worse_than_raw"
    assert snapshot_body["pairing_sensitivity"]["available"] is True
    assert snapshot_body["terra_extrapolation"]["n"] == 3847
    assert snapshot_body["digital_twin"]["passed"] is True
    assert "saturation" in snapshot_body["not_evaluated"]


def test_static_dashboard_or_api_banner(client: TestClient) -> None:
    root = client.get("/")
    assert root.status_code == 200
    if (PROJECT_ROOT / "frontend" / "dist" / "index.html").is_file():
        assert "Arkagni" in root.text
    else:
        assert root.json()["name"] == "Arkagni"


def test_startup_banner_prints_single_clickable_url(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ARKAGNI_SILENT_STARTUP", raising=False)
    monkeypatch.delenv("ARKAGNI_URL", raising=False)

    main._announce_urls()
    out = capsys.readouterr().out

    # Exactly one raw, unwrapped URL so terminals can auto-link it.
    assert out.strip() == "http://localhost:8000"
    assert "\x1b[" not in out


def test_startup_banner_respects_silent_flag(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARKAGNI_SILENT_STARTUP", "1")

    main._announce_urls()

    assert capsys.readouterr().out == ""
