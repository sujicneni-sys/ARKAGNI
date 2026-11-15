"""Release verifier - no fitting, no mutation, fail loudly.

Run after `scripts/03_run_analysis.py --force` and before serving.  The script
checks every hash boundary in the release:

* the canonical science block still hashes to the value embedded in results;
* regenerated batch outputs match the frozen release copies;
* the release copies match `backend/artifacts/registry.json`;
* the served pickle is identified only after its SHA-256 matches;
* the pure L5 core reproduces the documented applicability counts.

Exit code 0 means the release is internally consistent.  It does **not** claim
that the scientific model is externally valid.
"""

from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from backend import config, core  # noqa: E402

EXPECTED = {
    "active_model": "H",
    "data_hash_begins": "37423f49d223",
    "pairs": 6313,
    "rows": 1_382_752,
    "applicable": 6136,
    "delay_outside_calibrated_range": 128,
    "scan_out_of_range": 49,
}


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def _sha(path: Path) -> str:
    require(path.is_file(), f"missing artifact: {path}")
    return config.sha256_file(path)


def main() -> int:
    checks: list[dict[str, Any]] = []

    def check(name: str, detail: Any) -> None:
        checks.append({"check": name, "status": "pass", "detail": detail})

    try:
        payload = config.load_config()
        registry = config.load_registry()
        require(registry.get("active_model") == EXPECTED["active_model"], "registry active_model is not H")
        check("registry.active_model", registry["active_model"])

        computed_config_hash = config.config_hash(payload)
        check("config.sha256", computed_config_hash)

        release_results = config.ARTIFACTS_DIR / "results.json"
        release_model = config.ARTIFACTS_DIR / "model_H.pkl"
        release_conformal = config.ARTIFACTS_DIR / "conformal.json"

        results_sha = _sha(release_results)
        model_sha = _sha(release_model)
        conformal_sha = _sha(release_conformal)
        require(results_sha == registry["results"]["sha256"], "release results hash mismatch")
        require(model_sha == registry["model"]["sha256"], "release model hash mismatch")
        require(conformal_sha == registry["conformal"]["sha256"], "release conformal hash mismatch")
        check(
            "release.sha256",
            {
                "results": results_sha,
                "model": model_sha,
                "conformal": conformal_sha,
            },
        )

        results = json.loads(release_results.read_text(encoding="utf-8"))
        require(results["provenance"]["config_hash"] == computed_config_hash, "config hash drift")
        require(
            results["provenance"]["model_artifact_sha256"] == model_sha,
            "results and model artifact disagree",
        )
        require(
            results["provenance"]["data_hash"].startswith(EXPECTED["data_hash_begins"]),
            "data hash anchor drift",
        )
        require(results["models"]["served"] == EXPECTED["active_model"], "served model drift")
        require(int(results["pairs"]["count"]) == EXPECTED["pairs"], "pair count drift")
        require(int(results["dataset"]["rows"]) == EXPECTED["rows"], "row count drift")
        check(
            "results.provenance",
            {
                "config_hash": computed_config_hash,
                "data_hash": results["provenance"]["data_hash"],
                "pairs": results["pairs"]["count"],
                "rows": results["dataset"]["rows"],
            },
        )

        # Regenerated batch outputs must agree with the frozen release copies.
        batch_results = PROJECT_ROOT / "artifacts" / "results" / "results.json"
        batch_model = PROJECT_ROOT / "artifacts" / "models" / "model_H.pkl"
        if batch_results.is_file():
            require(_sha(batch_results) == results_sha, "regenerated results differ from release")
            require(_sha(batch_model) == model_sha, "regenerated model differs from release")
            check("batch_outputs_match_release", True)
        else:
            check("batch_outputs_match_release", "batch outputs not present; skipped")

        with release_model.open("rb") as handle:
            artifact = pickle.load(handle)
        require(artifact.get("served_model") == EXPECTED["active_model"], "pickle is not the served model")
        require(float(artifact["conformal"]["alpha"]) == 0.2, "conformal alpha drift")
        require(int(artifact["gate"]["min_calibration_pairs"]) == 40, "gate pair floor drift")
        require(float(artifact["gate"]["coverage_floor"]) == 0.70, "gate coverage floor drift")
        check(
            "artifact.gate",
            {
                "served_model": artifact["served_model"],
                "alpha": artifact["conformal"]["alpha"],
                "min_calibration_pairs": artifact["gate"]["min_calibration_pairs"],
                "coverage_floor": artifact["gate"]["coverage_floor"],
            },
        )

        conformal = json.loads(release_conformal.read_text(encoding="utf-8"))
        require(conformal["alpha"] == artifact["conformal"]["alpha"], "conformal metadata drift")
        for label in core.DELAY_BIN_LABELS:
            require(
                conformal["calibration"][label]["quantile"]
                == artifact["conformal"]["bins"][label]["quantile"],
                f"conformal quantile drift in bin {label}",
            )
        check("conformal.quantiles_match_artifact", list(core.DELAY_BIN_LABELS))

        pairs_path = config.PROCESSED_DIR / "pairs_aqua_snpp.parquet"
        require(pairs_path.is_file(), f"missing pair table: {pairs_path}")
        pairs = pd.read_parquet(pairs_path)
        require(len(pairs) == EXPECTED["pairs"], "pair table length drift")
        output = core.predict_harmonized(pairs, artifact)
        counts = output["reason"].value_counts(dropna=False).to_dict()
        applicable = int(output["applicable"].sum())
        require(applicable == EXPECTED["applicable"], f"applicable count drift: {applicable}")
        require(
            int(counts.get("delay_outside_calibrated_range", 0))
            == EXPECTED["delay_outside_calibrated_range"],
            "delay refusal count drift",
        )
        require(
            int(counts.get("scan_out_of_range", 0)) == EXPECTED["scan_out_of_range"],
            "scan refusal count drift",
        )
        refused = output.loc[~output["applicable"]]
        require(refused["harmonized_frp_mw"].isna().all(), "refused rows contain a number")
        valid = output.loc[output["applicable"]]
        require(
            bool(
                np.all(valid["interval_lower_mw"] > 0)
                and np.all(valid["interval_upper_mw"] > valid["interval_lower_mw"])
            ),
            "interval construction drift",
        )
        check(
            "core.parity",
            {
                "pairs": int(len(pairs)),
                "applicable": applicable,
                "delay_outside_calibrated_range": int(
                    counts.get("delay_outside_calibrated_range", 0)
                ),
                "scan_out_of_range": int(counts.get("scan_out_of_range", 0)),
            },
        )

    except (VerificationError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "fail", "error": str(exc), "checks": checks}, indent=2))
        return 1

    print(json.dumps({"status": "pass", "checks": checks}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
