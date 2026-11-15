# Arkagni

http://localhost:8000

---

## 1. Quick start (Docker)

```bash
docker compose up --build
```

| Service | URL | Purpose |
|---|---|---|
| Arkagni | <http://localhost:8000> | Dashboard at `/`, API docs at `/docs` |
| Health | <http://localhost:8000/health> | Hash-verified readiness probe |

The single container serves the built React dashboard and the FastAPI API on
one origin. It contains the hash-verified model, results, conformal table, and
the processed canonical tables needed by the explorer and audit pages.

Run the reproducible batch profile (L2-L5 regeneration, release verification,
and targeted tests) with:

```bash
docker compose --profile batch run --rm --build batch
```

Stop the stack:

```bash
docker compose down
```

---

## 2. Local development

Python 3.12 is required. The project uses a project-local virtual environment.

```powershell
# Python
uv sync

# Dashboard dependencies (Node 20+)
npm --prefix frontend ci
```

### One command: build and serve

```powershell
.venv\Scripts\python.exe scripts\run_local.py
# or: make PYTHON=.venv/Scripts/python.exe dev
```

The launcher builds the React dashboard into `frontend/dist`, starts FastAPI on
port 8000, and prints the single clickable URL:

```
http://localhost:8000
```

The SPA is served at `/`, the API at `/health`, `/version`, etc., and OpenAPI
docs at `/docs`. There is no separate frontend dev server. Set
`ARKAGNI_SKIP_BUILD=1` to reuse an existing `frontend/dist`, or
`ARKAGNI_SILENT_STARTUP=1` to suppress the lifespan banner.

To serve an already-built dashboard directly:

```powershell
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

At startup the API reads the three real cleaned CSVs
(`MODIS_SP_cleaned.csv`, `VIIRS_SNPP_SP_cleaned.csv`,
`VIIRS_NOAA20_SP_cleaned.csv`) from `data/` or the frozen raw tree, rebuilds the
canonical pixels, cell-days and Aqua-SNPP pairs, and verifies them against the
frozen measured release. Startup takes roughly 23-26 seconds because the source
files total about 288 MB. Missing files, schema drift, a hash mismatch, or a
count mismatch raise and stop service; there is no synthetic fallback.

`make` targets are provided for Unix-like shells and Git Bash. On Windows,
override the interpreter path:

```bash
make PYTHON=.venv/Scripts/python.exe dev
make PYTHON=.venv/Scripts/python.exe test
make PYTHON=.venv/Scripts/python.exe verify
make PYTHON=.venv/Scripts/python.exe reproduce
make PYTHON=.venv/Scripts/python.exe run-local
```

`make dev` builds the dashboard and serves Arkagni from a single origin on
port 8000. `make run-local` does the same via the Make build dependency.
`make test` runs the full suite.

---

## 3. Reproduce the science

The frozen L1 canonical table is the input to the reproducible L2-L5 analysis:

```powershell
.venv\Scripts\python.exe scripts\03_run_analysis.py --force
.venv\Scripts\python.exe scripts\04_verify_release.py
.venv\Scripts\python.exe -m pytest
```

`04_verify_release.py` fails loudly if any of the following drift:

- the canonical science block no longer hashes to `aggregator_config_hash`;
- regenerated batch outputs differ from the frozen release copies;
- the model, results, or conformal table differ from `backend/artifacts/registry.json`;
- the served pickle is not model `H`;
- the gate floors or conformal quantiles change;
- the pure core no longer reproduces the documented applicability counts.

Full L1 regeneration is possible from the frozen raw archive with
`scripts/00_freeze_inputs.py`, `scripts/01_l1_reproduce_cleaning.py`, and
`scripts/02_l1_build_canonical.py`. The raw archive is intentionally excluded
from container images (3.6 GB) and from version control.

---

## 4. Measured system state

These are measured outputs, not placeholders.

| Quantity | Value |
|---|---|
| Canonical observations | 1,382,752 rows |
| Aqua-SNPP calibration pairs | 6,313 cell-days |
| Study regions | Amazon, Australia, California, Southern Africa |
| Served model | `H` (physics + regional offsets) |
| Served-model applicable pairs | 6,136 |
| `delay_outside_calibrated_range` | 128 |
| `scan_out_of_range` | 49 |
| Overall conformal coverage | 0.809599 |
| Late bin `(2, 3.5]` coverage | 0.660377 (n = 53) |
| Gate floors | >= 40 pairs, coverage >= 0.70 |
| Data hash | `37423f49d223…` |
| Config hash | `4afd3392e89d812f5478d33da693abae40ad11d5e9b18a82a72a0785fe6d0c6d` |
| Model artifact SHA-256 | `d3e7645f…c2a7c579672715` |
| Results SHA-256 | `6f6d09df…2aab552325fb0c` |

Grouped-CV RMSE (log-ratio units): B0 `1.01545`, B1 `1.008166`, B2
`0.993157`, P `1.002762`, **H `0.991605`**, M `0.938354`, PR `0.934555`.
Model H is served because it is the pre-registered selection winner; the
research ML models are reported for comparison but are **not** eligible for
serving.

---

## 5. Architecture

```
L1  Real cleaned-CSV ingestion  backend/ingestion.py  data/*_SP_cleaned.csv
L2  Aqua-SNPP pairing          backend/ingestion.py  cell-days -> pairs
L3  Model fitting              seven candidate families B0..PR (frozen release)
L4  Audit engine               backend/audit.py
L5  Pure science core          backend/core.py     (no I/O, no clock, no network)
L6  Strict API boundary        backend/main.py     (no science)
L7  Research dashboard         frontend/           React + Tailwind + Recharts
```

`backend/ingestion.py` is the only serving-side module that reads the source
files. It hashes the three cleaned CSVs in documented order, builds canonical
pixels, aggregates validated pixels to 1-degree cell-days, pairs Aqua with
Suomi-NPP, and compares the result with `backend/artifacts/results.json`. The
shared aggregation contract in `data/adapters.py` is the same one used by the
batch pipeline.

The L5 core is array-vectorised and is imported by training, batch analysis,
audit, and serving. The L6 service validates requests, snaps coordinates, calls
`core.harmonize`, and serialises the result. It does not fit, calibrate, or
compute residuals.

Artifact integrity is checked at process start. The service refuses to start if
the model pickle, results file, or conformal table does not match the SHA-256
recorded in `backend/artifacts/registry.json`, if the canonical science block no
longer hashes to the value embedded in the results provenance, or if the real
cleaned CSVs no longer reproduce the frozen counts and pairs. An unverified
pickle is never loaded and no cached or synthetic source is substituted.

---

## 6. API

Read-only endpoints:

| Endpoint | Content |
|---|---|
| `GET /health` | Loaded model, hashes, row/pair counts |
| `GET /version` | Provenance, library versions, limitations |
| `GET /validity`, `GET /audit` | Gate, validity map, uncertainty, limitations |
| `GET /results` | Full measured results payload plus the live ingestion manifest |
| `GET /config` | Config hash, regions, grid, refusal codes, examples |
| `GET /observations` | Paginated explorer with filters |
| `GET /observations/summary` | Distributions, flags, sparse-year notices |
| `GET /ingestion` | Source files, hashes, rebuilt counts, release verification |
| `GET /ingestion/harmonization` | Frozen H replayed over every real Aqua-SNPP pair |
| `POST /ingestion/rebuild` | Re-read the cleaned CSVs without restarting |
| `GET /audit/digital-twin` | Injected-offset round-trip audit |
| `GET /audit/snapshot` | Grouped CV, transfer matrix, pairing sensitivity, Terra test |

Live harmonization: `POST /harmonize`. The body is columnar; one element in each
list is one 1-degree cell-day. Unknown fields are rejected.

```json
{
  "aggregator_config_hash": "4afd3392e89d812f5478d33da693abae40ad11d5e9b18a82a72a0785fe6d0c6d",
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
  "area_ratio": [1.2]
}
```

The published example returns `applicable: true`, cell `S13E025`, delay bin
`(1, 1.5]`, point estimate `246.81 MW`, and 80% interval
`[71.79, 848.54] MW`.

A refused cell returns `applicable: false`, a machine-readable `reason`, a human
`refusal_message`, and `null` in every predictive field. It never returns an
imputed number.

Public batch testing: `POST /live-analysis?filename=rows.csv` accepts raw CSV or
Parquet bytes (up to 5 MB / 2,000 rows). It maps documented column aliases
(`delay_h`, `acquisition_time_utc`, …) onto the same columnar request and returns
the identical `/harmonize` payload, so uploads and single cell-days share one
science path.

### Request guards

- `aggregator_config_hash` must equal the training aggregation hash.
- All arrays must have equal length; maximum 100,000 cells.
- Latitude/longitude must lie in valid ranges and `cell_lat`/`cell_lon` must
  equal `floor(coordinate)` on the 1-degree grid.
- Dates must fall inside the verified five-day sampling windows.
- `lst_aqua_h` or `acquisition_time_utc` is required. UTC requires longitude.
- If both LST and UTC are supplied, they must agree after longitude correction.
- Validation errors are returned as structured 422 bodies with
  `detail.code = "validation_error"` and field-level messages.

### Refusal codes

`insufficient_calibration_pairs`, `coverage_below_floor`,
`delay_outside_calibrated_range`, `scan_out_of_range`,
`region_not_in_training`.

The late delay bin has 53 calibration pairs but honest coverage `0.66 < 0.70`,
so it is refused by the pre-registered coverage floor. The measured delay domain
upper bound (`1.98 h`) is tighter than the nominal bin edge, so most late cells
are refused as outside the calibrated domain before the coverage reason can
fire.

---

## 7. Scientific contract

### Local solar time

```
lst = (UTC hours + longitude / 15) mod 24
```

Local Solar Time is stored as a zero-padded integer (`01:18` -> `118`) and
rendered as `01:18`, never as `11:08`. Both UTC and LST are shown in the
explorer.

### Pixel flags

Rows are retained, never silently deleted. The `uint8` bitmask is:

| Bit | Meaning |
|---|---|
| 0 | `type != 0` |
| 1 | `FRP <= 0` or non-finite |
| 2 | night (`daynight != D`) |
| 3-7 | reserved: saturation, plume scattering, canopy occlusion, not evaluated |

Validation requires `type == 0 AND FRP > 0 AND daynight == D`. Flagged and
excluded rows remain visible in the explorer.

### Conformal uncertainty

The interval is split-conformal by pre-registered delay bin with the
finite-sample rank correction. The 80% interval is the primary visual; the point
estimate is secondary. Coverage is honest out-of-fold coverage, not in-sample
fit.

### Applicability gate

A bin is served only when it has at least 40 calibration pairs **and** at least
0.70 out-of-fold coverage. The gate is applied before any number is returned.
Refusal is a feature: thin support is not extrapolated.

### Pairing sensitivity and transfer

The cell-day-sum and near-coincident pairing slopes have opposite signs
(`-0.11897` vs `+0.30774`); pairing is a reported confounder, not a licence to
choose the convenient sign. Leave-one-region-out transfer shows H worse than raw
in Amazon and Australia; the dashboard marks those regions as caution rather
than hiding them. The Terra out-of-regime test is not independent Terra
validation.

---

## 8. Dashboard

Seven hash-routed pages:

1. **Overview** - system state, measured metrics, Leaflet study-region map,
   animated schematic bowtie sampling footprint, composition and support.
2. **Data Explorer** - distributions, dual UTC/LST display, active ingest
   calendar, flag map, sparse-2022 notice.
3. **FRP Harmonization** - log FRP slider, coordinate snap indicator, live
   validation guard, before/after breakdown, conformal range bar.
4. **Uncertainty Analysis** - coverage by delay bin, interval width, primary
   interval visualization.
5. **Model Comparison** - seven models, grouped CV, Decision Boundary /
   Safe Zone separating served H from research ML models.
6. **Audit & Validation** - grouped CV folds, regional transfer matrix, pairing
   sensitivity sign change, Terra test, digital twin, identifiability.
7. **Live Analysis** - public CSV/Parquet upload or single cell-day tester, run
   through the frozen harmonization pipeline with pastel at-a-glance results.

The bowtie overlay is explicitly labelled as a schematic sampling-footprint
indicator, not a fire perimeter or individual detection location.

---

## 9. Repository layout

```
backend/
  core.py                  pure L5 science
  main.py                  L6 FastAPI service
  audit.py                 L4 audit engine
  config.py                hash-verified config/registry access
  artifacts/               served model, results, conformal table, registry
frontend/
  src/                     7-page React dashboard
data/processed/            frozen canonical and pair tables
artifacts/                 reproducible batch outputs
scripts/                   00 freeze, 01-02 L1, 03 analysis, 04 verify, run_local
tests/                     pytest suite
config.yaml                canonical science block
docker-compose.yml         single Arkagni server + batch profile
Dockerfile.api             multi-stage dashboard build + serving image
Dockerfile.batch           reproducible batch image
```

---

## 10. Testing

```bash
.venv/Scripts/python.exe -m pytest        # Windows
python -m pytest                          # Unix
```

Coverage includes Phase 0 manifests, L2 pairing, model artifacts, the legacy API
contract, the new pure-core parity, hash verification, structured 422 mapping,
coordinate snap, date windows, LST/UTC agreement, applicability refusals, and
all read-only endpoints.

Current suite: **80 passed, 1 skipped** (the source ZIP is not in this checkout;
the extracted raw tree and every recorded file hash are still verified).

---

## 11. Limitations

- The model is trained on four sampled regions and verified five-day windows;
  it is not a global fire product.
- Conformal intervals describe cell-day noise, not individual-pixel accuracy.
- Saturation, plume scattering, and canopy occlusion are not evaluated; their
  flag bits remain reserved.
- The Terra test is out-of-regime application, not independent Terra validation.
- Pairing confounding remains pending a scan-controlled test.
- 2022 matched pairs exist only for Australia and California; zero matched pairs
  for Amazon and Southern Africa is displayed as a calibration interrupt, not as
  zero raw observations.
- The dashboard's bowtie is schematic, not a fire perimeter.
- No geostationary independent reference is used.
