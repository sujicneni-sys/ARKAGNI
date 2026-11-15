"""L6 API contract and parity tests.

The tests start the real FastAPI lifespan, which hash-verifies and loads the
served artefact.  They do not mock the science or the model.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pyroharmonize.api import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def config_payload(client: TestClient) -> dict:
    response = client.get("/config")
    assert response.status_code == 200
    return response.json()


def test_health_and_version(client: TestClient) -> None:
    health = client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert body["model_loaded"] is True
    assert body["model"] == "H"
    assert body["data_hash_begins"] == "37423f49d223"

    version = client.get("/version").json()
    assert version["data_hash"].startswith("37423f49d223")
    assert version["pipeline_version"] == "l2-l5-v1"
    assert len(version["config_hash"]) == 64


def test_validity_and_audit_are_identical(client: TestClient) -> None:
    validity = client.get("/validity")
    audit = client.get("/audit")
    assert validity.status_code == 200
    assert audit.status_code == 200
    assert validity.json() == audit.json()


def test_results_are_the_measured_pipeline_output(client: TestClient) -> None:
    body = client.get("/results").json()
    assert body["pairs"]["count"] == 6313
    assert body["dataset"]["rows"] == 1382752
    assert body["models"]["served"] == "H"
    assert body["uncertainty"]["overall_coverage"] > 0.70


def test_config_and_static_dashboard(client: TestClient) -> None:
    config_payload = client.get("/config").json()
    assert len(config_payload["aggregator_config_hash"]) == 64
    assert config_payload["nominal_coverage"] == 0.8
    assert "Southern_Africa" in config_payload["regions"]

    root = client.get("/")
    assert root.status_code == 200
    assert "Arkagni" in root.text
    assert "index.html" not in root.text[:80].lower()

    script = client.get("/app.js")
    assert script.status_code == 200
    assert "harmonize" in script.text


def test_harmonize_accepts_a_supported_cell(client: TestClient, config_payload: dict) -> None:
    payload = {
        "aggregator_config_hash": config_payload["aggregator_config_hash"],
        "region": ["Southern_Africa"],
        "date": ["2021-08-01"],
        "latitude": [-12.3],
        "longitude": [25.7],
        "frp_aqua_mw": [180.0],
        "detections": [12],
        "lst_aqua_h": [14.9],
        "scan_aqua": [1.1],
        "area_ratio": [1.2],
    }
    response = client.post("/harmonize", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    cell = body["cells"][0]
    assert cell["applicable"] is True
    assert cell["reason"] is None
    assert cell["interval_lower_mw"] < cell["harmonized_frp_mw"] < cell["interval_upper_mw"]
    assert cell["delay_bin"] == "(1, 1.5]"
    # This reproduces the independently documented v9 example.
    assert abs(cell["harmonized_frp_mw"] - 246.8106) < 0.01


def test_harmonize_refuses_late_delay(client: TestClient, config_payload: dict) -> None:
    payload = {
        "aggregator_config_hash": config_payload["aggregator_config_hash"],
        "region": ["Southern_Africa"],
        "date": ["2021-08-01"],
        "frp_aqua_mw": [180.0],
        "detections": [12],
        "lst_aqua_h": [16.5],
        "scan_aqua": [1.1],
    }
    response = client.post("/harmonize", json=payload)
    assert response.status_code == 200
    cell = response.json()["cells"][0]
    assert cell["applicable"] is False
    assert cell["reason"] == "delay_outside_calibrated_range"
    assert cell["harmonized_frp_mw"] is None


def test_harmonize_rejects_bad_hash(client: TestClient) -> None:
    payload = {
        "aggregator_config_hash": "a" * 64,
        "region": ["Southern_Africa"],
        "frp_aqua_mw": [180.0],
        "detections": [12],
        "lst_aqua_h": [14.9],
        "scan_aqua": [1.1],
    }
    response = client.post("/harmonize", json=payload)
    assert response.status_code == 422
    assert "does not match" in response.json()["detail"]


def test_harmonize_rejects_out_of_window_date(client: TestClient, config_payload: dict) -> None:
    payload = {
        "aggregator_config_hash": config_payload["aggregator_config_hash"],
        "region": ["Southern_Africa"],
        "date": ["2022-03-15"],
        "frp_aqua_mw": [180.0],
        "detections": [12],
        "lst_aqua_h": [14.9],
        "scan_aqua": [1.1],
    }
    response = client.post("/harmonize", json=payload)
    assert response.status_code == 422
    assert "outside the verified" in response.json()["detail"]


def test_harmonize_rejects_length_mismatch(client: TestClient, config_payload: dict) -> None:
    payload = {
        "aggregator_config_hash": config_payload["aggregator_config_hash"],
        "region": ["Southern_Africa", "Amazon"],
        "frp_aqua_mw": [180.0],
        "detections": [12],
        "lst_aqua_h": [14.9],
        "scan_aqua": [1.1],
    }
    response = client.post("/harmonize", json=payload)
    assert response.status_code == 422


def test_harmonize_rejects_unknown_region(client: TestClient, config_payload: dict) -> None:
    payload = {
        "aggregator_config_hash": config_payload["aggregator_config_hash"],
        "region": ["Europe"],
        "frp_aqua_mw": [180.0],
        "detections": [12],
        "lst_aqua_h": [14.9],
        "scan_aqua": [1.1],
    }
    response = client.post("/harmonize", json=payload)
    assert response.status_code == 422
    assert "unsupported region" in str(response.json())


def test_harmonize_rejects_extra_field(client: TestClient, config_payload: dict) -> None:
    payload = {
        "aggregator_config_hash": config_payload["aggregator_config_hash"],
        "region": ["Southern_Africa"],
        "frp_aqua_mw": [180.0],
        "detections": [12],
        "lst_aqua_h": [14.9],
        "scan_aqua": [1.1],
        "pixel_level": ["not allowed"],
    }
    response = client.post("/harmonize", json=payload)
    assert response.status_code == 422


def test_observations_pagination_and_filters(client: TestClient) -> None:
    first = client.get("/observations", params={"page": 1, "page_size": 3})
    assert first.status_code == 200
    body = first.json()
    assert body["total"] == 1382752
    assert len(body["rows"]) == 3
    assert body["rows"][0]["observation_id"]

    filtered = client.get(
        "/observations",
        params={"region": "Amazon", "satellite": "N20", "year": 2024, "page_size": 2},
    ).json()
    assert filtered["total"] > 0
    assert all(row["region"] == "Amazon" for row in filtered["rows"])
    assert all(row["satellite"] == "N20" for row in filtered["rows"])
    assert all(row["date"].startswith("2024") for row in filtered["rows"])

    empty = client.get(
        "/observations", params={"region": "Amazon", "year": 1999}
    ).json()
    assert empty["total"] == 0
    assert empty["rows"] == []
